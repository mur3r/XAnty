"""Portable cookie snapshots for profile transfer between Windows accounts."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from xgenius.cookies import get_cookies_file_path


def normalize_session(data) -> list[dict]:
    if isinstance(data, dict):
        data = data.get('cookies', [])
    if not isinstance(data, list):
        raise ValueError('Invalid portable cookies')
    result = []
    for item in data:
        if not isinstance(item, dict):
            raise ValueError('Invalid portable cookie')
        name, value, domain = (item.get(k) for k in ('name', 'value', 'domain'))
        if not all(isinstance(v, str) for v in (name, value, domain)) or not name or not domain:
            raise ValueError('Invalid portable cookie')
        if any(ord(c) < 32 for c in name + value + domain) or any(c in domain for c in '/\\:@'):
            raise ValueError('Invalid portable cookie')
        path = item.get('path') or '/'
        if not isinstance(path, str) or not path.startswith('/'):
            raise ValueError('Invalid portable cookie path')
        cookie = {'name': name, 'value': value, 'domain': domain.lower(), 'path': path}
        for key in ('secure', 'httpOnly'):
            cookie[key] = bool(item.get(key, False))
        expiry = item.get('expires', item.get('expiry', item.get('expirationDate')))
        if expiry is not None:
            try:
                expiry = float(expiry)
                if 0 < expiry < 253402300800:
                    cookie['expires'] = expiry
            except (TypeError, ValueError, OverflowError):
                raise ValueError('Invalid portable cookie expiry') from None
        same = str(item.get('sameSite') or '').lower()
        if same in ('strict', 'lax', 'none'):
            cookie['sameSite'] = same.capitalize()
        result.append(cookie)
    return result


def session_path(config, username: str) -> Path:
    return get_cookies_file_path(config, username).parent / 'portable_cookies.json'


def store_session(config, username: str, cookies, pending: bool = True) -> int:
    data = {'version': 1, 'pending': pending, 'cookies': normalize_session(cookies)}
    path = session_path(config, username)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)
    return len(data['cookies'])


def capture_session(browser, config, username: str) -> None:
    """CDP captures all origins, including HttpOnly cookies, before Chrome closes."""
    try:
        payload = browser.execute_cdp_cmd('Storage.getCookies', {})
        store_session(config, username, payload.get('cookies', []), pending=False)
    except Exception:
        # Older Chrome builds may expose the same operation under Network.
        try:
            payload = browser.execute_cdp_cmd('Network.getAllCookies', {})
            store_session(config, username, payload.get('cookies', []), pending=False)
        except Exception:
            pass


def apply_session(browser, config, username: str) -> None:
    path = session_path(config, username)
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding='utf-8'))
    if not data.get('pending'):
        return
    cookies = normalize_session(data)
    if cookies:
        browser.execute_cdp_cmd('Storage.setCookies', {'cookies': cookies})
    store_session(config, username, cookies, pending=False)


def _unprotect(data: bytes) -> bytes:
    if os.name != 'nt':
        raise ValueError('Windows is required to decrypt this session')

    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ValueError('This browser session is protected by another Windows account')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel32.LocalFree(target.data)


def read_chrome_session(profile: Path) -> tuple[list[dict], int]:
    """Read a closed local Chrome profile; never change its cookie database."""
    databases = sorted(profile.glob('*/Network/Cookies')) + sorted(profile.glob('*/Cookies'))
    if not databases:
        return [], 0
    key = None
    try:
        local_state = json.loads((profile / 'Local State').read_text(encoding='utf-8'))
        encrypted_key = base64.b64decode(local_state['os_crypt']['encrypted_key'])
        if encrypted_key.startswith(b'DPAPI'):
            key = _unprotect(encrypted_key[5:])
    except (OSError, ValueError, KeyError):
        pass
    result, failed = [], 0
    seen = set()
    for database in databases:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as connection:
            try:
                version = int(connection.execute("SELECT value FROM meta WHERE key='version'").fetchone()[0])
            except (sqlite3.Error, TypeError, ValueError):
                version = 0
            rows = connection.execute('SELECT host_key,name,value,encrypted_value,path,expires_utc,is_secure,is_httponly,samesite FROM cookies')
            for domain, name, value, encrypted, path, expires, secure, http_only, same in rows:
                identity = (domain, path, name)
                if identity in seen:
                    continue
                try:
                    if encrypted:
                        encrypted = bytes(encrypted)
                        if encrypted.startswith((b'v10', b'v11')):
                            if key is None:
                                raise ValueError('No local encryption key')
                            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
                            plain = AESGCM(key).decrypt(encrypted[3:15], encrypted[15:], None)
                            if version >= 24:
                                if plain[:32] != hashlib.sha256(domain.encode()).digest():
                                    raise ValueError('Cookie domain verification failed')
                                plain = plain[32:]
                        elif encrypted.startswith(b'v20'):
                            raise ValueError('Chrome application-bound encryption')
                        else:
                            plain = _unprotect(encrypted)
                        value = plain.decode('utf-8')
                    cookie = {'domain': domain, 'name': name, 'value': value, 'path': path or '/',
                              'secure': bool(secure), 'httpOnly': bool(http_only)}
                    if expires:
                        cookie['expires'] = expires / 1000000 - 11644473600
                    if same in (0, 1, 2):
                        cookie['sameSite'] = {0: 'None', 1: 'Lax', 2: 'Strict'}[same]
                    result.extend(normalize_session([cookie]))
                    seen.add(identity)
                except Exception:
                    # Never include cookie values or encryption keys in reports.
                    failed += 1
    return result, failed


def export_session(config, username: str) -> tuple[list[dict], list[str]]:
    profile = config.browser_profiles_dir / f'profile_{username}'
    cookies, warnings = [], []
    try:
        cookies, failed = read_chrome_session(profile)
        if failed:
            warnings.append(f'{failed} browser cookies could not be decrypted; open and close this profile in XAnty before exporting again')
    except (sqlite3.Error, OSError, ValueError):
        warnings.append('Could not read the local browser cookie database')
    # A pending transferred snapshot is authoritative until the first browser launch.
    path = session_path(config, username)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            snapshot = normalize_session(data)
            if data.get('pending'):
                cookies = snapshot
            else:
                merged = {(c['domain'], c['path'], c['name']): c for c in snapshot}
                merged.update({(c['domain'], c['path'], c['name']): c for c in cookies})
                cookies = list(merged.values())
        except (OSError, ValueError):
            warnings.append('Could not read the saved portable session')
    # Preserve legacy X sessions as well as all-origin browser cookies.
    try:
        from xgenius.cookies import read_cookies, CookieError
        legacy = normalize_session(read_cookies(config, username))
    except (CookieError, OSError, ValueError):
        legacy = []
    merged = {(c['domain'], c['path'], c['name']): c for c in cookies}
    for cookie in legacy:
        merged.setdefault((cookie['domain'], cookie['path'], cookie['name']), cookie)
    return list(merged.values()), warnings
