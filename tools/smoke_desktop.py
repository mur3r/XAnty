"""Launch only an isolated test EXE; verify startup/update and preserved test data."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

import psutil


def check(executable, version, expected_sha256=None, timeout=180):
    executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix='xanty-smoke-') as directory:
        root = Path(directory)
        local = root / 'appdata'
        home = local / 'XAnty'
        workspace = root / 'workspace'
        home.mkdir(parents=True)
        workspace.mkdir()
        sentinel = workspace / 'test-data.txt'
        sentinel.write_text('preserve this synthetic profile data', encoding='utf-8')
        (home / 'paths.json').write_text(json.dumps({'base_dir': str(workspace)}), encoding='utf-8')
        health = root / 'ready.json'
        env = dict(os.environ, LOCALAPPDATA=str(local), XANTY_UPDATE_HEALTH_FILE=str(health), PYINSTALLER_RESET_ENVIRONMENT='1')
        # All state and browser profiles belong to the temporary synthetic workspace.
        process = subprocess.Popen([str(executable)], cwd=executable.parent, env=env,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = time.monotonic() + timeout
            status_file = home / 'updates/result.json' if expected_sha256 else health
            result = None
            while time.monotonic() < deadline:
                try:
                    result = json.loads(status_file.read_text(encoding='utf-8-sig'))
                except (OSError, ValueError):
                    time.sleep(0.25)
                    continue
                if result.get('version') == version:
                    if expected_sha256 and result.get('ok') is not True:
                        raise RuntimeError('Live update failed: ' + str(result))
                    break
                time.sleep(0.25)
            else:
                log = home / 'startup.log'
                raise RuntimeError('Desktop probe timed out: ' + (log.read_text(encoding='utf-8') if log.exists() else str(result)))
            if expected_sha256 and hashlib.sha256(executable.read_bytes()).hexdigest() != expected_sha256:
                raise RuntimeError('The running update does not match the release EXE.')
            if sentinel.read_text(encoding='utf-8') != 'preserve this synthetic profile data':
                raise RuntimeError('Profile data changed during startup/update.')
            print('Verified desktop startup' + (' and live automatic update' if expected_sha256 else '') + ': ' + version)
        finally:
            # Match the exact isolated executable; never stop other XAnty/browser processes.
            owned = []
            for candidate in psutil.process_iter(['exe']):
                try:
                    if candidate.info['exe'] and Path(candidate.info['exe']).resolve() == executable:
                        candidate.terminate()
                        owned.append(candidate)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            psutil.wait_procs(owned, timeout=15)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--sha256')
    args = parser.parse_args()
    check(args.exe, args.version, args.sha256)
