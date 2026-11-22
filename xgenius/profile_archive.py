"""Stream complete profile packages without overwriting existing user profiles."""
from __future__ import annotations

import copy
import errno
import json
import os
import re
import shutil
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from xgenius.cookies import CookieError, get_cookies_file_path, normalize_cookies, store_cookies
from xgenius.folders import folder_name
from xgenius.portable_session import export_session, normalize_session, store_session
from xgenius.profile_settings import browser_settings

FORMAT = 'xanty-profile-package'
VERSION = 1
MAX_UNPACKED = 64 * 1024 ** 3
_NAME = re.compile(r'^[A-Za-z0-9_]{1,32}$')
_CACHE = {'cache', 'code cache', 'gpucache', 'shadercache', 'grshadercache', 'dawncache',
          'crashpad', 'crash reports', 'browsermetrics', 'component_crx_cache', 'extensions_crx_cache'}


class ArchiveError(ValueError):
    pass


def unique_name(name: str, reserved: set[str]) -> str:
    if not _NAME.fullmatch(name):
        raise ArchiveError('Invalid profile username in package')
    candidate, number = name, 2
    while candidate.casefold() in reserved:
        suffix = f'_{number}'
        candidate = name[:32 - len(suffix)] + suffix
        number += 1
    reserved.add(candidate.casefold())
    return candidate


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def _profile_files(root: Path):
    if not root.is_dir() or _linked(root):
        return
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(n for n in folders if n.lower() not in _CACHE and not _linked(Path(directory) / n))
        for name in sorted(files):
            path = Path(directory) / name
            if name.lower().startswith('singleton') or name.lower() in {'lockfile', 'lock', 'debug.log'} or _linked(path):
                continue
            yield path


def export_package(config, accounts: list[dict], destination: Path, progress=None, cancelled=None,
                   folders=None) -> dict:
    if not accounts:
        raise ArchiveError('No profiles to export')
    manifest = {'format': FORMAT, 'version': VERSION,
                'created_at': datetime.now(timezone.utc).isoformat(), 'profiles': [], 'folders': folders or []}
    report = []
    try:
        with ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
            for index, account in enumerate(accounts):
                if cancelled and cancelled():
                    raise ArchiveError('Operation cancelled')
                username = str(account.get('username') or '')
                if not _NAME.fullmatch(username):
                    raise ArchiveError('Invalid profile username')
                prefix = f'profiles/{index:06d}'
                cookies, warnings = export_session(config, username)
                archive.writestr(prefix + '/cookies.json', json.dumps(cookies, ensure_ascii=False))
                browser_root = config.browser_profiles_dir / f'profile_{username}'
                file_count = 0
                for path in _profile_files(browser_root):
                    if cancelled and cancelled():
                        raise ArchiveError('Operation cancelled')
                    archive.write(path, prefix + '/browser/' + path.relative_to(browser_root).as_posix())
                    file_count += 1
                manifest['profiles'].append({'key': f'{index:06d}', 'account': copy.deepcopy(account)})
                report.append({'username': username, 'status': 'exported', 'cookies': len(cookies),
                               'files': file_count, 'warnings': warnings})
                if progress:
                    progress(processed=index + 1, total=len(accounts), report=report)
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {'total': len(accounts), 'report': report, 'filename': destination.name,
            'size': destination.stat().st_size}


def _read_manifest(archive: ZipFile) -> dict:
    seen, total = set(), 0
    for info in archive.infolist():
        raw = info.orig_filename
        path = PurePosixPath(raw)
        parts = raw.rstrip('/').split('/')
        if (not raw or '\\' in raw or path.is_absolute() or any(p in ('', '.', '..') for p in parts)
                or any(':' in p or p.endswith((' ', '.')) or any(ord(c) < 32 for c in p) for p in parts)
                or any(p.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)],
                                                  *[f'LPT{i}' for i in range(1, 10)]} for p in parts)):
            raise ArchiveError('Unsafe path in profile package')
        key = raw.casefold().rstrip('/')
        if key in seen:
            raise ArchiveError('Duplicate file in profile package')
        seen.add(key)
        if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
            raise ArchiveError('Links and encrypted ZIP entries are not supported')
        total += info.file_size
        if total > MAX_UNPACKED:
            raise ArchiveError('Profile package exceeds the 64 GB unpacked size limit')
    try:
        info = archive.getinfo('manifest.json')
        if info.file_size > 64 * 1024 * 1024:
            raise ArchiveError('Profile package manifest is too large')
        manifest = json.loads(archive.read(info))
    except (KeyError, ValueError, UnicodeError) as exc:
        raise ArchiveError('This is not a valid XAnty profile package') from exc
    if not isinstance(manifest, dict) or manifest.get('format') != FORMAT or manifest.get('version') != VERSION:
        raise ArchiveError('Unsupported XAnty profile package version')
    profiles = manifest.get('profiles')
    if not isinstance(profiles, list) or not profiles:
        raise ArchiveError('Profile package contains no profiles')
    keys = set()
    for item in profiles:
        if not isinstance(item, dict) or not isinstance(item.get('key'), str) or not re.fullmatch(r'[0-9]{6,12}', item['key']):
            raise ArchiveError('Invalid profile entry in package')
        if item['key'] in keys:
            raise ArchiveError('Duplicate profile entry in package')
        keys.add(item['key'])
        account = item.get('account')
        if not isinstance(account, dict) or not _NAME.fullmatch(str(account.get('username', ''))):
            raise ArchiveError('Invalid profile username in package')
        group = account.get('group') or ''
        if group:
            folder_name(group)
        browser_settings(account)
        if type(account.get('auto_login', False)) is not bool:
            raise ArchiveError('Invalid automatic sign-in setting in package')
        for name in ('password', 'proxy', 'auth_token', 'ct0_token'):
            if not isinstance(account.get(name, ''), (str, type(None))):
                raise ArchiveError('Invalid profile settings in package')
    allowed = {'manifest.json'}
    prefixes = tuple(f'profiles/{key}/browser/' for key in keys)
    allowed.update(f'profiles/{key}/cookies.json' for key in keys)
    for info in archive.infolist():
        if not info.is_dir() and info.filename not in allowed and not info.filename.startswith(prefixes):
            raise ArchiveError('Unexpected file in profile package')
    if not isinstance(manifest.get('folders', []), list):
        raise ArchiveError('Invalid folder list in profile package')
    for name in manifest.get('folders', []):
        folder_name(name)
    filenames = set(archive.namelist())
    if any(f'profiles/{key}/cookies.json' not in filenames for key in keys):
        raise ArchiveError('Profile package is missing session files. Export the profiles again.')
    return manifest


def inspect_package(path: Path) -> dict:
    try:
        with ZipFile(path) as archive:
            manifest = _read_manifest(archive)
        return {'total': len(manifest['profiles']), 'created_at': manifest.get('created_at', ''),
                'profiles': [{'username': p['account']['username'], 'group': p['account'].get('group', '')}
                             for p in manifest['profiles']]}
    except (BadZipFile, OSError, ValueError) as exc:
        raise ArchiveError(str(exc) if isinstance(exc, ArchiveError) else 'Could not read the XAnty profile package') from exc


def import_package(config, account_manager, folders, source: Path, duplicates='rename',
                   progress=None, cancelled=None, commit_lock=None) -> dict:
    if duplicates not in ('rename', 'skip'):
        raise ArchiveError('Choose rename or skip for existing profiles')
    report, prepared, committed = [], [], []
    previous_folders = None
    config.base_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.xanty-import-', dir=config.base_dir) as staging:
        stage = Path(staging)
        try:
            with ZipFile(source) as archive:
                manifest = _read_manifest(archive)
                existing = account_manager.load_accounts()
                reserved = {a['username'].casefold() for a in existing}
                reserved.update(p.name.removeprefix('profile_').casefold() for p in config.browser_profiles_dir.glob('profile_*'))
                cookies_root = config.base_dir / 'kook'
                if cookies_root.is_dir():
                    reserved.update(p.name.lstrip('@').casefold() for p in cookies_root.iterdir())
                for index, item in enumerate(manifest['profiles']):
                    if cancelled and cancelled():
                        raise ArchiveError('Operation cancelled')
                    account = copy.deepcopy(item['account'])
                    old = account['username']
                    if duplicates == 'skip' and old.casefold() in reserved:
                        report.append({'username': old, 'status': 'skipped'})
                    else:
                        account['username'] = unique_name(old, reserved)
                        prefix = f"profiles/{item['key']}"
                        cookie_name = prefix + '/cookies.json'
                        if archive.getinfo(cookie_name).file_size > 64 * 1024 * 1024:
                            raise ArchiveError('Portable session is too large')
                        cookies = normalize_session(json.loads(archive.read(cookie_name)))
                        target = stage / item['key']
                        browser = target / 'browser'
                        browser.mkdir(parents=True)
                        for info in archive.infolist():
                            if not info.filename.startswith(prefix + '/browser/') or info.is_dir():
                                continue
                            if cancelled and cancelled():
                                raise ArchiveError('Operation cancelled')
                            relative = PurePosixPath(info.filename[len(prefix + '/browser/'):])
                            output = browser.joinpath(*relative.parts)
                            output.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(info) as reader, output.open('wb') as writer:
                                shutil.copyfileobj(reader, writer, 1024 * 1024)
                        # Windows encryption keys belong to the sending machine. Cookie
                        # values are restored through CDP and encrypted by the recipient.
                        state = browser / 'Local State'
                        if state.is_file():
                            try:
                                data = json.loads(state.read_text(encoding='utf-8'))
                                data.pop('os_crypt', None)
                                state.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                            except (OSError, ValueError):
                                pass
                        prepared.append((account, cookies, browser))
                        report.append({'username': account['username'], 'original_username': old,
                                       'status': 'prepared', 'cookies': len(cookies)})
                    if progress:
                        progress(processed=index + 1, total=len(manifest['profiles']), report=report)
            # Changes to account metadata stay on the application's event loop.
            # File staging has finished and no account is overwritten during commit.
            if cancelled and cancelled():
                raise ArchiveError('Operation cancelled')
            lock = commit_lock
            if lock:
                lock.acquire()
            try:
                current = account_manager.load_accounts()
                previous_folders = folders.list()
                current_names = {a['username'].casefold() for a in current}
                for account, cookies, browser in prepared:
                    username = account['username']
                    destination = config.browser_profiles_dir / f'profile_{username}'
                    cookie_path = get_cookies_file_path(config, username).parent
                    if username.casefold() in current_names or destination.exists() or cookie_path.exists():
                        raise ArchiveError('Profile list changed during import; please retry')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(browser), str(destination))
                    committed.append((destination, cookie_path))
                    if cookies:
                        store_session(config, username, cookies, pending=True)
                        try:
                            x_cookies = normalize_cookies(cookies)
                        except CookieError:
                            x_cookies = []
                        if x_cookies:
                            store_cookies(config, username, x_cookies)
                    current.append(account)
                    current_names.add(username.casefold())
                folders.sync([*manifest.get('folders', []), *[a.get('group', '') for a in current]])
                canonical = {name.casefold(): name for name in folders.list()}
                for account in current:
                    group = account.get('group') or ''
                    if group:
                        account['group'] = canonical.get(group.casefold(), group)
                if prepared:
                    account_manager.save_accounts(current)
                for row in report:
                    if row['status'] == 'prepared':
                        row['status'] = 'imported'
                if progress:
                    progress(processed=len(report), total=len(manifest['profiles']), report=report)
            finally:
                if lock:
                    lock.release()
        except Exception as exc:
            for directory, cookie_path in committed:
                shutil.rmtree(directory, ignore_errors=True)
                shutil.rmtree(cookie_path, ignore_errors=True)
            if previous_folders is not None:
                folders._save(previous_folders)
            if isinstance(exc, ArchiveError):
                raise
            if isinstance(exc, PermissionError):
                raise ArchiveError('Cannot save profile files. Check write access to the workspace folder.') from exc
            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                raise ArchiveError('Not enough disk space to import profiles. Free space in the workspace folder.') from exc
            raise ArchiveError('Could not import the profile package') from exc
    return {'total': len(report), 'report': report}
