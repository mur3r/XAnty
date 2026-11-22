"""Verified local profile backups with workspace-scoped retention."""
from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from pathlib import Path

from xgenius.profile_archive import ArchiveError, export_package, inspect_package
from xgenius.profile_leases import ProfileInUseError, ProfileLease, profile_directory

_DEFAULTS = {'enabled': False, 'directory': '', 'interval_hours': 24, 'keep': 7}
_PROFILE_NAME = re.compile(r'^[A-Za-z0-9_]{1,32}$')


class BackupError(ValueError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def _assert_unlinked(path: Path) -> None:
    for item in (path, *path.parents):
        if os.path.lexists(item) and _linked(item):
            raise BackupError('Backup paths cannot contain symbolic links or junctions')


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _check_cancelled(cancelled) -> None:
    if cancelled and cancelled():
        raise BackupError('Backup cancelled')


class BackupManager:
    """Synchronous worker; the application schedules due() while it is running.

    A manual run is allowed while automatic backups are disabled, provided the
    user has explicitly selected a destination. Every supplied account and every
    existing browser profile is leased before the first export read.
    """

    def __init__(self, config):
        self.config = config
        self._mutex = threading.RLock()
        self._job_lock = threading.Lock()
        self._running = False
        self._settings_path = config.base_dir / '.xanty-backup.json'
        self._lock_path = config.base_dir / '.xanty-backup.lock'
        workspace = os.path.normcase(str(config.base_dir.resolve())).casefold()
        self._workspace_key = hashlib.sha256(workspace.encode('utf-8')).hexdigest()[:20]
        self._file_pattern = re.compile(r'^xanty-' + self._workspace_key + r'-[0-9]{8}T[0-9]{12}Z-[0-9a-f]{12}\.xanty$')

    def _read_document(self) -> dict:
        _assert_unlinked(self._settings_path)
        if not self._settings_path.exists():
            return {'settings': dict(_DEFAULTS), 'state': {}}
        try:
            document = json.loads(self._settings_path.read_text(encoding='utf-8'))
            if not isinstance(document, dict) or not isinstance(document.get('settings'), dict) or not isinstance(document.get('state'), dict):
                raise ValueError()
            settings = {**_DEFAULTS, **document['settings']}
            if (set(settings) != set(_DEFAULTS) or type(settings['enabled']) is not bool or
                    not isinstance(settings['directory'], str) or
                    type(settings['interval_hours']) is not int or not 1 <= settings['interval_hours'] <= 8760 or
                    type(settings['keep']) is not int or not 1 <= settings['keep'] <= 365):
                raise ValueError()
            return {'settings': settings, 'state': document['state']}
        except (OSError, ValueError, TypeError):
            raise BackupError('Could not read local backup settings') from None

    def _write_document(self, document: dict) -> None:
        temporary = None
        try:
            _assert_unlinked(self._settings_path)
            self.config.base_dir.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', prefix='.xanty-backup-', suffix='.tmp',
                                             dir=self.config.base_dir, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(document, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
            _assert_unlinked(self._settings_path)
            os.replace(temporary, self._settings_path)
        except OSError:
            raise BackupError('Could not save local backup settings or status') from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def _directory(self, value: str) -> Path:
        if (not isinstance(value, str) or not value.strip() or
                value.replace('/', '\\').startswith('\\\\') or '\x00' in value):
            raise BackupError('Choose a local backup directory; network locations are not supported')
        path = Path(value)
        if not path.is_absolute():
            raise BackupError('Choose an absolute local backup directory')
        _assert_unlinked(path)
        if os.name == 'nt' and ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) not in (2, 3, 6):
            raise BackupError('Choose a local backup drive; network locations are not supported')
        path = path.resolve()
        for root in (self.config.browser_profiles_dir, self.config.base_dir / 'kook'):
            _assert_unlinked(root)
            if _inside(path, root.resolve()):
                raise BackupError('Backup destination cannot be inside a profile or session directory')
        if path.exists() and not path.is_dir():
            raise BackupError('Choose a backup directory')
        return path

    def settings(self) -> dict:
        with self._mutex:
            return copy.deepcopy(self._read_document()['settings'])

    def _acquire_job(self):
        if not self._job_lock.acquire(blocking=False):
            raise BackupError('A backup job is already running')
        try:
            _assert_unlinked(self._lock_path)
            return ProfileLease._acquire_file(self._lock_path)
        except ProfileInUseError:
            self._job_lock.release()
            raise BackupError('A backup job is already running') from None
        except BaseException:
            self._job_lock.release()
            raise

    def configure(self, data) -> dict:
        if not isinstance(data, dict) or set(data) - set(_DEFAULTS):
            raise BackupError('Invalid local backup settings')
        lease = self._acquire_job()
        try:
            with self._mutex:
                document = self._read_document()
                settings = {**document['settings'], **data}
                if (type(settings['enabled']) is not bool or type(settings['interval_hours']) is not int or
                        not 1 <= settings['interval_hours'] <= 8760 or type(settings['keep']) is not int or
                        not 1 <= settings['keep'] <= 365 or not isinstance(settings['directory'], str)):
                    raise BackupError('Use a boolean enabled setting, 1–8760 interval hours and 1–365 retained backups')
                if settings['directory']:
                    settings['directory'] = str(self._directory(settings['directory']))
                elif settings['enabled']:
                    raise BackupError('Choose a local backup directory before enabling automatic backups')
                document['settings'] = settings
                self._write_document(document)
                return copy.deepcopy(settings)
        finally:
            lease.release()
            self._job_lock.release()

    def _record(self, **values) -> None:
        with self._mutex:
            document = self._read_document()
            document['state'].update(values)
            self._write_document(document)

    def snapshot(self) -> dict:
        with self._mutex:
            document = self._read_document()
            state = document['state']
            last_success = state.get('last_success_at')
            next_due = None
            if last_success:
                try:
                    next_due = (datetime.fromisoformat(last_success) + timedelta(
                        hours=document['settings']['interval_hours'])).isoformat()
                except (ValueError, TypeError):
                    pass
            return {**document['settings'], 'running': self._running,
                    'last_status': state.get('last_status', 'never'),
                    'last_result': copy.deepcopy(state.get('last_result')),
                    'last_attempt_at': state.get('last_attempt_at'),
                    'last_success_at': last_success, 'next_due_at': next_due}

    def due(self, now=None) -> bool:
        status = self.snapshot()
        if not status['enabled'] or not status['directory'] or status['running']:
            return False
        if not status['last_success_at']:
            return True
        moment = _now() if now is None else (datetime.fromtimestamp(now, timezone.utc) if isinstance(now, (int, float)) else now)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        try:
            success = datetime.fromisoformat(status['last_success_at'])
            return moment >= success + timedelta(hours=status['interval_hours'])
        except (ValueError, TypeError):
            return True

    def _backup_directory(self, directory: Path) -> Path:
        target = directory / ('XAnty-backups-' + self._workspace_key)
        _assert_unlinked(target)
        target.mkdir(parents=True, exist_ok=True)
        _assert_unlinked(target)
        owner = target / '.xanty-owner.json'
        identity = {'format': 'xanty-local-backups', 'version': 1, 'workspace': self._workspace_key}
        _assert_unlinked(owner)
        if not owner.exists():
            if any(target.iterdir()):
                raise BackupError('The dedicated backup directory contains unrecognized files')
            with owner.open('x', encoding='utf-8') as stream:
                json.dump(identity, stream)
                stream.flush()
                os.fsync(stream.fileno())
        try:
            if json.loads(owner.read_text(encoding='utf-8')) != identity:
                raise ValueError()
        except (OSError, ValueError, TypeError):
            raise BackupError('The dedicated backup directory belongs to a different workspace') from None
        return target

    def _validate_source(self, root: Path, cancelled=None) -> None:
        _assert_unlinked(root)
        if not root.exists():
            return
        for directory, folders, files in os.walk(root, followlinks=False):
            _check_cancelled(cancelled)
            for name in folders + files:
                _assert_unlinked(Path(directory) / name)

    def _retain(self, directory: Path, keep: int, current: Path) -> list[str]:
        try:
            _assert_unlinked(directory)
            candidates = sorted((path for path in directory.iterdir() if self._file_pattern.fullmatch(path.name)
                                 and not _linked(path) and path.is_file()), key=lambda path: path.name, reverse=True)
            # Keep the just-published archive even if the system clock moved
            # backwards and its timestamp sorts before older backup names.
            previous = [path for path in candidates if path != current]
            for path in previous[keep - 1:]:
                _assert_unlinked(path)
                if path.parent != directory:
                    raise BackupError('Unsafe backup retention path')
                path.unlink()
        except (OSError, BackupError):
            return ['The backup was saved, but older backup copies could not all be removed']
        return []

    def run(self, accounts, folders=None, progress=None, cancelled=None) -> dict:
        lease = self._acquire_job()
        self._running = True
        temporary = None
        try:
            settings = self.settings()
            if not settings['directory']:
                raise BackupError('Choose a local backup directory before creating a backup')
            if not isinstance(accounts, list) or not accounts:
                raise BackupError('No profiles to back up')
            accounts = copy.deepcopy(accounts)
            if any(not isinstance(a, dict) or not _PROFILE_NAME.fullmatch(str(a.get('username', ''))) for a in accounts):
                raise BackupError('Invalid profile list for backup')
            names = {a['username'] for a in accounts}
            _assert_unlinked(self.config.browser_profiles_dir)
            for profile in self.config.browser_profiles_dir.glob('profile_*'):
                _assert_unlinked(profile)
                name = profile.name.removeprefix('profile_')
                if _PROFILE_NAME.fullmatch(name):
                    names.add(name)
            self._record(last_status='running', last_attempt_at=_now().isoformat())
            _check_cancelled(cancelled)
            directory = self._directory(settings['directory'])
            with ExitStack() as profiles:
                for name in sorted(names, key=str.casefold):
                    _check_cancelled(cancelled)
                    profiles.enter_context(ProfileLease.acquire_path(profile_directory(self.config, name), create_profile=False))
                for name in names:
                    self._validate_source(profile_directory(self.config, name), cancelled)
                    self._validate_source(self.config.base_dir / 'kook' / ('@' + name), cancelled)
                target = self._backup_directory(directory)
                with tempfile.NamedTemporaryFile(prefix='.xanty-', suffix='.partial', dir=target, delete=False) as stream:
                    temporary = Path(stream.name)
                result = export_package(self.config, accounts, temporary, progress=progress, cancelled=cancelled, folders=folders)
                verified = inspect_package(temporary)
                if verified['integrity'] != 'verified':
                    raise BackupError('The backup failed its SHA-256 integrity check')
                with temporary.open('rb+') as stream:
                    os.fsync(stream.fileno())
                _check_cancelled(cancelled)
                _assert_unlinked(target)
                stamp = _now()
                final = target / ('xanty-' + self._workspace_key + '-' + stamp.strftime('%Y%m%dT%H%M%S%fZ') + '-' + uuid.uuid4().hex[:12] + '.xanty')
                if final.exists():
                    raise BackupError('Could not reserve a unique backup filename')
                os.replace(temporary, final)
                temporary = None
            result.update(status='completed', filename=final.name, path=str(final), created_at=stamp.isoformat())
            self._record(last_status='completed', last_success_at=stamp.isoformat(), last_result=result)
            # A failed status commit must preserve every previous copy. Pruning
            # starts only once the new verified archive and its status are saved.
            retention_warnings = self._retain(target, settings['keep'], final)
            if retention_warnings:
                result['warnings'].extend(retention_warnings)
                try:
                    self._record(last_result=result)
                except BackupError:
                    pass
            return result
        except Exception as exc:
            if isinstance(exc, ProfileInUseError):
                status, message = 'postponed', 'Close all profiles before creating a backup; a profile is still in use'
            elif isinstance(exc, (BackupError, ArchiveError)) and 'cancelled' in str(exc).lower():
                status, message = 'cancelled', 'Backup cancelled'
            else:
                status, message = 'failed', (str(exc) if isinstance(exc, BackupError) else
                                              'Could not create and verify the local backup; previous backups were preserved')
            try:
                self._record(last_status=status, last_attempt_at=_now().isoformat(), last_result={'status': status, 'message': message})
            except (BackupError, OSError):
                pass
            raise BackupError(message) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
            self._running = False
            try:
                lease.release()
            finally:
                self._job_lock.release()
