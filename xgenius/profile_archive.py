"""Stream complete profile packages without overwriting existing user profiles."""
from __future__ import annotations

import copy
import errno
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import zlib
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

from xgenius.cookies import CookieError, get_cookies_file_path, normalize_cookies, store_cookies
from xgenius.folders import folder_name
from xgenius.portable_session import export_session, normalize_session, store_session
from xgenius.profile_settings import browser_settings, workspace_settings

FORMAT = 'xanty-profile-package'
VERSION = 2
MAX_UNPACKED = 64 * 1024 ** 3
_CHUNK = 1024 * 1024
_MAX_METADATA = 64 * 1024 * 1024
_CHECKSUMS = 'checksums.json'
_LEGACY_WARNING = 'Package integrity is unavailable for this version 1 archive. Export it again to add SHA-256 checksums.'
_NAME = re.compile(r'^[A-Za-z0-9_]{1,32}$')
_CACHE = {'cache', 'code cache', 'gpucache', 'shadercache', 'grshadercache', 'dawncache',
          'crashpad', 'crash reports', 'browsermetrics', 'component_crx_cache', 'extensions_crx_cache'}
_PRIVACY_FLAGS = ('include_passwords', 'include_tokens', 'include_cookies',
                  'include_proxy_credentials', 'include_browser_data')
_SETTINGS_ONLY_WARNING = (
    'Settings-only export: all credentials, cookies, browser data, saved tabs and free-text metadata '
    'were omitted. Raw browser files and arbitrary metadata can contain indirect secrets, '
    'so requested secret exclusions also disable include_browser_data and other secret categories.')


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


def _excluded_file(name: str) -> bool:
    name = name.lower()
    return name.startswith('singleton') or name in {'lockfile', 'lock', 'debug.log', '.xanty-profile.lock'}


def _profile_files(root: Path):
    if not root.is_dir() or _linked(root):
        return
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(n for n in folders if n.lower() not in _CACHE and not _linked(Path(directory) / n))
        for name in sorted(files):
            path = Path(directory) / name
            if _excluded_file(name) or _linked(path):
                continue
            yield path


def _write_bytes(archive: ZipFile, name: str, data: bytes, checksums: dict) -> None:
    archive.writestr(name, data)
    checksums[name] = hashlib.sha256(data).hexdigest()


def _write_file(archive: ZipFile, name: str, path: Path, checksums: dict, cancelled=None) -> None:
    digest = hashlib.sha256()
    with path.open('rb') as reader, archive.open(name, 'w', force_zip64=True) as writer:
        while block := reader.read(_CHUNK):
            if cancelled and cancelled():
                raise ArchiveError('Operation cancelled')
            digest.update(block)
            writer.write(block)
    checksums[name] = digest.hexdigest()


def _integrity_result(version: int, file_count: int) -> dict:
    return {'integrity': 'verified' if version == VERSION else 'unavailable',
            'integrity_algorithm': 'sha256' if version == VERSION else None,
            'verified_files': file_count if version == VERSION else 0,
            'warnings': [] if version == VERSION else [_LEGACY_WARNING]}


def _privacy_policy(privacy) -> tuple[dict, dict]:
    """One omission requires settings-only output; opaque stores cannot be redacted reliably."""
    if privacy is not None and (not isinstance(privacy, dict) or
                                set(privacy) - set(_PRIVACY_FLAGS) or
                                any(type(value) is not bool for value in privacy.values())):
        raise ArchiveError('Invalid export privacy policy; use boolean include settings')
    requested = {key: (privacy or {}).get(key, True) for key in _PRIVACY_FLAGS}
    full = all(requested.values())
    return requested, {key: full for key in _PRIVACY_FLAGS}


def _settings_only_account(account: dict) -> dict:
    # Do not recursively redact untyped metadata: notes, Dolphin snapshots,
    # user-agent strings, proxy URLs, extension data and future fields can all
    # carry credentials under unrelated names. Preserve only typed settings.
    return {'username': account['username'], 'auto_login': False,
            **browser_settings(account), **workspace_settings(account)}


def export_package(config, accounts: list[dict], destination: Path, progress=None, cancelled=None,
                   folders=None, privacy=None) -> dict:
    requested_privacy, effective_privacy = _privacy_policy(privacy)
    full = effective_privacy['include_browser_data']
    if not accounts:
        raise ArchiveError('No profiles to export')
    manifest = {'format': FORMAT, 'version': VERSION,
                'created_at': datetime.now(timezone.utc).isoformat(), 'profiles': [],
                'folders': (folders or []) if full else [], 'privacy': effective_privacy}
    report, checksums = [], {}
    try:
        with ZipFile(destination, 'w', compression=ZIP_DEFLATED, compresslevel=3, allowZip64=True) as archive:
            for index, account in enumerate(accounts):
                if cancelled and cancelled():
                    raise ArchiveError('Operation cancelled')
                username = str(account.get('username') or '')
                if not _NAME.fullmatch(username):
                    raise ArchiveError('Invalid profile username')
                prefix = f'profiles/{index:06d}'
                cookies, warnings = export_session(config, username) if full else ([], [_SETTINGS_ONLY_WARNING])
                _write_bytes(archive, prefix + '/cookies.json', json.dumps(cookies, ensure_ascii=False).encode('utf-8'), checksums)
                tabs = get_cookies_file_path(config, username).parent / 'tabs.json'
                if full and tabs.is_file() and not _linked(tabs):
                    _write_file(archive, prefix + '/tabs.json', tabs, checksums, cancelled)
                browser_root = config.browser_profiles_dir / f'profile_{username}'
                file_count = 0
                for path in _profile_files(browser_root) if full else ():
                    if cancelled and cancelled():
                        raise ArchiveError('Operation cancelled')
                    _write_file(archive, prefix + '/browser/' + path.relative_to(browser_root).as_posix(),
                                path, checksums, cancelled)
                    file_count += 1
                manifest['profiles'].append({'key': f'{index:06d}',
                                             'account': copy.deepcopy(account) if full else _settings_only_account(account)})
                report.append({'username': username, 'status': 'exported', 'cookies': len(cookies),
                               'files': file_count, 'warnings': warnings, 'integrity': 'verified'})
                if progress:
                    progress(processed=index + 1, total=len(accounts), report=report)
            _write_bytes(archive, 'manifest.json', json.dumps(manifest, ensure_ascii=False).encode('utf-8'), checksums)
            archive.writestr(_CHECKSUMS, json.dumps({'algorithm': 'sha256', 'files': checksums}))
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    result = _integrity_result(VERSION, len(checksums))
    result['warnings'] = [warning for row in report for warning in row['warnings']]
    return {'total': len(accounts), 'report': report, 'filename': destination.name,
            'size': destination.stat().st_size, 'privacy': effective_privacy,
            'requested_privacy': requested_privacy, **result}


def _json_object(pairs) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ArchiveError('Duplicate metadata entry in profile package integrity data')
        result[key] = value
    return result


def _verify_integrity(archive: ZipFile, version: int, cancelled=None) -> dict:
    files = {info.filename: info for info in archive.infolist() if not info.is_dir() and info.filename != _CHECKSUMS}
    checksums = None
    if version == VERSION:
        try:
            descriptor_info = archive.getinfo(_CHECKSUMS)
            if descriptor_info.file_size > _MAX_METADATA:
                raise ArchiveError('Profile package integrity descriptor is too large')
            descriptor = json.loads(archive.read(descriptor_info), object_pairs_hook=_json_object)
        except (KeyError, ValueError, UnicodeError) as exc:
            raise ArchiveError('Profile package integrity checksums are missing or invalid') from exc
        if not isinstance(descriptor, dict) or descriptor.get('algorithm') != 'sha256':
            raise ArchiveError('Unsupported profile package integrity algorithm')
        checksums = descriptor.get('files')
        if not isinstance(checksums, dict) or set(checksums) != set(files):
            raise ArchiveError('Profile package integrity checksum entries do not match its files')
        if any(not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value) for value in checksums.values()):
            raise ArchiveError('Invalid profile package integrity checksum')
    # Read even skipped legacy profiles completely so ZIP CRC failures are caught
    # before account/folder commits. Large browser files never enter memory at once.
    for name, info in files.items():
        digest = hashlib.sha256() if checksums is not None else None
        with archive.open(info) as reader:
            while block := reader.read(_CHUNK):
                if cancelled and cancelled():
                    raise ArchiveError('Operation cancelled')
                if digest is not None:
                    digest.update(block)
        if digest is not None and digest.hexdigest() != checksums[name]:
            raise ArchiveError('Profile package integrity checksum mismatch. Export the profiles again.')
    return _integrity_result(version, len(files))


def _read_manifest(archive: ZipFile, cancelled=None) -> tuple[dict, dict]:
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
        if info.file_size > _MAX_METADATA:
            raise ArchiveError('Profile package manifest is too large')
        manifest = json.loads(archive.read(info), object_pairs_hook=_json_object)
    except (KeyError, ValueError, UnicodeError) as exc:
        raise ArchiveError('This is not a valid XAnty profile package') from exc
    if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT
            or type(manifest.get('version')) is not int or manifest['version'] not in (1, VERSION)):
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
        workspace_settings(account)
        if type(account.get('auto_login', False)) is not bool:
            raise ArchiveError('Invalid automatic sign-in setting in package')
        for name in ('password', 'proxy', 'auth_token', 'ct0_token', 'proxy_rotation_url'):
            if not isinstance(account.get(name, ''), (str, type(None))):
                raise ArchiveError('Invalid profile settings in package')
    allowed = {'manifest.json'}
    if manifest['version'] == VERSION:
        allowed.add(_CHECKSUMS)
    prefixes = tuple(f'profiles/{key}/browser/' for key in keys)
    allowed.update(f'profiles/{key}/cookies.json' for key in keys)
    allowed.update(f'profiles/{key}/tabs.json' for key in keys)
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
    return manifest, _verify_integrity(archive, manifest['version'], cancelled)


def inspect_package(path: Path) -> dict:
    try:
        with ZipFile(path) as archive:
            manifest, integrity = _read_manifest(archive)
        return {'total': len(manifest['profiles']), 'created_at': manifest.get('created_at', ''),
                'profiles': [{'username': p['account']['username'], 'group': p['account'].get('group', '')}
                             for p in manifest['profiles']], **integrity}
    except (BadZipFile, zlib.error, OSError, ValueError) as exc:
        message = ('Profile package integrity check failed: corrupt ZIP data' if isinstance(exc, (BadZipFile, zlib.error))
                   else str(exc) if isinstance(exc, ArchiveError) else 'Could not read the XAnty profile package')
        raise ArchiveError(message) from exc


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
                manifest, integrity = _read_manifest(archive, cancelled)
                existing = account_manager.load_accounts()
                reserved = {a['username'].casefold() for a in existing}
                reserved.update(getattr(account_manager, 'reserved_profile_names', lambda: set())())
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
                        report.append({'username': old, 'status': 'skipped', 'integrity': integrity['integrity'],
                                       'warnings': list(integrity['warnings'])})
                    else:
                        account['username'] = unique_name(old, reserved)
                        prefix = f"profiles/{item['key']}"
                        cookie_name = prefix + '/cookies.json'
                        if archive.getinfo(cookie_name).file_size > _MAX_METADATA:
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
                            if _excluded_file(relative.name):
                                continue
                            output = browser.joinpath(*relative.parts)
                            output.parent.mkdir(parents=True, exist_ok=True)
                            with archive.open(info) as reader, output.open('wb') as writer:
                                shutil.copyfileobj(reader, writer, _CHUNK)
                        tabs = None
                        if prefix + '/tabs.json' in archive.namelist():
                            tabs = target / 'tabs.json'
                            with archive.open(prefix + '/tabs.json') as reader, tabs.open('wb') as writer:
                                shutil.copyfileobj(reader, writer, _CHUNK)
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
                        prepared.append((account, cookies, browser, tabs))
                        report.append({'username': account['username'], 'original_username': old,
                                       'status': 'prepared', 'cookies': len(cookies),
                                       'integrity': integrity['integrity'], 'warnings': list(integrity['warnings'])})
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
                for account, cookies, browser, tabs in prepared:
                    username = account['username']
                    destination = config.browser_profiles_dir / f'profile_{username}'
                    cookie_path = get_cookies_file_path(config, username).parent
                    if username.casefold() in current_names or destination.exists() or cookie_path.exists():
                        raise ArchiveError('Profile list changed during import; please retry')
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(browser), str(destination))
                    committed.append((destination, cookie_path))
                    if tabs is not None:
                        cookie_path.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(tabs), str(cookie_path / 'tabs.json'))
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
            if isinstance(exc, (BadZipFile, zlib.error)):
                raise ArchiveError('Profile package integrity check failed: corrupt ZIP data') from exc
            if isinstance(exc, PermissionError):
                raise ArchiveError('Cannot save profile files. Check write access to the workspace folder.') from exc
            if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
                raise ArchiveError('Not enough disk space to import profiles. Free space in the workspace folder.') from exc
            raise ArchiveError('Could not import the profile package') from exc
    return {'total': len(report), 'report': report, **integrity}
