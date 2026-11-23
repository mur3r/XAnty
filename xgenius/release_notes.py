"""Offline release notes and a per-installation acknowledgement."""
import json
import os
import tempfile
from pathlib import Path

from xgenius import __version__
from xgenius.config import application_home


def current_notes():
    return (Path(__file__).parent / 'web' / 'static' / 'release-notes.md').read_text(encoding='utf-8').strip()


class ReleaseNotes:
    def __init__(self, repository):
        self.repository = repository
        try:
            self.notes = current_notes()
        except OSError:
            self.notes = ''

    @property
    def acknowledgement(self):
        return application_home() / 'updates' / 'release-notes-seen.json'

    def snapshot(self):
        try:
            seen = json.loads(self.acknowledgement.read_text(encoding='utf-8')).get('version')
        except (OSError, ValueError, AttributeError):
            seen = None
        return {'version': __version__, 'notes': self.notes, 'pending': seen != __version__,
                'page_url': f'https://github.com/{self.repository}/releases/tag/v{__version__}'
                if self.repository else ''}

    def acknowledge(self, version):
        if version != __version__:
            raise ValueError('Cannot acknowledge notes for a different application version.')
        destination = self.acknowledgement
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=destination.parent,
                                             delete=False) as stream:
                temporary = stream.name
                json.dump({'version': __version__}, stream)
            os.replace(temporary, destination)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

