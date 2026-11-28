"""Validate HTTP/SOCKS5 proxies and check the public IP without a direct fallback."""

import ipaddress
import re
from dataclasses import dataclass, replace
import socket
import time
import threading
from urllib.parse import quote, unquote, urlsplit


IP_CHECK_URL = "https://api64.ipify.org/?format=json"
IP_CHECK_URLS = (IP_CHECK_URL, "https://checkip.amazonaws.com/", "https://api.ipify.org/?format=json")
LOCATION_URL = "https://ipwho.is/"


class ProxyCheckError(Exception):
    """A safe error message: never includes a proxy password or full URL."""


@dataclass(frozen=True)
class HttpProxy:
    host: str
    port: int
    username: str = ""
    password: str = ""
    scheme: str = "http"
    auto_detect: bool = True

    @property
    def server(self):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"{self.scheme}://{host}:{self.port}"

    @property
    def requests_url(self):
        scheme = 'socks5h' if self.scheme == 'socks5' else self.scheme
        address = self.server.split('://', 1)[1]
        auth = f"{quote(self.username, safe='')}:{quote(self.password, safe='')}@" if self.username else ''
        return f'{scheme}://{auth}{address}'


def parse_proxy(value: str) -> HttpProxy:
    raw = (value or "").strip()
    if not raw:
        raise ProxyCheckError("Proxy is not configured. Add an HTTP proxy before opening the profile.")
    if any(c.isspace() for c in raw):
        raise ProxyCheckError("Invalid proxy format. Use host:port:user:password or http://user:password@host:port.")
    explicit_scheme = '://' in raw
    scheme, address = raw.split('://', 1) if explicit_scheme else ('http', raw)
    legacy = re.fullmatch(r'(\[[^\]]+\]|[^:/?#\[\]]+):(\d+):([^:]*):(.*)', address)
    if legacy:
        host, port, username, password = legacy.groups()
        address = f"{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"
    raw = f'{scheme}://{address}'
    try:
        parsed = urlsplit(raw)
        if parsed.scheme not in ("http", "socks5", "socks5h"):
            raise ValueError("unsupported scheme")
        if parsed.path or parsed.query or parsed.fragment:
            raise ValueError("unexpected URL path")
        host, port = parsed.hostname, parsed.port
        username = unquote(parsed.username or "")
        password = unquote(parsed.password or "")
        if not host or port is None or not 1 <= port <= 65535:
            raise ValueError("missing host or port")
        if bool(username) != bool(password):
            raise ValueError("incomplete credentials")
        if any(c in host for c in ("/", "@", "\\", ",", ";", "=", "<", ">", "|")):
            raise ValueError("invalid host")
    except (ValueError, TypeError) as exc:
        raise ProxyCheckError("Invalid proxy. Use host:port:user:password, http://user:password@host:port or socks5://user:password@host:port.") from None
    return HttpProxy(host, port, username, password,
                     'socks5' if parsed.scheme.startswith('socks5') else 'http', not explicit_scheme)


def parse_ip_response(body: str) -> str:
    import json
    try:
        try:data=json.loads(body)
        except ValueError:data=body.strip()
        ip=data['ip'] if isinstance(data,dict) else data
        return str(ipaddress.ip_address(ip))
    except (ValueError, KeyError, TypeError):
        raise ProxyCheckError("IP check did not return a valid public IP.") from None


_PROTOCOL_CACHE = {}
_PROTOCOL_LOCK = threading.Lock()


def _socks5_port(host: str, port: int) -> bool:
    """Identify SOCKS without sending credentials or touching a rotation URL."""
    key = (host.lower(), port)
    with _PROTOCOL_LOCK:
        cached = _PROTOCOL_CACHE.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    detected = False
    try:
        with socket.create_connection((host, port), timeout=2) as connection:
            connection.settimeout(1)
            connection.sendall(b'\x05\x02\x00\x02')
            answer = b''
            while len(answer) < 2:
                part = connection.recv(2 - len(answer))
                if not part:
                    break
                answer += part
            detected = answer in (b'\x05\x00', b'\x05\x02')
    except OSError:
        pass
    with _PROTOCOL_LOCK:
        if len(_PROTOCOL_CACHE) >= 512:
            _PROTOCOL_CACHE.clear()
        _PROTOCOL_CACHE[key] = (time.monotonic() + (300 if detected else 5), detected)
    return detected


def resolve_proxy(proxy: HttpProxy) -> HttpProxy:
    # Older saved profile strings have no protocol and were treated as HTTP.
    # A positive SOCKS greeting is required before changing their interpretation.
    return replace(proxy, scheme='socks5') if (proxy.scheme == 'http' and proxy.auto_detect
        and _socks5_port(proxy.host, proxy.port)) else proxy


def check_proxy(proxy: HttpProxy) -> str:
    """Verify the exit through the configured HTTP/SOCKS endpoint only."""
    import requests
    proxy = resolve_proxy(proxy)
    last_error = 'Cannot check the external IP through the proxy. Check its network access.'
    with requests.Session() as session:
        session.trust_env = False
        session.proxies = {'http': proxy.requests_url, 'https': proxy.requests_url}
        for endpoint in IP_CHECK_URLS:
            try:
                response = session.get(endpoint, timeout=(4, 8), allow_redirects=False,
                                       headers={'Cache-Control': 'no-cache'})
                if response.status_code == 407:
                    raise ProxyCheckError('Proxy authentication failed (407). Check login and password.')
                if response.status_code != 200:
                    last_error = f'IP check returned HTTP {response.status_code} through the proxy.'
                    continue
                try:
                    return parse_ip_response(response.text)
                except ProxyCheckError as exc:
                    last_error = str(exc)
            except requests.exceptions.Timeout:
                last_error = 'Proxy timed out. Check the address and network.'
            except requests.exceptions.ProxyError as exc:
                if '407' in str(exc):
                    raise ProxyCheckError('Proxy authentication failed (407). Check login and password.') from None
                last_error = 'Cannot connect through the proxy. Check host, port and access.'
            except requests.exceptions.SSLError:
                last_error = 'HTTPS check failed through the proxy (certificate error).'
            except requests.exceptions.RequestException as exc:
                # SOCKS authentication errors may be nested inside ConnectionError.
                cause = str(exc).lower()
                if proxy.scheme == 'socks5' and ('authentication failed' in cause or 'authentication methods' in cause):
                    raise ProxyCheckError('SOCKS5 proxy authentication failed. Check login and password.') from None
                last_error = 'Cannot check the external IP through the proxy. Check its network access.'
    raise ProxyCheckError(last_error) from None


def parse_location_response(data: dict, ip: str) -> dict:
    try:
        matches = isinstance(data, dict) and data.get('success') is True and ipaddress.ip_address(data.get('ip')) == ipaddress.ip_address(ip)
    except (ValueError, TypeError):
        matches = False
    if not matches:
        raise ProxyCheckError('Proxy location is unavailable. The proxy IP check succeeded.')
    code = data.get('country_code', '')
    if not isinstance(code, str) or len(code) != 2 or not code.isascii() or not code.isalpha():
        raise ProxyCheckError('Proxy location is unavailable. The proxy IP check succeeded.')
    result = {'country_code': code.upper()}
    for key in ('country', 'region', 'city'):
        value = data.get(key, '')
        result[key] = ''.join(c for c in value if c.isprintable())[:100] if isinstance(value, str) else ''
    return result


def lookup_proxy_location(proxy: HttpProxy, ip: str) -> dict:
    """Geolocate the verified exit IP through the same proxy, never directly."""
    import requests
    ip = str(ipaddress.ip_address(ip))
    proxy = resolve_proxy(proxy)
    with requests.Session() as session:
        session.trust_env = False
        session.proxies = {'http': proxy.requests_url, 'https': proxy.requests_url}
        try:
            response = session.get(LOCATION_URL + ip, timeout=(4, 6),
                                   params={'fields': 'success,ip,country_code,country,region,city'})
            if response.status_code != 200:
                raise ProxyCheckError('Proxy location is unavailable. The proxy IP check succeeded.')
            return parse_location_response(response.json(), ip)
        except (requests.exceptions.RequestException, ValueError):
            raise ProxyCheckError('Proxy location is unavailable. The proxy IP check succeeded.') from None
