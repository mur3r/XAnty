"""Per-profile X cookie import, storage and restoration."""

import json
import os
import tempfile
from pathlib import Path


class CookieError(ValueError):
    pass


def get_cookies_file_path(config, username: str) -> Path:
    if not username or username in ('.', '..') or any(c in username for c in '/\\:\0'):
        raise CookieError('Invalid profile name')
    root = (config.base_dir / 'kook').resolve()
    folder = (root / f'@{username}').resolve()
    if not folder.is_relative_to(root):
        raise CookieError('Invalid profile name')
    return folder / 'cookies.json'


def _allowed_domain(domain: str) -> bool:
    host = domain.lower().lstrip('.')
    return host in ('x.com', 'twitter.com') or host.endswith(('.x.com', '.twitter.com'))


def normalize_cookies(data) -> list[dict]:
    """Accept Selenium/extension JSON, legacy domain maps, and Netscape text."""
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError as exc:
            if not data.lstrip().startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
                raise CookieError('Expected JSON or a Netscape cookie file') from exc
            rows = []
            for line in data.splitlines():
                if not line or (line.startswith('#') and not line.startswith('#HttpOnly_')):
                    continue
                parts = line.removeprefix('#HttpOnly_').split('\t')
                if len(parts) != 7:
                    raise CookieError('Invalid Netscape cookie line')
                domain, _, path, secure, expiry, name, value = parts
                rows.append({'domain': domain, 'path': path, 'secure': secure.upper() == 'TRUE',
                             'httpOnly': line.startswith('#HttpOnly_'), 'expiry': expiry,
                             'name': name, 'value': value})
            data = rows
    if isinstance(data, dict):
        if isinstance(data.get('cookies'), list):
            data = data['cookies']
        elif all(isinstance(v, list) for v in data.values()):
            data = [c for batch in data.values() for c in batch]
        else:
            raise CookieError('Expected a cookie list or domain mapping')
    if not isinstance(data, list):
        raise CookieError('Expected a cookie list')
    result = []
    for cookie in data:
        if not isinstance(cookie, dict):
            raise CookieError('Invalid cookie entry')
        domain = cookie.get('domain', '')
        if not isinstance(domain, str) or not _allowed_domain(domain):
            continue
        name, value = cookie.get('name'), cookie.get('value')
        if not isinstance(name, str) or not name or not isinstance(value, str):
            raise CookieError('Cookie name and value must be text')
        if any(ord(c) < 32 for c in name + value):
            raise CookieError('Cookie contains control characters')
        path = cookie.get('path', '/')
        if not isinstance(path, str) or not path.startswith('/'):
            raise CookieError('Invalid cookie path')
        clean = {'name': name, 'value': value, 'domain': domain.lower(), 'path': path}
        for key in ('secure', 'httpOnly'):
            if key in cookie:
                if not isinstance(cookie[key], bool):
                    raise CookieError(f'Invalid {key} flag')
                clean[key] = cookie[key]
        expiry = cookie.get('expiry', cookie.get('expirationDate'))
        if expiry not in (None, '', 0, '0'):
            try:
                clean['expiry'] = int(float(expiry))
            except (ValueError, TypeError, OverflowError) as exc:
                raise CookieError('Invalid cookie expiry') from exc
        same_site = cookie.get('sameSite')
        if isinstance(same_site, str) and same_site.lower() in ('strict', 'lax', 'none'):
            clean['sameSite'] = same_site.capitalize()
        result.append(clean)
    if not result:
        raise CookieError('No X/Twitter cookies found')
    return result


def read_cookies(config, username: str) -> list[dict]:
    path = get_cookies_file_path(config, username)
    if not path.is_file():
        raise CookieError('No saved cookies for this profile')
    try:
        return normalize_cookies(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError) as exc:
        raise CookieError('Could not read saved cookies') from exc


def store_cookies(config, username: str, data) -> int:
    cookies = normalize_cookies(data)
    grouped = {}
    for cookie in cookies:
        grouped.setdefault(cookie['domain'], []).append(cookie)
    path = get_cookies_file_path(config, username)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                         prefix='.cookies-', suffix='.tmp', delete=False) as fh:
            temp_path = Path(fh.name)
            json.dump(grouped, fh, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return len(cookies)


def save_cookies(browser, config, username: str, db_manager=None, pc_id=None) -> None:
    from xgenius.portable_session import capture_session
    capture_session(browser, config, username)
    # Selenium sees only the current site. Keep previous cookies when on another page.
    try:
        cookies = normalize_cookies(browser.get_cookies())
    except CookieError:
        return
    store_cookies(config, username, cookies)
    if db_manager and pc_id:
        grouped = {}
        for cookie in cookies:
            grouped.setdefault(cookie['domain'], []).append(cookie)
        db_manager.update_cookies(pc_id, username, grouped)


def load_cookies(browser, config, username: str, db_manager=None, pc_id=None) -> None:
    try:
        cookies = read_cookies(config, username)
    except CookieError:
        if not db_manager or not pc_id:
            return
        data = db_manager.get_cookies(pc_id, username)
        if not data:
            return
        cookies = normalize_cookies(data)
    browser.get('https://x.com')
    for cookie in cookies:
        if cookie['domain'].lstrip('.') != 'x.com':
            continue
        try:
            browser.add_cookie(cookie)
        except Exception as exc:
            print(f"Could not apply cookie {cookie['name']}: {type(exc).__name__}")
