"""Publish an audited source snapshot to a new private GitHub repository.

Uses an existing Git Credential Manager login. Never uploads the working folder
recursively, local account files, browser profiles, archives, or Git history.
Run with --check for an entirely local check without uploading anything.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
TOP_FILES = {
    '.gitignore', 'ANALYSIS.md', 'README.md', 'main.py',
    'requirements.txt', 'requirements-build.txt',
}
SOURCE_DIRS = {'.github', 'docs', 'tests', 'tools', 'xgenius'}
BINARY_FILES = {
    'xgenius/web/static/assets/app-icon.png',
    'xgenius/web/static/assets/app.ico',
}
PRIVATE_PATH = re.compile(
    r'(?i)(?:^|/)(?:accounts[^/]*\.json|folders[^/]*\.json|'
    r'[^/]*cookies[^/]*\.json|paths[^/]*\.json|preferences\.json|'
    r'\.env(?:\.[^/]*)?|browser_profiles|kook|bro|drivers|logs|'
    r'output|tmp|\.venv|softtwitter|webui_profile)(?:$|/)|'
    r'\.(?:zip|7z|rar|xanty|db|sqlite3?|log|har|pem|key|pfx|p12)$'
)
SECRET_PATTERN = re.compile(
    rb'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----|'
    rb'(?:gh[pousr]_[A-Za-z0-9]{30,255}|github_pat_[A-Za-z0-9_]{30,255})|'
    rb'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b|'
    rb'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}'
)


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT)


def account_secrets():
    found = set()

    def visit(value, key='', in_cookies=False):
        if isinstance(value, dict):
            for child_key, item in value.items():
                visit(item, str(child_key).lower(), in_cookies or 'cookie' in key)
        elif isinstance(value, list):
            for item in value:
                visit(item, key, in_cookies or 'cookie' in key)
        elif isinstance(value, str) and len(value) >= 5:
            sensitive = any(word in key for word in ('username', 'password', 'token', 'proxy', 'email'))
            sensitive = sensitive or key in {'login', 'ct0'} or (in_cookies and key == 'value')
            if sensitive:
                found.add(value.encode('utf-8'))

    account_file = ROOT / 'accounts.json'
    if account_file.exists():
        visit(json.loads(account_file.read_text(encoding='utf-8-sig')))
    return found


def source_snapshot():
    names = sorted(set(p.decode('utf-8') for p in
                       git('ls-files', '--cached', '--others', '--exclude-standard', '-z').split(b'\0') if p))
    secrets = account_secrets()
    snapshot = {}
    for name in names:
        if name not in TOP_FILES and name != 'config/settings.example.json' and name.split('/')[0] not in SOURCE_DIRS:
            raise RuntimeError('Unexpected file in source list: ' + name)
        if PRIVATE_PATH.search(name) or name == 'config/settings.json':
            raise RuntimeError('Private file in source list: ' + name)
        path = ROOT / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise RuntimeError('Refusing a missing file or a link: ' + name)
        data = path.read_bytes()
        if len(data) > 5_000_000:
            raise RuntimeError('File needs manual review because of its size: ' + name)
        if any(secret in data for secret in secrets) or SECRET_PATTERN.search(data):
            raise RuntimeError('Possible credential found in: ' + name)
        if name not in BINARY_FILES:
            try:
                data.decode('utf-8')
            except UnicodeDecodeError:
                raise RuntimeError('Unreviewed binary file: ' + name) from None
        snapshot[name] = data
    if not snapshot:
        raise RuntimeError('Source snapshot is empty.')
    print(f'Checked {len(snapshot)} source files; private data excluded.', flush=True)
    return snapshot


class GitHub:
    def __init__(self, username):
        prompt = 'protocol=https\nhost=github.com\n'
        if username:
            prompt += 'username=' + username + '\n'
        result = subprocess.run(
            ['git', 'credential-manager', 'get'], input=(prompt + '\n').encode(),
            capture_output=True, cwd=ROOT, timeout=45,
            env=dict(os.environ, GCM_INTERACTIVE='never', GIT_TERMINAL_PROMPT='0'),
        )
        credential = dict(line.split('=', 1) for line in
                          result.stdout.decode('utf-8').splitlines() if '=' in line)
        self.token = credential.get('password', '')
        if result.returncode or not self.token:
            raise RuntimeError('No usable GitHub login in Git Credential Manager.')

    def api(self, method, path, payload=None, missing_ok=False):
        body = None if payload is None else json.dumps(payload).encode('utf-8')
        request = Request('https://api.github.com' + path, data=body, method=method, headers={
            'Authorization': 'Bearer ' + self.token,
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'XAnty-source-publisher',
        })
        try:
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as exc:
            if missing_ok and exc.code == 404:
                return None
            raise RuntimeError(f'GitHub returned HTTP {exc.code} for {method} {path}.') from None
        except URLError:
            raise RuntimeError('Cannot connect to GitHub. Check the network connection.') from None


def publish(snapshot, username, name):
    api = GitHub(username)
    owner = api.api('GET', '/user')['login']
    repo_path = '/repos/' + owner + '/' + name
    if api.api('GET', repo_path, missing_ok=True) is not None:
        raise RuntimeError('Repository already exists. Choose a new name with --name; existing repositories are preserved.')
    repo = api.api('POST', '/user/repos', {
        'name': name, 'description': 'XAnty browser profile manager source code',
        'private': True, 'auto_init': True,
    })
    if repo.get('private') is not True:
        raise RuntimeError('Repository privacy could not be verified. No source files uploaded.')
    branch = repo['default_branch']
    head = api.api('GET', repo_path + '/git/ref/heads/' + branch)['object']['sha']
    base = api.api('GET', repo_path + '/git/commits/' + head)['tree']['sha']
    entries = []
    for path, data in snapshot.items():
        entry = {'path': path, 'mode': '100644', 'type': 'blob'}
        if path in BINARY_FILES:
            entry['sha'] = api.api('POST', repo_path + '/git/blobs', {
                'content': base64.b64encode(data).decode('ascii'), 'encoding': 'base64',
            })['sha']
        else:
            entry['content'] = data.decode('utf-8')
        entries.append(entry)
    tree = api.api('POST', repo_path + '/git/trees', {'base_tree': base, 'tree': entries})['sha']
    commit = api.api('POST', repo_path + '/git/commits', {
        'message': 'Publish audited XAnty source without local account data',
        'tree': tree, 'parents': [head],
    })['sha']
    api.api('PATCH', repo_path + '/git/refs/heads/' + branch, {'sha': commit, 'force': False})
    published = api.api('GET', repo_path + '/git/trees/' + tree + '?recursive=1')
    actual = {entry['path']: entry['sha'] for entry in published.get('tree', []) if entry['type'] == 'blob'}
    expected = {path: hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
                for path, data in snapshot.items()}
    if published.get('truncated') or actual != expected:
        raise RuntimeError('Remote file list could not be verified. Inspect the repository before sharing it.')
    if api.api('GET', repo_path + '/git/ref/heads/' + branch)['object']['sha'] != commit:
        raise RuntimeError('Remote branch does not point to the uploaded source snapshot.')
    if api.api('GET', repo_path).get('private') is not True:
        raise RuntimeError('Remote repository privacy could not be verified.')
    print('Uploaded and verified private repository: ' + repo['html_url'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check sources locally; do not connect or upload.')
    parser.add_argument('--username', default='mur3r', help='Existing Git Credential Manager account.')
    parser.add_argument('--name', default='XAnty', help='Name for the new private repository.')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.-]+', args.name) or args.name in {'.', '..'}:
        raise RuntimeError('Invalid repository name.')
    snapshot = source_snapshot()
    if not args.check:
        publish(snapshot, args.username, args.name)


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print('Upload stopped: ' + str(error), file=sys.stderr)
        sys.exit(1)
