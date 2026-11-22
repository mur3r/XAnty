"""Build a per-user installer from the EXE and official browser prerequisites."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from xgenius import __version__
from xgenius.chromium_versions import ChromiumVersionManager

WEBVIEW_URL = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703'


def compiler_path(explicit=None):
    candidates = [explicit, shutil.which('ISCC.exe')]
    for variable in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA'):
        root = os.environ.get(variable)
        if root:
            candidates.extend(str(Path(root) / folder / 'ISCC.exe')
                              for folder in ('Inno Setup 6', 'Inno Setup 7', 'Programs/Inno Setup 6'))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate).resolve()
    raise RuntimeError('Install Inno Setup 6/7 or pass --compiler with the ISCC.exe path.')


def webview_bootstrapper(destination):
    import requests
    destination.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(WEBVIEW_URL, stream=True, timeout=(10, 30)) as response:
        response.raise_for_status()
        total = 0
        with destination.open('wb') as stream:
            for chunk in response.iter_content(256 * 1024):
                total += len(chunk)
                if total > 8 * 1024 * 1024:
                    raise RuntimeError('Unexpected WebView2 bootstrapper size.')
                stream.write(chunk)
    quoted = "'" + str(destination).replace("'", "''") + "'"
    script = ("$s=Get-AuthenticodeSignature -LiteralPath " + quoted + "; "
              "if ($s.Status -ne 'Valid' -or $s.SignerCertificate.Subject -notlike '*O=Microsoft Corporation*') "
              "{ throw 'WebView2 bootstrapper signature verification failed' }")
    shell = shutil.which('pwsh.exe') or 'powershell.exe'
    environment = dict(os.environ)
    environment.pop('PSModulePath', None)
    subprocess.run([shell, '-NoProfile', '-NonInteractive', '-Command', script], check=True, env=environment)
    return destination


def build(executable, output_dir, compiler=None, browser_version='Stable'):
    if sys.platform != 'win32':
        raise RuntimeError('Build the installer on Windows.')
    executable, output_dir = Path(executable).resolve(), Path(output_dir).resolve()
    if not executable.is_file():
        raise RuntimeError('Build the onefile XAnty.exe first.')
    output_dir.mkdir(parents=True, exist_ok=True)
    staging = output_dir / 'installer-inputs'
    staging.mkdir(exist_ok=True)
    manager = ChromiumVersionManager(SimpleNamespace(base_dir=staging / 'official-browser'))
    pair = manager.install(browser_version)
    bootstrapper = webview_bootstrapper(staging / 'MicrosoftEdgeWebview2Setup.exe')
    command = [str(compiler_path(compiler)), '/Qp', '/DAppVersion=' + __version__,
               '/DAppExe=' + str(executable), '/DChromeDir=' + str(Path(pair['chrome_path']).parent),
               '/DDriverDir=' + str(Path(pair['driver_path']).parent), '/DWebViewSetup=' + str(bootstrapper),
               '/DOutputDir=' + str(output_dir), str(ROOT / 'tools/xanty.iss')]
    subprocess.run(command, cwd=ROOT, check=True)
    return output_dir / 'XAnty-Setup.exe'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, default=ROOT / 'dist/release/XAnty.exe')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'dist/release')
    parser.add_argument('--compiler')
    parser.add_argument('--browser-version', default='Stable')
    args = parser.parse_args()
    print('Installer ready:', build(args.exe, args.output_dir, args.compiler, args.browser_version))
