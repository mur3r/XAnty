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
        # A transient lack of page targets must not erase a useful previous snapshot.
        return write_tabs(config, username, [t['url'] for t in pages]) if any(t.get('type') == 'page' for t in targets) else 0


def prepare_workspace(browser):
    """Preserve native restored pages while launch checks use a disposable tab."""
    targets = browser.execute_cdp_cmd('Target.getTargets', {}).get('targetInfos', [])
    browser._xg_native_tabs = [t['url'] for t in targets if t.get('type') == 'page' and valid_tab(t.get('url'))]
    browser._xg_empty_startup_targets = {t.get('targetId') for t in targets if t.get('type') == 'page' and
                                       t.get('url') in ('data:,','about:blank','chrome://newtab/')}
    browser._xg_ignored_targets = set()
    if browser._xg_native_tabs:
        browser.switch_to.new_window('tab')
    handle = getattr(browser,'current_window_handle',None)
    if handle:
        browser._xg_bootstrap_handle = handle
        browser._xg_ignored_targets.add(handle.removeprefix('CDwindow-'))


def restore_tabs(browser, config, username, enabled=True):
    if not enabled:
        browser._xg_ignored_targets = set()
        browser._xg_bootstrap_handle = None
        return 0
    with browser_lock(browser):
        native = getattr(browser, '_xg_native_tabs', [])
        urls = native or read_tabs(config, username)['tabs']
        if not urls:
            browser._xg_ignored_targets = set()
            browser._xg_bootstrap_handle = None
            return 0
        if not native:
            for url in urls:
                browser.execute_cdp_cmd('Target.createTarget', {'url': url})
        bootstrap = getattr(browser, '_xg_bootstrap_handle', None)
        handles = getattr(browser, 'window_handles', [])
        empty = getattr(browser,'_xg_empty_startup_targets',set())
        for handle in handles:
            if (handle == bootstrap or handle.removeprefix('CDwindow-') in empty) and len(browser.window_handles) > 1:
                browser.switch_to.window(handle)
                browser.close()
        if bootstrap and getattr(browser,'window_handles',[]):
            browser.switch_to.window(browser.window_handles[0])
        browser._xg_ignored_targets = set()
        browser._xg_bootstrap_handle = None
        return len(urls)


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
