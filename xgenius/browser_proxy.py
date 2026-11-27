"""Verify Chrome's HTTP proxy through a background extension worker."""

import base64
import hashlib
import ipaddress
import json
import socket
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from xgenius.browser_cdp import CdpError, browser_connection
from xgenius.proxy_service import IP_CHECK_URL, HttpProxy, ProxyCheckError, parse_ip_response


# A public manifest key gives the worker the same known ID in every launch.
_EXTENSION_KEY = (
    "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEArVUZnWaikBrTezvqckptpqLJDTJA4WX"
    "bJGDNkFPEysVH13auvUuGanJ5xs4ggJgZJYM2Nj5tT5iH9tCOz8aOVMFeSQuFm0JtFWgCFIDMI"
    "qcRN1F74ixCGcaXM+WxlJxWX6tQ8Nq1Z7uc+rvvefe6bZQIu27804DvYJpy7arb7CHKwzz0PvI"
    "pkpJOgC/aCwWtnoclb7wsDHAnwqsi6How+DxMx6W6Z91g+7hEyT6Dqt1tjT0G8r6KG47R8MFH"
    "Je28euXLDG3I407s04mv4Ve8otOY/5yIQlrWCDdRXRKgNYNEdRgPnfh1QFCdejR8zBhWXJ0nn8"
    "DwRP86S5avJS7GgQIDAQAB"
)
_EXTENSION_ID = hashlib.sha256(base64.b64decode(_EXTENSION_KEY)).hexdigest()[:32].translate(
    str.maketrans("0123456789abcdef", "abcdefghijklmnop")
)
PROXY_WORKER_URL = f"chrome-extension://{_EXTENSION_ID}/background.js"
_AUTH_ERROR = "Chrome proxy authentication failed (407). Check login and password."
_CONNECTION_ERROR = "Chrome could not connect through the proxy. Check host, port and access."
_WORKER_ERROR = "Chrome could not start its proxy verification worker. Check browser extension support and retry."
_CHECK_URLS=(IP_CHECK_URL,'https://checkip.amazonaws.com/')


class _ServiceError(ProxyCheckError):
    pass


def prepare_proxy_extension(proxy: HttpProxy):
    """Create the private per-process extension and its proxy challenge handler."""
    extension = tempfile.TemporaryDirectory(prefix="xanty_proxy_")
    try:
        path = Path(extension.name)
        manifest = {
            "manifest_version": 3,
            "key": _EXTENSION_KEY,
            "name": "XAnty Proxy",
            "version": "1.1.0",
            "permissions": ["webRequest", "webRequestAuthProvider"],
            "host_permissions": ["<all_urls>"] if proxy.username else ["https://api.ipify.org/*","https://api64.ipify.org/*","https://checkip.amazonaws.com/*"],
            "background": {"service_worker": "background.js"},
        }
        credentials = {"username": proxy.username, "password": proxy.password} if proxy.username else None
        worker = (
            f"const credentials = {json.dumps(credentials)};\n"
            f"const proxyHost = {json.dumps(proxy.host.lower().rstrip('.'))};\n"
            f"const proxyPort = {proxy.port};\n"
            "const attempted = new Set();\n"
            "const filter = {urls: ['<all_urls>']};\n"
            "chrome.webRequest.onAuthRequired.addListener((details, callback) => {\n"
            "  if (!details.isProxy) { callback({}); return; }\n"
            "  const host = details.challenger.host.toLowerCase().replace(/^\\[|\\]$|\\.$/g, '');\n"
            "  if (!credentials || host !== proxyHost || details.challenger.port !== proxyPort ||\n"
            "      attempted.has(details.requestId)) { callback({cancel: true}); return; }\n"
            "  attempted.add(details.requestId);\n"
            "  callback({authCredentials: credentials});\n"
            "}, filter, ['asyncBlocking']);\n"
            "chrome.webRequest.onCompleted.addListener(details => attempted.delete(details.requestId), filter);\n"
            "chrome.webRequest.onErrorOccurred.addListener(details => attempted.delete(details.requestId), filter);\n"
            "chrome.runtime.onStartup.addListener(() => {});\n"
            "globalThis.xantyProxyReady = true;\n"
        )
        (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (path / "background.js").write_text(worker, encoding="utf-8")
        return extension
    except Exception:
        extension.cleanup()
        raise ProxyCheckError("Cannot prepare proxy verification for Chrome.") from None


def _find_worker(connection):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        targets = connection.call('Target.getTargets', {}, timeout=1).get('targetInfos', [])
        for target in targets:
            if target.get('type') == 'service_worker' and target.get('url') == PROXY_WORKER_URL:
                return target['targetId']
        time.sleep(.05)
    raise ProxyCheckError(_WORKER_ERROR)


def _wait_for_worker(connection, session_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            result = connection.call('Runtime.evaluate', {
                'expression': 'globalThis.xantyProxyReady === true',
                'returnByValue': True,
            }, session_id=session_id, timeout=1)
        except CdpError:
            result = {}
        if result.get('result', {}).get('value') is True:
            return
        time.sleep(.05)
    raise ProxyCheckError(_WORKER_ERROR)


def _address(value):
    ip = ipaddress.ip_address(value.strip('[]'))
    return getattr(ip, 'ipv4_mapped', None) or ip


def _check_proxy_socket(proxy, response):
    if (response.get('remotePort') != proxy.port or response.get('fromDiskCache')
            or response.get('fromPrefetchCache') or response.get('fromServiceWorker')):
        raise ProxyCheckError("Chrome did not connect through the configured proxy.")
    try:
        remote_address = _address(response['remoteIPAddress'])
        endpoints = socket.getaddrinfo(proxy.host, proxy.port, type=socket.SOCK_STREAM)
        if remote_address in {_address(endpoint[4][0]) for endpoint in endpoints}:
            return
    except (KeyError, TypeError, ValueError, OSError):
        pass
    raise ProxyCheckError("Chrome did not connect through the configured proxy.")


def _check_worker_request(connection, session_id, proxy, endpoint=IP_CHECK_URL):
    url = endpoint+('&' if '?' in endpoint else '?')+'xanty_probe='+uuid4().hex
    expression = f"""
    (async () => {{
        try {{
            const response = await fetch({json.dumps(url)}, {{
                cache: 'no-store', credentials: 'omit', redirect: 'error',
                signal: AbortSignal.timeout(9000)
            }});
            return {{status: response.status, body: response.ok ? await response.text() : ''}};
        }} catch (error) {{
            return {{error: error.name}};
        }}
    }})()
    """
    connection.call('Network.enable', {}, session_id=session_id)
    result = connection.call('Runtime.evaluate', {
        'expression': expression, 'awaitPromise': True, 'returnByValue': True,
    }, session_id=session_id, timeout=11)
    value = result.get('result', {}).get('value')
    if not isinstance(value, dict):
        raise ProxyCheckError(_WORKER_ERROR)
    request = connection.wait_event(
        'Network.requestWillBeSent', session_id=session_id, timeout=1,
        predicate=lambda event: event.get('request', {}).get('url') == url,
    )
    request_id = request['requestId']

    def is_probe(event):
        return event.get('requestId') == request_id

    if value.get('error'):
        failure = connection.wait_event('Network.loadingFailed', session_id=session_id, predicate=is_probe, timeout=1)
        error = failure.get('errorText', '')
        if error in ('net::ERR_INVALID_AUTH_CREDENTIALS', 'net::ERR_PROXY_AUTH_REQUESTED',
                     'net::ERR_MISSING_AUTH_CREDENTIALS', 'net::ERR_PROXY_AUTH_UNSUPPORTED'):
            raise ProxyCheckError(_AUTH_ERROR)
        if value['error'] == 'TimeoutError':
            raise _ServiceError("Chrome proxy verification timed out. Check the proxy and network.")
        if error.startswith('net::ERR_CERT_'):
            raise ProxyCheckError("Chrome HTTPS check failed through the proxy (certificate error).")
        if error in ('net::ERR_CONNECTION_RESET', 'net::ERR_CONNECTION_CLOSED',
                     'net::ERR_EMPTY_RESPONSE', 'net::ERR_NAME_NOT_RESOLVED',
                     'net::ERR_TIMED_OUT', 'net::ERR_CONNECTION_TIMED_OUT',
                     'net::ERR_TUNNEL_CONNECTION_FAILED'):
            raise _ServiceError("Chrome could not reach the IP check service through the proxy.")
        raise ProxyCheckError(_CONNECTION_ERROR)

    status = value.get('status')
    if status == 407:
        raise ProxyCheckError(_AUTH_ERROR)
    if status != 200:
        if type(status) is int and 100 <= status <= 599:
            raise _ServiceError(f"Chrome IP check returned HTTP {status} through the proxy.")
        raise ProxyCheckError(_CONNECTION_ERROR)
    event = connection.wait_event('Network.responseReceived', session_id=session_id, predicate=is_probe, timeout=1)
    _check_proxy_socket(proxy, event['response'])
    try:return parse_ip_response(value.get('body', ''))
    except ProxyCheckError as exc:raise _ServiceError(str(exc)) from None


def verify_browser_proxy(browser, proxy: HttpProxy, expected_ip=None) -> str:
    """Return Chrome's observed exit IP after verifying its proxy socket.

    The HTTP preflight and Chrome can legitimately have different exit IPs.
    """
    try:
        with browser_connection(browser, timeout=10) as connection:
            target_id = _find_worker(connection)
            session_id = connection.call('Target.attachToTarget', {'targetId': target_id, 'flatten': True})['sessionId']
            try:
                _wait_for_worker(connection, session_id)
                for index,endpoint in enumerate(_CHECK_URLS):
                    try:return _check_worker_request(connection,session_id,proxy,endpoint)
                    except _ServiceError:
                        if index==len(_CHECK_URLS)-1:raise
            finally:
                try:
                    connection.call('Target.detachFromTarget', {'sessionId': session_id}, timeout=1)
                except CdpError:
                    pass
    except CdpError:
        raise ProxyCheckError(_CONNECTION_ERROR) from None
