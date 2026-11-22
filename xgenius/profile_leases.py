"""OS-held profile leases shared by independent XAnty processes."""
import os
import hashlib
from pathlib import Path
import psutil


class ProfileInUseError(ValueError):
    pass


def profile_directory(config, username):
    if not username or username in ('.', '..') or any(c in username for c in '/\\:\0'):
        raise ValueError('Invalid profile name')
    root = config.browser_profiles_dir.resolve()
    candidate = root / ('profile_' + username)
    if candidate.is_symlink() or candidate.resolve().parent != root:
        raise ValueError('Invalid profile path')
    return candidate.resolve()


def process_uses_profile(profile):
    expected = os.path.normcase(str(Path(profile).resolve()))
    for process in psutil.process_iter(['name']):
        try:
            if (process.info.get('name') or '').lower() not in ('chrome', 'chrome.exe', 'chromium', 'chromium.exe'):
                continue
            arguments = process.info.get('cmdline') or process.cmdline()
            for i, value in enumerate(arguments):
                if value.startswith('--user-data-dir='):
                    path = value.split('=', 1)[1].strip('"')
                elif value == '--user-data-dir' and i + 1 < len(arguments):
                    path = arguments[i + 1].strip('"')
                else:
                    continue
                if os.path.normcase(str(Path(path).resolve())) == expected:
                    return True
        except (psutil.Error, OSError, ValueError):
            continue
    return False


class ProfileLease:
    def __init__(self, stream):
        self.stream = stream

    @classmethod
    def acquire(cls, config, username, check_processes=True):
        return cls.acquire_path(profile_directory(config, username), check_processes)

    @classmethod
    def acquire_workspace(cls, config):
        config.base_dir.mkdir(parents=True,exist_ok=True)
        try:
            return cls._acquire_file(config.base_dir / '.xanty-workspace.lock')
        except ProfileInUseError:
            raise ProfileInUseError('This workspace is already open in another XAnty instance.') from None

    @classmethod
    def acquire_path(cls, profile, check_processes=True, create_profile=True):
        profile = Path(profile).resolve()
        if create_profile:
            profile.mkdir(parents=True, exist_ok=True)
        lock_root = profile.parent / '.xanty-locks'
        if lock_root.is_symlink() or (lock_root.exists() and getattr(lock_root.lstat(),'st_file_attributes',0) & 0x400):
            raise ValueError('Unsafe profile lock directory')
        lock_root.mkdir(exist_ok=True)
        key = hashlib.sha256(str(profile).casefold().rstrip(' .').encode('utf-8')).hexdigest()
        lock_path = lock_root / (key + '.lock')
        lease = cls._acquire_file(lock_path)
        if check_processes and process_uses_profile(profile):
            lease.release()
            raise ProfileInUseError('Profile is already open in another session. Close it before continuing.')
        return lease

    @classmethod
    def _acquire_file(cls,lock_path):
        if lock_path.is_symlink() or (lock_path.exists() and getattr(lock_path.lstat(),'st_file_attributes',0) & 0x400):
            raise ValueError('Unsafe profile lock path')
        stream = lock_path.open('a+b')
        try:
            if stream.seek(0, 2) == 0:
                stream.write(b'0'); stream.flush()
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            lease = cls(stream)
            return lease
        except (OSError, BlockingIOError):
            stream.close()
            raise ProfileInUseError('Profile is already open in another session. Close it before continuing.') from None
        except BaseException:
            stream.close()
            raise

    def release(self):
        if self.stream.closed:
            return
        try:
            self.stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        finally:
            self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.release()
