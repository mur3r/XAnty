"""Verify real Chrome proxy auth against a synthetic HTTPS gateway, without accounts."""
import argparse
import base64
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import ssl
import sys
import tempfile
import threading
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xgenius import browser_proxy
from xgenius.browser_cdp import browser_connection
from xgenius.http_bridge import HttpBridge
from xgenius.proxy_service import HttpProxy, ProxyCheckError, check_proxy


class Gateway(BaseHTTPRequestHandler):
    def do_CONNECT(self):
        token = self.headers.get('Proxy-Authorization', '')
        valid = token == self.server.authorization
        self.server.requests.append(valid)
        if not valid:
            # A working preemptive proxy need not issue a usable auth challenge.
            self.send_response(407)
            self.send_header('Content-Length', '0')
            self.end_headers()
            return
        if self.path != 'probe.invalid:443':
            self.send_error(502)
            return
        self.send_response(200)
        self.end_headers()
        try:
            with self.server.tls.wrap_socket(self.connection, server_side=True) as stream:
                request = b''
                while b'\r\n\r\n' not in request:
                    part = stream.recv(4096)
                    if not part or len(request) + len(part) > 65536:
                        return
                    request += part
                if b'proxy-authorization:' in request.lower():
                    self.server.leaked_credentials = True
                body = b'{"ip":"203.0.113.90"}'
                stream.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n'
                    b'Content-Length: ' + str(len(body)).encode() + b'\r\nConnection: close\r\n\r\n' + body)
        except (OSError, ssl.SSLError):
            pass

    def log_message(self, *args):
        pass


def make_tls(root):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'probe.invalid')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName('probe.invalid')]), critical=False)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = root / 'certificate.pem', root / 'key.pem'
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    tls.load_cert_chain(cert_path, key_path)
    public_key = key.public_key().public_bytes(serialization.Encoding.DER,
                                             serialization.PublicFormat.SubjectPublicKeyInfo)
    import hashlib
    return tls, cert_path, base64.b64encode(hashlib.sha256(public_key).digest()).decode('ascii')


def launch(chrome, driver, profile, proxy, extension, fingerprint, headless):
    options = webdriver.ChromeOptions()
    options.binary_location = str(chrome)
    for argument in ('--no-first-run', '--no-default-browser-check', '--disable-background-networking',
            '--user-data-dir=' + str(profile), '--proxy-server=' + proxy.server,
            '--proxy-bypass-list=<-loopback>', '--load-extension=' + extension.name,
            '--ignore-certificate-errors-spki-list=' + fingerprint,
            '--headless=new' if headless else '--start-minimized'):
        options.add_argument(argument)
    browser = webdriver.Chrome(service=Service(str(driver),
        **({'creation_flags': 0x08000000} if os.name == 'nt' else {})), options=options)
    browser._xg_proxy_extension = extension
    return browser


def check(chrome, driver):
    with tempfile.TemporaryDirectory(prefix='xanty-proxy-smoke-') as directory:
        root = Path(directory)
        tls, certificate, fingerprint = make_tls(root)
        gateway = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
        gateway.daemon_threads = True
        gateway.tls, gateway.requests, gateway.leaked_credentials = tls, [], False
        gateway.authorization = 'Basic ' + base64.b64encode(b'user:synthetic:p@ss%word').decode('ascii')
        thread = threading.Thread(target=gateway.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
        thread.start()
        upstream = HttpProxy('127.0.0.1', gateway.server_port, 'user', 'synthetic:p@ss%word', auto_detect=False)
        endpoint = 'https://probe.invalid/'
        try:
            import requests
            original_get = requests.Session.get
            def trusted_get(session, url, **kwargs):
                return original_get(session, url, verify=str(certificate), **kwargs)
            with patch('xgenius.proxy_service.IP_CHECK_URLS', (endpoint,)), \
                    patch.object(requests.Session, 'get', trusted_get):
                if check_proxy(upstream) != '203.0.113.90':
                    raise RuntimeError('Preflight must pass on this working proxy.')
            with patch.object(browser_proxy, '_CHECK_URLS', (endpoint,)):
                extension = browser_proxy.prepare_proxy_extension(upstream)
                with extension:
                    browser = launch(chrome, driver, root / 'original', upstream, extension, fingerprint, True)
                    try:
                        try:
                            browser_proxy.verify_browser_proxy(browser, upstream)
                        except ProxyCheckError:
                            print('Reproduced: preflight succeeds but original Chrome proxy authentication fails.', flush=True)
                        else:
                            raise RuntimeError('The regression scenario did not reproduce.')
                    finally:
                        browser.quit()
                for headless in (True, False):
                    for restart in (False, True):
                        bridge = HttpBridge(upstream)
                        try:
                            extension = browser_proxy.prepare_proxy_extension(bridge.proxy)
                            with extension:
                                browser = launch(chrome, driver, root / str(headless), bridge.proxy,
                                                 extension, fingerprint, headless)
                                try:
                                    selected, handles = browser.current_window_handle, browser.window_handles
                                    with browser_connection(browser) as connection:
                                        worker = browser_proxy._find_worker(connection, extension.worker_url)
                                        session = connection.call('Target.attachToTarget', {'targetId': worker, 'flatten': True})['sessionId']
                                        browser_proxy._wait_for_worker(connection, session)
                                        fresh = connection.call('Runtime.evaluate', {
                                            'expression': f'proxyPort === {bridge.proxy.port} && credentials.username === {json.dumps(bridge.proxy.username)}',
                                            'returnByValue': True}, session_id=session)['result'].get('value')
                                        if fresh is not True:
                                            raise RuntimeError('Chrome reused the previous launch proxy worker with stale port/credentials.')
                                    if browser_proxy.verify_browser_proxy(browser, bridge.proxy) != '203.0.113.90':
                                        raise RuntimeError('Chrome did not verify its proxied exit IP.')
                                    if browser.current_window_handle != selected or browser.window_handles != handles:
                                        raise RuntimeError('Proxy verification changed the user tabs.')
                                    browser.get(endpoint)
                                    if '203.0.113.90' not in browser.page_source:
                                        raise RuntimeError('Regular browser traffic did not use the proxy.')
                                    print('Verified Chrome proxy: ' + json.dumps({
                                        'version': browser.capabilities['browserVersion'],
                                        'headless': headless, 'restart': restart,
                                        'upstream_preemptive_auth': True, 'user_tabs_preserved': True}), flush=True)
                                finally:
                                    browser.quit()
                        finally:
                            bridge.cleanup()
            if gateway.leaked_credentials:
                raise RuntimeError('Proxy credentials reached the synthetic origin.')
        finally:
            gateway.shutdown()
            gateway.server_close()
            thread.join(timeout=5)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chrome', required=True, type=Path)
    parser.add_argument('--driver', required=True, type=Path)
    args = parser.parse_args()
    check(args.chrome.resolve(), args.driver.resolve())
