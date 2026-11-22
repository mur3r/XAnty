"""Verified GitHub Releases updates for the Windows onefile application."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from xgenius import __version__
from xgenius.config import application_home

CHECK_INTERVAL = 24 * 60 * 60
MAX_DOWNLOAD = 1024 * 1024 * 1024


class UpdateError(Exception):
    pass


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r'v?\d+(?:\.\d+){1,3}', value):
        raise UpdateError('The release version is invalid. Use a numeric tag such as v2026.11.22.3.')
    parts = tuple(int(n) for n in value.lstrip('v').split('.'))
    return parts + (0,) * (4 - len(parts))


def read_update_config():
    try:
        data = json.loads(Path(__file__).with_name('update_config.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    repository = os.environ.get('XANTY_UPDATE_REPOSITORY', data.get('repository', ''))
    if not isinstance(repository, str) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        repository = ''
    return {'repository': repository, 'asset': 'XAnty.exe'}


def select_release(data, repository, current_version):
    if not isinstance(data, dict):
        raise UpdateError('GitHub returned an invalid release.')
    if data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name', '')
    if version_tuple(tag) <= version_tuple(current_version):
        return None
    asset = next((a for a in data.get('assets', []) if isinstance(a, dict) and a.get('name') == 'XAnty.exe'), None)
    if not asset:
        raise UpdateError('The GitHub release has no XAnty.exe. Attach a Windows onefile build.')
    digest = asset.get('digest', '')
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[a-fA-F0-9]{64}', digest):
        raise UpdateError('GitHub did not provide a SHA-256 digest. The update cannot be verified.')
    url = asset.get('browser_download_url', '')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'github.com'
            or not parsed.path.startswith('/' + repository + '/releases/download/')
            or parsed.query or parsed.fragment):
        raise UpdateError('The update download does not belong to the configured GitHub repository.')
    size = asset.get('size')
    if isinstance(size, bool) or not isinstance(size, int) or not 2 <= size <= MAX_DOWNLOAD:
        raise UpdateError('The update file size is invalid.')
    return {'version': tag.lstrip('v'), 'tag': tag, 'url': url, 'sha256': digest[7:].lower(), 'size': size,
            'notes': str(data.get('body') or '')[:20000],
            'page_url': f'https://github.com/{repository}/releases/tag/{tag}'}


def fetch_release(repository, current_version):
    import requests
    with requests.Session() as session:
        session.trust_env = False
        try:
            response = session.get(f'https://api.github.com/repos/{repository}/releases/latest',
                                   headers={'Accept': 'application/vnd.github+json',
                                            'User-Agent': 'XAnty-Updater/' + current_version}, timeout=(6, 15))
            if response.status_code == 404:
                raise UpdateError('No public GitHub release found. Publish the first release and check the repository name.')
            if response.status_code in (403, 429):
                raise UpdateError('GitHub request limit reached. Try checking for updates later.')
            if response.status_code != 200:
                raise UpdateError(f'GitHub update check returned HTTP {response.status_code}. Try again later.')
            return select_release(response.json(), repository, current_version)
        except (requests.exceptions.RequestException, ValueError):
            raise UpdateError('Cannot connect to GitHub. Check your connection and try again.') from None


def verify_download(path, release):
    try:
        if path.stat().st_size != release['size']:
            raise UpdateError('The update download is incomplete. Download it again.')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            if stream.read(2) != b'MZ':
                raise UpdateError('The update is not a Windows executable.')
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        if digest.hexdigest() != release['sha256']:
            raise UpdateError('The update SHA-256 does not match. The file was discarded; download it again.')
    except OSError:
        raise UpdateError('Cannot read the update file. Download it again.') from None


def download_release(release, destination, progress=None, cancel_event=None):
    import requests
    def check_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise UpdateError('Update download cancelled.')
    check_cancelled()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.part')
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(release['url'], stream=True, timeout=(6, 8)) as response:
                if response.status_code != 200:
                    raise UpdateError('GitHub could not download the update. Try again later.')
                count = 0
                with temporary.open('wb') as stream:
                    for chunk in response.iter_content(256 * 1024):
                        check_cancelled()
                        if not chunk:
                            continue
                        count += len(chunk)
                        if count > release['size']:
                            raise UpdateError('The update size does not match the release. Download cancelled.')
                        stream.write(chunk)
                        if progress:
                            progress(count)
        check_cancelled()
        verify_download(temporary, release)
        os.replace(temporary, destination)
    except (requests.exceptions.RequestException, OSError):
        raise UpdateError('Cannot download the update. Check your connection and free disk space.') from None
    finally:
        temporary.unlink(missing_ok=True)


def supports_install():
    return (sys.platform == 'win32' and bool(getattr(sys, 'frozen', False))
            and Path(getattr(sys, '_MEIPASS', '')).name.startswith('_MEI'))


class UpdateManager:
    def __init__(self):
        self.config = read_update_config()
        self.release = None
        self.status = 'idle' if self.config['repository'] else 'unconfigured'
        self.error = ''
        self.last_checked = 0
        self.downloaded = 0
        self.path = None
        self.installing = False
        self._check_task = None
        self._download_task = None
        self._cancel_download = threading.Event()
        self._restore_check()

    @property
    def root(self):
        return application_home() / 'updates'

    def _restore_check(self):
        if not self.config['repository']:
            return
        try:
            data = json.loads((self.root / 'last-check.json').read_text(encoding='utf-8'))
            if data.get('repository') == self.config['repository'] and data.get('current_version') == __version__:
                self.last_checked = min(float(data['checked']), time.time())
                self.release = select_release(data['release'], self.config['repository'], __version__) if data.get('release') else None
                self.status = 'available' if self.release else 'current'
        except (OSError, ValueError, TypeError, KeyError, UpdateError):
            pass

    def snapshot(self):
        result = {'configured': bool(self.config['repository']), 'repository': self.config['repository'],
                  'current_version': __version__, 'status': self.status, 'release': self.release,
                  'error': self.error, 'last_checked': self.last_checked, 'downloaded': self.downloaded,
                  'can_install': supports_install()}
        try:
            result['install_result'] = json.loads((self.root / 'result.json').read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            result['install_result'] = None
        return result

    async def check(self, automatic=False):
        if not self.config['repository']:
            self.status = 'unconfigured'
            return self.snapshot()
        if self.status in ('downloading', 'ready', 'installing'):
            return self.snapshot()
        if automatic and self.last_checked and time.time() - self.last_checked < CHECK_INTERVAL:
            return self.snapshot()
        if self._check_task is None or self._check_task.done():
            self._check_task = asyncio.create_task(self._check())
        return await asyncio.shield(self._check_task)

    async def update_on_startup(self, closing, progress):
        """Finish updating before the workspace starts; return True when exiting."""
        if not supports_install() or not self.config['repository'] or closing.is_set():
            return False
        self._cancel_download = closing
        try:
            progress('Проверяем обновления…')
            # A launch always checks GitHub, regardless of the background check cache.
            await self.check()
            if closing.is_set() or self.status != 'available':
                return False
            previous = self.snapshot().get('install_result') or {}
            if not isinstance(previous, dict):
                previous = {}
            if previous.get('ok') is False and previous.get('version') == self.release['version']:
                progress('Предыдущее обновление не установилось. Запускаем сохранённую версию…')
                return False
            progress('Скачиваем обновление ' + self.release['version'] + '…')
            self.start_download()
            while self._download_task and not self._download_task.done():
                await asyncio.sleep(0.15)
                if not closing.is_set() and self.release['size']:
                    percent = min(100, self.downloaded * 100 // self.release['size'])
                    progress(f'Скачиваем обновление {self.release["version"]}: {percent}%')
            if self._download_task:
                await self._download_task
            if closing.is_set() or self.status != 'ready':
                return False
            progress('Устанавливаем обновление. XAnty сейчас перезапустится…')
            await self.install()
            return True
        except (UpdateError, OSError):
            # Offline or failed downloads must never lock the user out of the app.
            return False

    async def _check(self):
        self.status, self.error = 'checking', ''
        try:
            self.release = await asyncio.to_thread(fetch_release, self.config['repository'], __version__)
            self.last_checked = time.time()
            self.status = 'available' if self.release else 'current'
            # Cache trusted GitHub metadata in the original release format for revalidation.
            data = {'repository': self.config['repository'], 'current_version': __version__, 'checked': self.last_checked,
                    'release': None}
            if self.release:
                r = self.release
                data['release'] = {'tag_name': r['tag'], 'body': r['notes'], 'assets': [{
                    'name': 'XAnty.exe', 'browser_download_url': r['url'], 'digest': 'sha256:' + r['sha256'], 'size': r['size']}]}
            try:
                self.root.mkdir(parents=True, exist_ok=True)
                temp = self.root / 'last-check.tmp'
                temp.write_text(json.dumps(data), encoding='utf-8')
                os.replace(temp, self.root / 'last-check.json')
            except OSError:
                pass  # A read-only cache must not prevent checking the release.
        except UpdateError as exc:
            self.status, self.error = 'error', str(exc)
        return self.snapshot()

    def start_download(self):
        if self._check_task is not None and not self._check_task.done():
            raise UpdateError('Wait for the update check to finish before downloading.')
        if not self.release:
            raise UpdateError('Check for a new version before downloading.')
        if not supports_install():
            raise UpdateError('Automatic installation requires the Windows onefile build. Download the release manually.')
        if self.status not in ('downloading', 'ready', 'installing'):
            self._cancel_download.clear()
            self.status, self.error, self.downloaded = 'downloading', '', 0
            self._download_task = asyncio.create_task(self._download())
        return self.snapshot()

    async def _download(self):
        release = dict(self.release)
        self.path = self.root / ('XAnty-' + release['version'] + '.exe')
        try:
            await asyncio.to_thread(download_release, release, self.path,
                                    lambda count: setattr(self, 'downloaded', count), self._cancel_download)
            self.status = 'ready'
        except (UpdateError, OSError) as exc:
            self.status, self.error = 'error', str(exc)

    async def shutdown(self):
        self._cancel_download.set()
        tasks = [task for task in (self._check_task, self._download_task) if task and not task.done()]
        if tasks:
            try:
                await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=24)
            except asyncio.TimeoutError:
                pass

    async def install(self):
        if self.installing:
            raise UpdateError('The update is already being installed.')
        if self.status != 'ready' or not self.path or not supports_install():
            raise UpdateError('Download and verify the update before installing.')
        self.installing, self.status, self.error = True, 'installing', ''
        try:
            await asyncio.to_thread(self._launch_helper)
        except (OSError, UpdateError) as exc:
            self.installing, self.status, self.error = False, 'error', str(exc)
            raise UpdateError('Cannot prepare the update. Check write access to the application folder.') from None
        return self.snapshot()

    def _launch_helper(self):
        verify_download(self.path, self.release)
        target = Path(sys.executable).resolve()
        probe = target.parent / ('.xanty-write-' + uuid.uuid4().hex)
        try:
            probe.touch(exist_ok=False)
        finally:
            probe.unlink(missing_ok=True)
        helper = self.root / ('install-' + uuid.uuid4().hex + '.ps1')
        shutil.copyfile(Path(__file__).with_name('update_helper.ps1'), helper)
        manifest = helper.with_suffix('.json')
        manifest.write_text(json.dumps({'pid': os.getpid(), 'target': str(target), 'source': str(self.path.resolve()),
                                        'sha256': self.release['sha256'], 'version': self.release['version'],
                                        'health': str(helper.with_suffix('.health.json')),
                                        'result': str((self.root / 'result.json').resolve())}), encoding='utf-8')
        powershell = Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        subprocess.Popen([str(powershell), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
                          '-File', str(helper), '-Manifest', str(manifest)],
                         creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
