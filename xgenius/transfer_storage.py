"""Validate a user-selected export folder and publish a finished package atomically."""
import os
from pathlib import Path


def export_directory(value):
    if value in (None, ''):
        return None
    if not isinstance(value, str) or len(value) > 4096 or any(ord(char) < 32 for char in value):
        raise ValueError('Choose an existing folder for the profile package')
    path = Path(value.strip()).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError('Choose an existing absolute folder for the profile package')
    return path.resolve()


def publish_export(staged, destination, cancelled=None):
    from xgenius.profile_archive import ArchiveError, inspect_package
    staged, destination = Path(staged), Path(destination)
    inspect_package(staged, cancelled=cancelled)
    if cancelled and cancelled():
        raise ArchiveError('Operation cancelled')
    if os.name == 'nt':
        os.rename(staged, destination)  # Windows refuses to replace an existing file.
    else:
        os.link(staged, destination)  # Atomic no-overwrite publication on POSIX.
        staged.unlink()
    return str(destination)
