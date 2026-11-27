"""User-configured proxy rotation endpoints, requested only on an explicit click."""
from urllib.parse import urlsplit


class ProxyRotationError(ValueError):
    pass


def rotation_url(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ProxyRotationError('Enter an HTTP or HTTPS proxy rotation link.')
    value = value.strip()
    if not value:
        return ''
    try:
        parsed = urlsplit(value)
        if (len(value) > 8192 or any(c.isspace() or not c.isprintable() for c in value)
                or '\\' in value or parsed.scheme not in ('http', 'https')
                or not parsed.hostname or parsed.fragment
                or (parsed.port is not None and not 1 <= parsed.port <= 65535)):
            raise ValueError()
    except ValueError:
        raise ProxyRotationError('Enter an HTTP or HTTPS proxy rotation link.') from None
    return value


def request_rotation(url):
    import requests
    url = rotation_url(url)
    if not url:
        raise ProxyRotationError('Add a proxy rotation link in the profile settings first.')
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.get(url, timeout=(6, 120), allow_redirects=False,
                                   headers={'Cache-Control': 'no-cache'})
            if response.status_code == 429:
                raise ProxyRotationError('Proxy rotation is rate limited. Wait and try again.')
            if not 200 <= response.status_code < 300:
                raise ProxyRotationError(f'Proxy rotation returned HTTP {response.status_code}. Check the link and provider limits.')
            try:
                data = response.json()
            except ValueError:
                data = None
            if isinstance(data, dict) and (
                    data.get('success') is False or data.get('ok') is False
                    or str(data.get('status', '')).lower() in ('error', 'fail', 'failed', 'failure')
                    or str(data.get('result', '')).lower() in ('error', 'fail', 'failed', 'failure')
                    or data.get('error')):
                raise ProxyRotationError('The proxy provider rejected the rotation request. Check the link and provider limits.')
        except requests.exceptions.Timeout:
            raise ProxyRotationError('Proxy rotation timed out. The provider may have received the request; check the IP before trying again.') from None
        except requests.exceptions.RequestException:
            raise ProxyRotationError('Cannot reach the proxy rotation endpoint. Check the link and connection.') from None

