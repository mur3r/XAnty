"""Publish a complete release by ID, including drafts whose tag is not created yet."""
import hashlib
import os
from pathlib import Path
import re
import sys

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xgenius import __version__
from xgenius.updates import version_tuple


def publish():
    repository, commit = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise RuntimeError('Invalid repository.')
    version_tuple(__version__)
    tag = 'v' + __version__
    notes = (ROOT / 'xgenius/web/static/release-notes.md').read_text(encoding='utf-8').strip()
    if not notes:
        raise RuntimeError('Release notes must describe the published update.')
    release_body = ('Установщик: XAnty-Setup.exe. Отдельный EXE: XAnty.exe.\n\n'
                    'Обновления при запуске устанавливаются автоматически. Профили и настройки сохраняются.\n\n'
                    + notes)
    directory = ROOT / 'dist/release'
    files = [directory / name for name in ('XAnty.exe', 'XAnty-Setup.exe')]
    sums = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in files}
    checksum_file = directory / 'SHA256SUMS.txt'
    checksum_file.write_text(''.join(digest + '  ' + name + '\n' for name, digest in sums.items()), encoding='ascii')
    files.append(checksum_file)
    with requests.Session() as session:
        session.trust_env = False
        session.headers.update({'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                                'Accept': 'application/vnd.github+json',
                                'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'XAnty-release'})
        base = 'https://api.github.com/repos/' + repository
        def api(method, suffix, **kwargs):
            response = session.request(method, base + suffix, timeout=(15, 60), **kwargs)
            response.raise_for_status()
            return response.json() if response.content else None
        if api('GET', '/branches/main')['commit']['sha'] != commit:
            print('Skipping an outdated build; a newer main commit is queued.')
            return
        releases = api('GET', '/releases?per_page=100')
        matches = [release for release in releases if release['tag_name'] == tag]
        if len(matches) > 1 or matches and not matches[0]['draft']:
            raise RuntimeError('This version is already published; use a newer build version.')
        if matches:
            release = matches[0]
            release = api('PATCH', '/releases/' + str(release['id']), json={'tag_name': tag, 'target_commitish': commit, 'draft': True, 'body': release_body})
        else:
            release = api('POST', '/releases', json={'tag_name': tag, 'target_commitish': commit,
                          'name': 'XAnty ' + __version__, 'draft': True,
                          'body': release_body})
        release_id = release['id']
        for asset in release['assets']:
            api('DELETE', '/releases/assets/' + str(asset['id']))
        for path in files:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            with path.open('rb') as stream:
                response = session.post(f'https://uploads.github.com/repos/{repository}/releases/{release_id}/assets',
                                        params={'name': path.name}, data=stream,
                                        headers={'Content-Type': 'application/octet-stream'}, timeout=(15, 300))
            response.raise_for_status()
            asset = response.json()
            if (asset.get('name') != path.name or asset.get('size') != path.stat().st_size
                    or asset.get('digest') != 'sha256:' + digest):
                raise RuntimeError('Release asset verification failed: ' + path.name)
        published = api('PATCH', '/releases/' + str(release_id), json={'tag_name': tag, 'target_commitish': commit,
                        'draft': False, 'make_latest': 'true'})
        if published['draft'] or published['tag_name'] != tag:
            raise RuntimeError('Release publication could not be verified.')
        print('Published verified release:', published['html_url'])


if __name__ == '__main__':
    publish()
