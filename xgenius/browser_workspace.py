"""Browser tabs/cookies snapshots and narrowly scoped local-file operations."""
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from urllib.parse import urlsplit

from xgenius.cookies import get_cookies_file_path
from xgenius.portable_session import normalize_session, store_session
from xgenius.profile_leases import ProfileLease, profile_directory


_EMPTY_STARTUP_PAGES = {'data:,', 'about:blank', 'chrome://newtab/'}


def browser_lock(browser):
    lock = getattr(browser, '_xg_workspace_lock', None)
    if lock is None:
        lock = browser._xg_workspace_lock = threading.RLock()
    return lock


def _atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = stream.name
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def tabs_path(config, username):
    return get_cookies_file_path(config, username).parent / 'tabs.json'


def valid_tab(url):
    if not isinstance(url, str) or len(url) > 16384:
        return False
    try:
        parsed = urlsplit(url)
        return parsed.scheme in ('http', 'https') and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False


def write_tabs(config, username, urls, active=0):
    urls = [u for u in urls if valid_tab(u)][:200]
    _atomic_json(tabs_path(config, username), {'version': 1, 'tabs': urls, 'active': active,
                                             'saved_at': datetime.now(timezone.utc).isoformat()})
    return len(urls)


def read_tabs(config, username):
    path = tabs_path(config, username)
    if not path.exists():
        return {'tabs': [], 'active': 0}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('tabs'), list):
        raise ValueError('Invalid saved tabs')
    return {**data, 'tabs': [u for u in data['tabs'] if valid_tab(u)][:200]}


def capture_tabs(browser, config, username):
    with browser_lock(browser):
        targets = browser.execute_cdp_cmd('Target.getTargets', {}).get('targetInfos', [])
        ignored = getattr(browser, '_xg_ignored_targets', set())
        pages = [t for t in targets if t.get('type') == 'page' and t.get('targetId') not in ignored and valid_tab(t.get('url'))]
        handles = getattr(browser, 'window_handles', [])
        order = {h.removeprefix('CDwindow-'): i for i, h in enumerate(handles)}
        pages.sort(key=lambda t: order.get(t.get('targetId'), len(order)))
        handle = getattr(browser, 'current_window_handle', '')
        active_target = handle.removeprefix('CDwindow-')
        active = next((i for i, page in enumerate(pages) if page.get('targetId') == active_target), 0)
        # A transient lack of page targets must not erase a useful previous snapshot.
        return write_tabs(config, username, [t['url'] for t in pages], active) if any(
            t.get('type') == 'page' for t in targets) else 0


def prepare_workspace(browser):
    """Record which startup pages can be replaced by a portable tab snapshot."""
    targets = browser.execute_cdp_cmd('Target.getTargets', {}).get('targetInfos', [])
    browser._xg_empty_startup_targets = {
        target['targetId'] for target in targets
        if target.get('type') == 'page' and target.get('url') in _EMPTY_STARTUP_PAGES
    }


def restore_tabs(browser, config, username, enabled=True):
    if not enabled:
        return 0
    with browser_lock(browser):
        restored = getattr(browser, '_xg_restored_tab_count', None)
        if restored is not None:
            return restored
        ignored = getattr(browser, '_xg_ignored_targets', set())
        targets = browser.execute_cdp_cmd('Target.getTargets', {}).get('targetInfos', [])
        pages = [target for target in targets if target.get('type') == 'page' and target['targetId'] not in ignored]
        native_count = sum(valid_tab(page.get('url')) for page in pages)
        if native_count:
            browser._xg_restored_tab_count = native_count
            return native_count
        snapshot = read_tabs(config, username)
        urls = snapshot['tabs']
        if not urls:
            browser._xg_restored_tab_count = 0
            return 0
        active = snapshot.get('active')
        if type(active) is not int or not 0 <= active < len(urls):
            active = 0

        created = []
        try:
            for url in urls:
                target = browser.execute_cdp_cmd('Target.createTarget', {'url': url, 'background': True})
                created.append(target['targetId'])
            handles = {handle.removeprefix('CDwindow-'): handle for handle in browser.window_handles}
            browser.switch_to.window(handles[created[active]])
        except Exception:
            for target in created:
                try:
                    browser.execute_cdp_cmd('Target.closeTarget', {'targetId': target})
                except Exception:
                    pass
            raise

        browser._xg_restored_tab_count = len(urls)
        startup = getattr(browser, '_xg_empty_startup_targets', set())
        for page in pages:
            if page['targetId'] in startup and page.get('url') in _EMPTY_STARTUP_PAGES:
                browser.execute_cdp_cmd('Target.closeTarget', {'targetId': page['targetId']})
        return len(urls)


def select_x_login_tab(browser):
    with browser_lock(browser):
        current = browser.current_window_handle
        handles = {handle.removeprefix('CDwindow-'): handle for handle in browser.window_handles}
        targets = browser.execute_cdp_cmd('Target.getTargets', {}).get('targetInfos', [])
        pages = {handles[target['targetId']]: target.get('url', '') for target in targets
                 if target.get('type') == 'page' and target['targetId'] in handles}
        x_tabs = []
        for handle, url in pages.items():
            if valid_tab(url):
                host = urlsplit(url).hostname
                if host in ('x.com', 'twitter.com') or host.endswith(('.x.com', '.twitter.com')):
                    x_tabs.append(handle)
        if current in x_tabs:
            return
        if x_tabs:
            browser.switch_to.window(x_tabs[0])
        elif pages.get(current) not in _EMPTY_STARTUP_PAGES:
            browser.switch_to.new_window('tab')


def parse_cookie_input(data):
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            rows = []
            if not data.lstrip().startswith(('# Netscape HTTP Cookie File', '# HTTP Cookie File')):
                raise ValueError('Expected JSON or a Netscape cookie file') from None
            for line in data.splitlines():
                if not line or (line.startswith('#') and not line.startswith('#HttpOnly_')):
                    continue
                parts = line.removeprefix('#HttpOnly_').split('\t')
                if len(parts) != 7:
                    raise ValueError('Invalid Netscape cookie line')
                domain, _, path, secure, expires, name, value = parts
                rows.append(dict(domain=domain, path=path, secure=secure.upper() == 'TRUE',
                                 httpOnly=line.startswith('#HttpOnly_'), expires=expires, name=name, value=value))
            data = rows
    if isinstance(data, dict) and 'cookies' not in data and all(isinstance(v, list) for v in data.values()):
        data = [c for values in data.values() for c in values]
    return normalize_session(data)


def live_cookies(browser):
    try:
        data = browser.execute_cdp_cmd('Storage.getCookies', {})
    except Exception:
        data = browser.execute_cdp_cmd('Network.getAllCookies', {})
    return normalize_session(data.get('cookies', []))


def save_workspace(browser, config, username, full=True):
    with browser_lock(browser):
        cookies = live_cookies(browser) if full else None
        count = capture_tabs(browser, config, username)
        if cookies is not None:
            store_session(config, username, cookies, pending=False)
        return {'tabs': count, 'cookies': len(cookies) if cookies is not None else None,
                'saved_at': datetime.now(timezone.utc).isoformat()}


def clear_cache(config, username):
    with ProfileLease.acquire(config, username):
        root = profile_directory(config, username)
        names = {'Cache', 'Code Cache', 'GPUCache', 'ShaderCache', 'GrShaderCache', 'DawnCache'}
        roots = [root, *[p for p in root.iterdir() if p.is_dir() and (p.name == 'Default' or p.name.startswith('Profile '))]]
        targets = [p / name for p in roots for name in names if (p / name).exists()]
        for path in targets:
            # Validate the complete candidate set before deleting any directory.
            if path.is_symlink() or not path.resolve().is_relative_to(root) or any(
                    p.is_symlink() or bool(getattr(p.lstat(), 'st_file_attributes', 0) & 0x400)
                    for p in [path, *path.rglob('*')]):
                raise ValueError('Unsafe link in cache directory')
        files = total = 0
        for path in targets:
            for item in path.rglob('*'):
                if item.is_file():
                    files += 1; total += item.stat().st_size
            if path.is_dir():
                shutil.rmtree(path)
        return {'files': files, 'bytes': total}
