"""Offline release notes and a per-installation acknowledgement."""
import json
import os
import re
import tempfile
from pathlib import Path

from xgenius import __version__
from xgenius.config import application_home


def current_notes():
    return (Path(__file__).parent / 'web' / 'static' / 'release-notes.md').read_text(encoding='utf-8').strip()


_VERSION = re.compile(r'v?(\d+(?:\.\d+){1,3})')


def archive_releases(releases):
    """Retain published notes; remove older cumulative notes from newer entries."""
    entries, seen = [], set()
    for release in releases:
        match = _VERSION.fullmatch(str(release.get('tag_name', '')))
        if not match or release.get('draft') or release.get('prerelease'):
            continue
        version = match[1]
        if version in seen:
            continue
        seen.add(version)
        notes = str(release.get('body') or '').replace('\r\n', '\n').strip()
        heading = re.search(r'(?m)^#{1,6}\s+', notes)
        if heading:
            notes = notes[heading.start():]
        entries.append({'version': version, 'notes': notes,
                        'published_at': release.get('published_at') or ''})
    entries.sort(key=lambda entry: tuple(map(int, entry['version'].split('.'))), reverse=True)
    original = [entry['notes'] for entry in entries]
    for index, entry in enumerate(entries):
        for older in original[index + 1:]:
            if older and entry['notes'] != older and entry['notes'].endswith(older):
                entry['notes'] = entry['notes'][:-len(older)].strip()
                break
    return entries


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

    def history(self):
        current = {'version': __version__, 'notes': self.notes, 'published_at': ''}
        try:
            archive = json.loads((Path(__file__).parent / 'web' / 'static' / 'release-history.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            archive = []
        entries, seen = [current], {__version__}
        for entry in archive if isinstance(archive, list) else []:
            if (not isinstance(entry, dict) or not isinstance(entry.get('version'), str)
                    or not _VERSION.fullmatch(entry['version']) or not isinstance(entry.get('notes'), str)
                    or entry['version'] in seen):
                continue
            seen.add(entry['version'])
            entries.append({'version': entry['version'], 'notes': entry['notes'],
                            'published_at': str(entry.get('published_at') or '')})
        for entry in entries:
            entry['page_url'] = (f'https://github.com/{self.repository}/releases/tag/v{entry["version"]}'
                                 if self.repository else '')
        return entries

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

