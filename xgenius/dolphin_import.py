"""Read Dolphin Anty profiles through its remote API without changing the source."""

import re
import time
from urllib.parse import quote, urljoin, urlsplit

from xgenius.cookies import CookieError, normalize_cookies
from xgenius.profile_settings import ProfileSettingsError, browser_settings
from xgenius.proxy_service import ProxyCheckError, parse_proxy


API_BASE = 'https://dolphin-anty-api.com'
COOKIE_BASE = 'https://darkwing.dolphin-anty-api.com/api/v1'
_HANDLE = re.compile(r'^@?([A-Za-z0-9_]{1,15})$')


class DolphinError(ValueError):
    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def profile_id(value) -> int:
    if isinstance(value, bool) or not str(value).isdigit() or int(value) <= 0:
        raise DolphinError('Enter a valid numeric Dolphin profile ID')
    return int(value)


def suggested_username(profile: dict) -> str:
    matched = _HANDLE.fullmatch(str(profile.get('name') or '').strip())
    return matched.group(1) if matched else f"dolphin_{profile_id(profile.get('id'))}"


def safe_username(value: str) -> str:
    name = str(value or '').strip().lstrip('@')
    if not re.fullmatch(r'[A-Za-z0-9_]{1,32}', name):
        raise DolphinError('Use a username of 1–32 letters, digits or underscores')
    return name


def _manual(value):
    if isinstance(value, dict):
        return value.get('value') if value.get('mode') == 'manual' else ''
    return value if isinstance(value, str) else ''


def _proxy(profile: dict, warnings: list[str]) -> str:
    value = profile.get('proxy')
    if not value:
        warnings.append('No proxy; add an HTTP proxy before opening')
        return ''
    if not isinstance(value, dict) or str(value.get('type') or '').lower() != 'http':
        warnings.append('Unsupported proxy type; add an HTTP proxy in XAnty')
        return ''
    host, port = value.get('host'), value.get('port')
    login, password = value.get('login') or '', value.get('password') or ''
    if not host or not port:
        warnings.append('Dolphin did not provide the full proxy address; add it in XAnty')
        return ''
    try:
        host = str(host)
        authority = f'[{host}]' if ':' in host and not host.startswith('[') else host
        creds = f"{quote(str(login), safe='')}:{quote(str(password), safe='')}@" if login or password else ''
        raw = f'http://{creds}{authority}:{port}'
        parse_proxy(raw)
        return raw
    except (ProxyCheckError, ValueError):
        warnings.append('Dolphin proxy is incomplete or invalid; add an HTTP proxy in XAnty')
        return ''


def map_profile(profile: dict, username: str = '', folder: str = 'Dolphin') -> tuple[dict, list[str]]:
    if not isinstance(profile, dict):
        raise DolphinError('Dolphin returned an invalid profile')
    source_id = profile_id(profile.get('id'))
    username = safe_username(username or suggested_username(profile))
    warnings = []
    if username == f'dolphin_{source_id}' and not _HANDLE.fullmatch(str(profile.get('name') or '').strip()):
        warnings.append('An internal username was generated; the original Dolphin profile name is preserved')
    proxy = _proxy(profile, warnings)
    settings = {}
    for source, target in (('locale', 'browser_language'), ('timezone', 'browser_timezone')):
        value = _manual(profile.get(source))
        if value:
            settings[target] = value.replace('_', '-') if source == 'locale' else value
    screen = profile.get('screen') or {}
    resolution = screen.get('resolution') if isinstance(screen, dict) else None
    if isinstance(resolution, str) and 'x' in resolution:
        width, height = resolution.lower().split('x', 1)
        settings.update(window_width=width, window_height=height)
    valid_settings = browser_settings({})
    for key, value in settings.items():
        try:
            valid_settings[key] = browser_settings({**valid_settings, key: value})[key]
        except ProfileSettingsError:
            warnings.append(f'Dolphin {key} is unsupported; review it in XAnty')
    settings = valid_settings
    if str(profile.get('platform') or 'windows').lower() not in ('windows', 'win'):
        warnings.append('Source OS differs from the Windows Chrome used by XAnty')
    warnings.append('Dolphin fingerprint is not copied; XAnty uses its own Chrome')
    warnings.append('Local storage and extensions are not available through the Dolphin remote API')
    account = {'username': username, 'password': '', 'proxy': proxy, 'user_agent': '',
               'group': folder, 'auth_token': '', 'ct0_token': '', 'headless': False,
               'auto_login': False, 'dolphin_profile_id': source_id,
               'dolphin_name': str(profile.get('name') or ''), 'profile_name': str(profile.get('name') or username),
               'notes': str(profile.get('notes') or ''), 'tags': profile.get('tags') or [],
               'dolphin_source': profile, **settings}
    return account, warnings


class DolphinClient:
    def __init__(self, token: str, session=None, cancelled=None):
        if not isinstance(token, str):
            raise DolphinError('Enter a Dolphin API token')
        token = token.strip()
        if not token or any(c.isspace() for c in token):
            raise DolphinError('Enter a Dolphin API token')
        if session is None:
            import requests
            session = requests.Session()
            session.trust_env = False
        self.session = session
        self.cancelled = cancelled or (lambda: False)
        self.session.headers.update({'Authorization': f'Bearer {token}', 'Accept': 'application/json'})

    def close(self):
        self.session.close()

    def _request(self, method: str, url: str, **kwargs) -> dict:
        response = None
        for attempt in range(4):
            if self.cancelled():
                raise DolphinError('Operation cancelled')
            try:
                response = self.session.request(method, url, timeout=(8, 20), allow_redirects=False, **kwargs)
            except Exception as exc:
                if attempt == 3:
                    raise DolphinError('Cannot connect to the Dolphin API') from exc
                self._wait(2 ** attempt)
                continue
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 3:
                break
            try:
                delay = float(getattr(response, 'headers', {}).get('Retry-After', 2 ** (attempt + 1)))
            except (TypeError, ValueError):
                delay = 2 ** (attempt + 1)
            self._wait(min(max(delay, 1), 90))
        status = response.status_code
        if status != 200:
            reason = {401: 'Invalid or expired Dolphin API token',
                      402: 'Dolphin requires a paid plan for this operation',
                      403: 'No access to this Dolphin profile',
                      404: 'Dolphin profile or cursor pagination is unavailable',
                      429: 'Dolphin API rate limit reached'}.get(status, f'Dolphin API returned HTTP {status}')
            raise DolphinError(reason, status=status)
        try:
            data = response.json()
        except ValueError as exc:
            raise DolphinError('Dolphin returned invalid JSON') from exc
        if not isinstance(data, dict) or data.get('success') is False:
            raise DolphinError('Dolphin rejected the request')
        return data

    def _wait(self, seconds):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self.cancelled():
                raise DolphinError('Operation cancelled')
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))

    def get_profile(self, value, password: str = '') -> dict:
        number = profile_id(value)
        params = {'browserProfilePassword': password} if password else None
        data = self._request('GET', f'{API_BASE}/browser_profiles/{number}', params=params).get('data')
        if not isinstance(data, dict):
            raise DolphinError('Dolphin did not return profile settings')
        data.setdefault('id', number)
        return data

    def export_cookies(self, value, password: str = '', all_sites: bool = False) -> tuple[list[dict], str]:
        payload = {'browserProfileId': profile_id(value)}
        if password:
            payload['browserProfilePassword'] = password
        try:
            data = self._request('POST', f'{COOKIE_BASE}/cookies/export', json=payload)
            raw = data.get('cookies') or []
            if not raw:
                return [], 'Dolphin returned no cookies; sign-in must be checked manually'
            try:
                if all_sites:
                    from xgenius.portable_session import normalize_session
                    return normalize_session(raw), ''
                return normalize_cookies(raw), ''
            except (CookieError, ValueError):
                return [], 'No X/Twitter cookies in the Dolphin profile'
        except DolphinError as exc:
            return [], f'Cookies unavailable: {exc}'

    def inspect(self, value, password: str = '', username: str = '', folder: str = 'Dolphin') -> tuple[dict, list[dict], list[str]]:
        profile = self.get_profile(value, password)
        account, warnings = map_profile(profile, username, folder)
        cookie_data, cookie_warning = self.export_cookies(value, password)
        if cookie_warning:
            warnings.append(cookie_warning)
        return account, cookie_data, warnings

    def profile_pages(self):
        path = f'{API_BASE}/browser_profiles/list-cursor?limit=50'
        seen = set()
        while path:
            if path in seen:
                raise DolphinError('Dolphin pagination repeated the same page')
            seen.add(path)
            page = self._request('GET', path)
            rows = page.get('data')
            if not isinstance(rows, list):
                raise DolphinError('Dolphin returned an invalid profile list')
            for row in rows:
                if not isinstance(row, dict):
                    raise DolphinError('Dolphin returned an invalid profile list')
                profile_id(row.get('id'))
            next_url = page.get('next_page_url')
            if next_url:
                next_url = urljoin(path, next_url)
                parsed = urlsplit(next_url)
                if (parsed.scheme != 'https' or parsed.netloc != urlsplit(API_BASE).netloc or
                        parsed.path != '/browser_profiles/list-cursor' or parsed.username or parsed.password):
                    raise DolphinError('Dolphin returned an unexpected next page URL')
            yield rows, page.get('total'), next_url
            path = next_url

    def profile_ids(self, max_profiles=None) -> list[int]:
        ids = []
        for rows, total, next_url in self.profile_pages():
            ids.extend(profile_id(row['id']) for row in rows)
            if max_profiles is not None and len(ids) >= max_profiles:
                break
        result = list(dict.fromkeys(ids))
        return result if max_profiles is None else result[:max_profiles]

    def folders(self):
        data = self._request('GET', f'{API_BASE}/folders').get('data', [])
        if not isinstance(data, list):
            return {}
        return {str(row['id']): str(row.get('name') or '') for row in data if isinstance(row, dict) and row.get('id')}
