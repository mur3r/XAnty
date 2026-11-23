"""Validate HTTP proxies and check the public IP without a direct fallback."""

import ipaddress
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit


IP_CHECK_URL = "https://api.ipify.org/?format=json"
LOCATION_URL = "https://ipwho.is/"


class ProxyCheckError(Exception):
    """A safe error message: never includes a proxy password or full URL."""


@dataclass(frozen=True)
class HttpProxy:
    host: str
    port: int
    username: str = ""
    password: str = ""

    @property
    def server(self):
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}"

    @property
    def requests_url(self):
        if not self.username:
            return self.server
        return f"http://{quote(self.username, safe='')}:{quote(self.password, safe='')}@{self.server[7:]}"


def parse_proxy(value: str) -> HttpProxy:
    raw = (value or "").strip()
    if not raw:
        raise ProxyCheckError("Proxy is not configured. Add an HTTP proxy before opening the profile.")
    if any(c.isspace() for c in raw):
        raise ProxyCheckError("Invalid proxy format. Use host:port:user:password or http://user:password@host:port.")
    if "://" not in raw and raw.count(":") >= 3 and not raw.startswith("["):
        host, port, username, password = raw.split(":", 3)
        raw = f"http://{quote(username, safe='')}:{quote(password, safe='')}@{host}:{port}"
    elif "://" not in raw:
        raw = f"http://{raw}"
    try:
        parsed = urlsplit(raw)
        if parsed.scheme != "http":
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
        raise ProxyCheckError("Invalid HTTP proxy. Use host:port:user:password or http://user:password@host:port.") from None
    return HttpProxy(host, port, username, password)


def parse_ip_response(body: str) -> str:
    import json
    try:
        try:data=json.loads(body)
        except ValueError:data=body.strip()
        ip=data['ip'] if isinstance(data,dict) else data
        return str(ipaddress.ip_address(ip))
    except (ValueError, KeyError, TypeError):
        raise ProxyCheckError("IP check did not return a valid public IP.") from None


def check_proxy(proxy: HttpProxy) -> str:
    """Check an HTTPS CONNECT request; both protocols are pinned to the proxy."""
    import requests

    with requests.Session() as session:
        session.trust_env = False
        session.proxies = {"http": proxy.requests_url, "https": proxy.requests_url}
        try:
            response = session.get(IP_CHECK_URL, timeout=(6, 15), headers={"Cache-Control": "no-cache"})
            if response.status_code == 407:
                raise ProxyCheckError("Proxy authentication failed (407). Check login and password.")
            if response.status_code != 200:
                raise ProxyCheckError(f"IP check returned HTTP {response.status_code} through the proxy.")
            return parse_ip_response(response.text)
        except requests.exceptions.Timeout:
            raise ProxyCheckError("Proxy timed out. Check the address and network.") from None
        except requests.exceptions.ProxyError as exc:
            if "407" in str(exc):
                raise ProxyCheckError("Proxy authentication failed (407). Check login and password.") from None
            raise ProxyCheckError("Cannot connect through the proxy. Check host, port and access.") from None
        except requests.exceptions.SSLError:
            raise ProxyCheckError("HTTPS check failed through the proxy (certificate error).") from None
        except requests.exceptions.RequestException:
            raise ProxyCheckError("Cannot check the external IP through the proxy. Check its network access.") from None


def parse_location_response(data: dict, ip: str) -> dict:
    if not isinstance(data, dict) or data.get('success') is not True or data.get('ip') != ip:
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
