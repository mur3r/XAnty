"""Stamp each main-branch build with a version newer than the published release."""
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xgenius import __version__
from xgenius.release_notes import archive_releases
from xgenius.updates import UpdateError, version_tuple


def next_version(source, latest=None):
    source_parts = version_tuple(source)
    if latest and version_tuple(latest) >= source_parts:
        parts = list(version_tuple(latest))
        parts[-1] += 1
        return '.'.join(map(str, parts))
    return source.lstrip('v')


def prepare():
    import requests
    repository = os.environ['GITHUB_REPOSITORY']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        raise RuntimeError('Invalid repository.')
    with requests.Session() as session:
        session.trust_env = False
        session.headers.update({'Accept': 'application/vnd.github+json', 'User-Agent': 'XAnty-release'})
        token = os.environ.get('GH_TOKEN')
        if token:
            session.headers['Authorization'] = 'Bearer ' + token
        response = session.get(f'https://api.github.com/repos/{repository}/releases/latest', timeout=(10, 30))
        if response.status_code == 404:
            latest = None
        else:
            response.raise_for_status()
            release = response.json()
            latest = release['tag_name']
            # Recover a release published with GitHub's temporary draft tag.
            if latest.startswith('untagged-') and release.get('name', '').startswith('XAnty '):
                intended = release['name'][len('XAnty '):]
                version_tuple(intended)
                names = {asset['name'] for asset in release.get('assets', [])}
                if not {'XAnty.exe', 'XAnty-Setup.exe'}.issubset(names):
                    raise UpdateError('The previous release is incomplete.')
                repaired = session.patch(f'https://api.github.com/repos/{repository}/releases/{release["id"]}',
                    json={'tag_name': 'v' + intended, 'target_commitish': release['target_commitish'],
                          'draft': False, 'make_latest': 'true'}, timeout=(10, 30))
                repaired.raise_for_status()
                latest = repaired.json()['tag_name']
                if latest != 'v' + intended:
                    raise UpdateError('The previous release tag could not be restored.')
        published = []
        page = 1
        while True:
            response = session.get(f'https://api.github.com/repos/{repository}/releases',
                                   params={'per_page': 100, 'page': page}, timeout=(10, 30))
            response.raise_for_status()
            batch = response.json()
            if not isinstance(batch, list):
                raise RuntimeError('Cannot read published release history.')
            published.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        (ROOT / 'xgenius/web/static/release-history.json').write_text(
            json.dumps(archive_releases(published), ensure_ascii=False, indent=2), encoding='utf-8', newline='\n')
    version = next_version(__version__, latest)
    path = ROOT / 'xgenius/__init__.py'
    stamped, count = re.subn(r'^__version__ = "[^\"]+"', '__version__ = "' + version + '"', path.read_text(encoding='utf-8'), flags=re.M)
    if count != 1:
        raise RuntimeError('Cannot stamp the application version.')
    path.write_text(stamped, encoding='utf-8', newline='\n')
    (ROOT / 'xgenius/update_config.json').write_text(json.dumps({'repository': repository, 'asset': 'XAnty.exe'}), encoding='utf-8')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
        output.write(f'version={version}\ntag=v{version}\n')
    print('Release version:', version)


if __name__ == '__main__':
    prepare()
