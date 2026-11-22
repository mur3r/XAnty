"""Side-by-side Windows Chrome for Testing + ChromeDriver pairs.

Only Google's official CfT manifests and exact-version win64 asset URLs are
accepted. Downloads are authenticated by HTTPS, checked for ZIP CRC/data errors,
and matched to both executables' PE version resources without running them.
CfT's manifests do not publish signed hashes: ``hash_verified`` is always False.

``install`` does not select a version. Callers must close/guard profile launches
before ``select``/``delete``; the process scan is an additional best-effort guard
(processes whose executable is inaccessible cannot be identified).

Official API: https://github.com/GoogleChromeLabs/chrome-for-testing#json-api-endpoints
Pairing: https://developer.chrome.com/docs/chromedriver/downloads/version-selection
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import shutil
import stat
import struct
import tempfile
import threading
import time
import zipfile
import zlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psutil
import requests


MANIFEST_BASE = 'https://googlechromelabs.github.io/chrome-for-testing/'
CHANNEL_MANIFEST = MANIFEST_BASE + 'last-known-good-versions-with-downloads.json'
VERSIONS_MANIFEST = MANIFEST_BASE + 'known-good-versions-with-downloads.json'
CHANNELS = ('Stable', 'Beta', 'Dev', 'Canary')
PLATFORM = 'win64'
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 512 * 1024 * 1024
MAX_EXTRACTED_BYTES = 2 * 1024 * 1024 * 1024
MAX_FILE_BYTES = 1024 * 1024 * 1024
MAX_ZIP_MEMBERS = 20000
TRANSFER_SECONDS = 30 * 60
CHUNK_BYTES = 256 * 1024
VERIFICATION = 'Official HTTPS, ZIP CRC/data checks, exact PE executable versions; no vendor checksum supplied.'
_VERSION_RE = re.compile(r'(?:0|[1-9]\d{0,4})(?:\.(?:0|[1-9]\d{0,4})){3}\Z', re.ASCII)
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'} | {
    prefix + suffix for prefix in ('COM', 'LPT') for suffix in '123456789¹²³'}


class ChromiumVersionError(ValueError):
    """A version operation could not be safely completed."""


def _version(value):
    if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
        raise ChromiumVersionError('Use a full four-part Chromium version or an official channel.')
    parts = tuple(int(part) for part in value.split('.'))
    if any(part > 65535 for part in parts):
        raise ChromiumVersionError('Invalid Chromium version.')
    return value


def _trusted_url(url, binary=None, version=None):
    if not isinstance(url, str):
        raise ChromiumVersionError('The official manifest contains an invalid download URL.')
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != 'https' or parsed.query or parsed.fragment or parsed.username
                or parsed.password or parsed.port is not None):
            raise ValueError
    except ValueError:
        raise ChromiumVersionError('Only official HTTPS Chrome for Testing URLs are allowed.') from None
    if binary is not None:
        expected = f'https://storage.googleapis.com/chrome-for-testing-public/{_version(version)}/win64/{binary}-win64.zip'
        valid = binary in ('chrome', 'chromedriver') and url == expected
    else:
        valid = parsed.netloc == 'googlechromelabs.github.io' and (
            url in (CHANNEL_MANIFEST, VERSIONS_MANIFEST)
            or (url.startswith(MANIFEST_BASE) and url.endswith('.json')
                and _VERSION_RE.fullmatch(url[len(MANIFEST_BASE):-5]) is not None))
    if not valid:
        raise ChromiumVersionError('Download URL is outside the official exact-version Chrome for Testing assets.')
    return url


def _cancel(cancelled):
    if cancelled is not None and (cancelled() if callable(cancelled) else cancelled.is_set()):
        raise ChromiumVersionError('Chromium installation cancelled.')


def _report(progress, **event):
    if progress is not None:
        # Reporting must never turn a committed installation into an apparent failure.
        try:
            progress(event)
        except Exception:
            pass


def _transfer(url, stream, limit, cancelled=None, progress=None, version=None, binary=None):
    """Stream with no redirects, bounded bytes, socket timeouts and a total deadline."""
    _cancel(cancelled)
    _trusted_url(url, binary, version)
    start, count = time.monotonic(), 0
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(url, stream=True, timeout=(8, 20), allow_redirects=False, verify=True,
                             headers={'Accept-Encoding': 'identity', 'User-Agent': 'XAnty-CfT/1'}) as response:
                if response.status_code != 200 or getattr(response, 'url', url) != url:
                    raise ChromiumVersionError('Chrome for Testing returned an unexpected HTTP response or redirect.')
                if response.headers.get('Content-Encoding', 'identity').lower() not in ('', 'identity'):
                    raise ChromiumVersionError('Unexpected download content encoding.')
                length = response.headers.get('Content-Length')
                if length is not None and (not str(length).isdigit() or not 0 < int(length) <= limit):
                    raise ChromiumVersionError('Chrome for Testing download exceeds the size limit or is empty.')
                total = int(length) if length is not None else None
                for chunk in response.iter_content(CHUNK_BYTES):
                    _cancel(cancelled)
                    if time.monotonic() - start > TRANSFER_SECONDS:
                        raise ChromiumVersionError('Chromium download exceeded the time limit.')
                    if not chunk:
                        continue
                    count += len(chunk)
                    if count > limit or (total is not None and count > total):
                        raise ChromiumVersionError('Chrome for Testing download exceeds the advertised size or size limit.')
                    stream.write(chunk)
                    _report(progress, phase='download', version=version, binary=binary, downloaded=count, total=total)
                _cancel(cancelled)
                if not count or (total is not None and count != total):
                    raise ChromiumVersionError('Chrome for Testing download is incomplete.')
    except requests.exceptions.RequestException as error:
        raise ChromiumVersionError('Cannot download Chrome for Testing. Check the connection and retry.') from error


def _fetch_manifest(url, cancelled=None):
    import io
    stream = io.BytesIO()
    _transfer(url, stream, MAX_MANIFEST_BYTES, cancelled)
    try:
        data = json.loads(stream.getvalue().decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeError):
        raise ChromiumVersionError('Chrome for Testing returned an invalid JSON manifest.') from None


def _pair(data, expected=None):
    if not isinstance(data, dict):
        raise ChromiumVersionError('Chrome for Testing returned an invalid version record.')
    version = _version(data.get('version'))
    if expected is not None and version != expected:
        raise ChromiumVersionError('The manifest version does not match the requested version.')
    downloads = data.get('downloads', {})
    if not isinstance(downloads, dict):
        raise ChromiumVersionError('The manifest downloads are invalid.')
    urls = {}
    for binary in ('chrome', 'chromedriver'):
        rows = downloads.get(binary, [])
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ChromiumVersionError('The manifest platform downloads are invalid.')
        matches = [row for row in rows if row.get('platform') == PLATFORM]
        if not matches:
            return None
        if len(matches) != 1:
            raise ChromiumVersionError('The manifest contains ambiguous platform downloads.')
        urls[binary] = _trusted_url(matches[0].get('url'), binary, version)
    return {'version': version, 'revision': str(data.get('revision', ''))[:100],
            'platform': PLATFORM, 'downloads': urls}


def _file_version(path):
    """Read Windows version resources. Never launch the downloaded executable."""
    if os.name != 'nt':
        raise ChromiumVersionError('Executable version validation requires Windows.')
    from ctypes import wintypes
    api = ctypes.WinDLL('version', use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
    api.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    api.GetFileVersionInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    api.GetFileVersionInfoW.restype = wintypes.BOOL
    api.VerQueryValueW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR,
                                  ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.UINT)]
    api.VerQueryValueW.restype = wintypes.BOOL
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not 0 < size <= 16 * 1024 * 1024:
        raise ChromiumVersionError('Executable has no valid Windows version resource.')
    buffer = ctypes.create_string_buffer(size)
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if (not api.GetFileVersionInfoW(str(path), 0, size, buffer)
            or not api.VerQueryValueW(buffer, '\\', ctypes.byref(pointer), ctypes.byref(length))
            or length.value < 52 or not pointer.value):
        raise ChromiumVersionError('Cannot read the executable Windows version resource.')
    signature, _, high, low = struct.unpack('<4I', ctypes.string_at(pointer, 16))
    if signature != 0xFEEF04BD:
        raise ChromiumVersionError('Invalid executable Windows version resource.')
    return '.'.join(str(part) for part in (high >> 16, high & 65535, low >> 16, low & 65535))


def _validate_binary(path, version):
    if not path.is_file() or not 64 <= path.stat().st_size <= MAX_FILE_BYTES:
        raise ChromiumVersionError('Installed executable is missing or has an invalid size.')
    with path.open('rb') as stream:
        header = stream.read(64)
        if header[:2] != b'MZ':
            raise ChromiumVersionError('Download is not a Windows executable.')
        offset = struct.unpack_from('<I', header, 60)[0]
        if not 64 <= offset <= min(path.stat().st_size - 6, 1024 * 1024):
            raise ChromiumVersionError('Executable has an invalid PE header.')
        stream.seek(offset)
        if stream.read(6) != b'PE\0\0\x64\x86':
            raise ChromiumVersionError('The executable is not a win64 PE binary.')
    if _file_version(path) != version:
        raise ChromiumVersionError('Chrome and ChromeDriver executable versions must both match the exact requested version.')


def _zip_parts(info, binary):
    name = info.orig_filename
    mode = stat.S_IFMT(info.external_attr >> 16)
    if (mode not in (0, stat.S_IFREG, stat.S_IFDIR) or info.external_attr & 0x400
            or info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
        raise ChromiumVersionError('ZIP contains a link, reparse point, encrypted entry or unsupported compression.')
    if (not name or '\\' in name or '\0' in name
            or (mode == stat.S_IFDIR and not info.is_dir())
            or (info.is_dir() and info.file_size != 0)):
        raise ChromiumVersionError('ZIP contains an unsafe path.')
    parts = name[:-1].split('/') if info.is_dir() else name.split('/')
    for part in parts:
        if (not part or part in ('.', '..') or part.endswith((' ', '.'))
                or any(ord(char) < 32 or char in '<>:"\\|?*' for char in part)
                or part.split('.')[0].rstrip(' .').upper() in _RESERVED):
            raise ChromiumVersionError('ZIP contains an unsafe Windows path.')
    if parts[0] != binary + '-win64' or (len(parts) == 1 and not info.is_dir()):
        raise ChromiumVersionError('ZIP contains an unexpected asset directory.')
    return parts


class ChromiumVersionManager:
    def __init__(self, config):
        self.base_dir = Path(config.base_dir).resolve()
        self.root = self.base_dir / 'chromium_versions'
        self._thread_lock = threading.RLock()

    def _safe(self, path):
        path = Path(path)
        try:
            parts = path.relative_to(self.root).parts
        except ValueError:
            raise ChromiumVersionError('Version path is outside the managed directory.') from None
        current = self.root
        for part in (None,) + parts:
            if part is not None:
                current = current / part
            try:
                attributes = current.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, 'st_file_attributes', 0) & 0x400:
                raise ChromiumVersionError('Managed version paths cannot contain links or reparse points.')
        if not path.resolve().is_relative_to(self.root):
            raise ChromiumVersionError('Version path escapes the managed directory.')
        return path

    @contextmanager
    def _mutation(self):
        with self._thread_lock:
            self._safe(self.root).mkdir(parents=True, exist_ok=True)
            path = self._safe(self.root / '.manager.lock')
            stream = path.open('a+b')
            locked = False
            try:
                if stream.seek(0, 2) == 0:
                    stream.write(b'0')
                    stream.flush()
                stream.seek(0)
                try:
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                except OSError:
                    raise ChromiumVersionError('Another Chromium version operation is already running.') from None
                yield
            except OSError as error:
                raise ChromiumVersionError('Cannot update the Chromium version store: ' + str(error)) from error
            finally:
                if locked:
                    stream.seek(0)
                    if os.name == 'nt':
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                stream.close()

    def _read_json(self, path):
        self._safe(path)
        if path.stat().st_size > 64 * 1024:
            raise ChromiumVersionError('Version metadata exceeds the size limit.')
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or data.get('schema') != 1:
            raise ChromiumVersionError('Invalid version metadata.')
        return data

    def _atomic_json(self, path, data):
        self._safe(path)
        descriptor, filename = tempfile.mkstemp(prefix=('.selection-' if path.name == 'selection.json' else '.metadata-'), dir=path.parent)
        temporary = Path(filename)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _requested_selection(self):
        path = self.root / 'selection.json'
        self._safe(path)
        if not path.exists():
            return 'bundled', ''
        try:
            selected = self._read_json(path).get('selected')
            if selected != 'bundled':
                _version(selected)
            return selected, ''
        except (OSError, ValueError, TypeError):
            return 'bundled', 'The saved Chromium selection is invalid; using the bundled browser.'

    def _paths(self, version):
        if version == 'bundled':
            return self.base_dir / 'Bro/chrome.exe', self.base_dir / 'Drivers/chromedriver.exe'
        root = self._safe(self.root / _version(version))
        return self._safe(root / 'chrome-win64/chrome.exe'), self._safe(root / 'chromedriver-win64/chromedriver.exe')

    def _installed(self, version):
        root = self._safe(self.root / _version(version))
        data = self._read_json(root / 'installation.json')
        if data.get('version') != version or data.get('platform') != PLATFORM:
            raise ChromiumVersionError('Installed version metadata does not match the directory.')
        urls = data.get('downloads')
        if not isinstance(urls, dict):
            raise ChromiumVersionError('Installed version metadata has no official download sources.')
        for binary in ('chrome', 'chromedriver'):
            _trusted_url(urls.get(binary), binary, version)
        chrome, driver = self._paths(version)
        _validate_binary(chrome, version)
        _validate_binary(driver, version)
        return {'version': version, 'chrome_path': str(chrome), 'driver_path': str(driver),
                'source': 'chrome-for-testing', 'platform': PLATFORM, 'available': True,
                'valid': True, 'installed_at': str(data.get('installed_at', '')),
                'verification': VERIFICATION, 'hash_verified': False}

    def snapshot(self):
        """Return local state without network access; damaged selections fall back visibly."""
        self._safe(self.root)
        requested, error = self._requested_selection()
        chrome, driver = self._paths('bundled')
        installed = [{'version': 'bundled', 'chrome_path': str(chrome), 'driver_path': str(driver),
                      'source': 'bundled', 'available': chrome.is_file() and driver.is_file(),
                      'valid': chrome.is_file() and driver.is_file(), 'hash_verified': False}]
        if self.root.exists():
            versions = sorted((path.name for path in self.root.iterdir() if _VERSION_RE.fullmatch(path.name)),
                              key=lambda value: tuple(int(part) for part in value.split('.')), reverse=True)
            for version in versions:
                try:
                    installed.append(self._installed(version))
                except (OSError, ValueError, TypeError) as failure:
                    installed.append({'version': version, 'source': 'chrome-for-testing',
                                      'available': False, 'valid': False, 'error': str(failure), 'hash_verified': False})
        selected = requested
        if selected != 'bundled' and not any(row['version'] == selected and row['available'] for row in installed):
            selected = 'bundled'
            error = 'The selected Chromium pair is unavailable or invalid; using the bundled browser.'
        for row in installed:
            row['selected'] = row['version'] == selected
        return {'installed': installed, 'selected': selected, 'requested_selected': requested,
                'selection_error': error, 'platform': PLATFORM, 'hash_verified': False, 'verification': VERIFICATION}

    def active_paths(self):
        """Resolve a validated selected pair, or the original Bro/Drivers fallback."""
        return self._paths(self.snapshot()['selected'])

    def available(self):
        """Fetch official channels and complete known-good win64 pairs."""
        channels_data, versions_data = _fetch_manifest(CHANNEL_MANIFEST), _fetch_manifest(VERSIONS_MANIFEST)
        source_channels, source_versions = channels_data.get('channels'), versions_data.get('versions')
        if not isinstance(source_channels, dict) or not isinstance(source_versions, list):
            raise ChromiumVersionError('Chrome for Testing returned an invalid versions manifest.')
        channels = {}
        for channel in CHANNELS:
            if channel in source_channels:
                pair = _pair(source_channels[channel])
                if pair:
                    channels[channel] = dict(pair, channel=channel)
        versions = {}
        for row in source_versions:
            pair = _pair(row)
            if pair:
                versions[pair['version']] = pair
        return {'channels': channels,
                'versions': sorted(versions.values(), key=lambda row: tuple(map(int, row['version'].split('.'))), reverse=True),
                'timestamp': str(versions_data.get('timestamp', '')), 'platform': PLATFORM,
                'hash_verified': False, 'verification': VERIFICATION}

    def _remove_tree(self, path):
        self._safe(path)
        for current, directories, files in os.walk(path, followlinks=False):
            self._safe(Path(current))
            for name in directories + files:
                self._safe(Path(current) / name)
        shutil.rmtree(path)

    def _extract(self, archive, destination, binary, version, progress, cancelled, budget):
        expanded, seen, files = 0, set(), set()
        try:
            with zipfile.ZipFile(archive) as source:
                members = source.infolist()
                if len(members) > MAX_ZIP_MEMBERS:
                    raise ChromiumVersionError('ZIP has too many entries.')
                checked = []
                for info in members:
                    _cancel(cancelled)
                    parts = _zip_parts(info, binary)
                    key = '/'.join(parts).casefold()
                    if key in seen:
                        raise ChromiumVersionError('ZIP contains duplicate Windows paths.')
                    seen.add(key)
                    if not info.is_dir():
                        files.add(key)
                    if info.file_size > MAX_FILE_BYTES:
                        raise ChromiumVersionError('ZIP entry exceeds the extracted file size limit.')
                    expanded += info.file_size
                    if expanded > budget:
                        raise ChromiumVersionError('ZIP exceeds the extracted size limit.')
                    checked.append((info, parts, key))
                for _, parts, _ in checked:
                    if any('/'.join(parts[:index]).casefold() in files for index in range(1, len(parts))):
                        raise ChromiumVersionError('ZIP contains conflicting file and directory paths.')
                extracted = 0
                for info, parts, _ in checked:
                    _cancel(cancelled)
                    target = self._safe(destination.joinpath(*parts))
                    if info.is_dir():
                        target.mkdir(parents=True, exist_ok=True)
                        continue
                    self._safe(target.parent).mkdir(parents=True, exist_ok=True)
                    count = 0
                    with source.open(info) as reader, target.open('xb') as writer:
                        while True:
                            _cancel(cancelled)
                            chunk = reader.read(CHUNK_BYTES)
                            if not chunk:
                                break
                            count += len(chunk)
                            extracted += len(chunk)
                            if count > info.file_size or extracted > budget:
                                raise ChromiumVersionError('ZIP data exceeds its advertised extracted size.')
                            writer.write(chunk)
                            _report(progress, phase='extract', version=version, binary=binary,
                                    extracted=extracted, total=expanded)
                    if count != info.file_size:
                        raise ChromiumVersionError('ZIP entry data is incomplete.')
                return expanded
        except (zipfile.BadZipFile, zlib.error, RuntimeError, EOFError, NotImplementedError) as error:
            raise ChromiumVersionError('Downloaded ZIP failed its CRC or data validation.') from error

    def install(self, version_or_channel, progress=None, cancelled=None):
        """Install a complete pair atomically; return its row without selecting it.

        ``progress`` receives dictionaries (phase, version, binary, downloaded or
        extracted, total). ``cancelled`` accepts a zero-argument callable or Event.
        """
        if not isinstance(version_or_channel, str):
            raise ChromiumVersionError('Choose an official channel or a full Chromium version.')
        channel = next((name for name in CHANNELS if name.casefold() == version_or_channel.casefold()), None)
        version = None if channel else _version(version_or_channel)
        _cancel(cancelled)
        with self._mutation():
            if version and (self.root / version).exists():
                row = self._installed(version)
                row['selected'] = self.snapshot()['selected'] == version
                return row
            _report(progress, phase='resolve', version=version, channel=channel)
            if channel:
                data = _fetch_manifest(CHANNEL_MANIFEST, cancelled).get('channels')
                if not isinstance(data, dict) or channel not in data:
                    raise ChromiumVersionError('The official release channel is unavailable.')
                pair = _pair(data[channel])
            else:
                pair = _pair(_fetch_manifest(MANIFEST_BASE + version + '.json', cancelled), version)
            if not pair:
                raise ChromiumVersionError('This version has no complete Chrome and ChromeDriver win64 pair.')
            version = pair['version']
            final = self._safe(self.root / version)
            if final.exists():
                row = self._installed(version)
                row['selected'] = self.snapshot()['selected'] == version
                return row
            stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.root))
            try:
                payload = self._safe(stage / 'payload')
                payload.mkdir()
                budget = MAX_EXTRACTED_BYTES
                for binary in ('chrome', 'chromedriver'):
                    _cancel(cancelled)
                    archive = self._safe(stage / (binary + '.zip'))
                    with archive.open('xb') as stream:
                        _transfer(pair['downloads'][binary], stream, MAX_DOWNLOAD_BYTES,
                                  cancelled, progress, version, binary)
                    budget -= self._extract(archive, payload, binary, version, progress, cancelled, budget)
                    archive.unlink()
                    _validate_binary(self._safe(payload / (binary + '-win64') / (binary + '.exe')), version)
                _cancel(cancelled)
                self._atomic_json(payload / 'installation.json', dict(pair, schema=1,
                    installed_at=datetime.now(timezone.utc).isoformat(), verification=VERIFICATION, hash_verified=False))
                self._safe(final)
                os.rename(payload, final)
            finally:
                if stage.exists():
                    self._remove_tree(stage)
            row = self._installed(version)
            row['selected'] = self.snapshot()['selected'] == version
            _report(progress, phase='complete', version=version)
            return row

    def _require_stopped(self, version=None):
        boundary = self.root if version is None else self.root / _version(version)
        bundled = {os.path.normcase(str(path)) for path in self._paths('bundled')} if version is None else set()
        try:
            for process in psutil.process_iter(['exe', 'name']):
                try:
                    executable = process.info.get('exe')
                    if not executable:
                        continue
                    path = Path(executable).resolve()
                    if path.is_relative_to(boundary) or os.path.normcase(str(path)) in bundled:
                        raise ChromiumVersionError('A managed browser or driver is running. Close all profiles before changing versions.')
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
                    continue
        except psutil.Error as error:
            raise ChromiumVersionError('Cannot check running managed Chromium processes.') from error

    def select(self, version):
        """Atomically select an installed pair (or ``bundled``); return a snapshot."""
        if version != 'bundled':
            _version(version)
        with self._mutation():
            if version != 'bundled':
                self._installed(version)
            self._require_stopped()
            self._atomic_json(self.root / 'selection.json', {'schema': 1, 'selected': version})
            return self.snapshot()

    def delete(self, version):
        """Remove an unselected managed pair; never remove the bundled browser."""
        _version(version)
        with self._mutation():
            requested, _ = self._requested_selection()
            if requested == version:
                raise ChromiumVersionError('The selected Chromium version cannot be deleted. Select another version first.')
            self._require_stopped(version)
            target = self._safe(self.root / version)
            if target.exists():
                self._remove_tree(target)
