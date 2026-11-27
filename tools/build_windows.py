"""Build the native, console-free Windows application."""
import argparse
import importlib.util
import os
import subprocess
import sys
from pathlib import Path


def build(onefile: bool = False, dist_dir: Path = None) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("Build XAnty.exe on Windows.")
    required = ("PyInstaller", "webview", "selenium", "selenium_stealth", "aiohttp", "psutil", "requests", "cryptography", "socks")
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        raise RuntimeError("Missing dependencies: " + ", ".join(missing) +
                           ". Run: python -m pip install -r requirements.txt -r requirements-build.txt")

    root = Path(__file__).resolve().parents[1]
    static = root / "xgenius" / "web" / "static"
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--onefile" if onefile else "--onedir", "--windowed", "--name", "XAnty",
               "--add-data", str(static) + os.pathsep + "xgenius/web/static",
               "--add-data", str(root / 'xgenius' / 'update_config.json') + os.pathsep + 'xgenius',
               "--add-data", str(root / 'xgenius' / 'update_helper.ps1') + os.pathsep + 'xgenius',
               "--icon", str(static / "assets" / "app.ico"),
               "--hidden-import", "socks", "--hidden-import", "urllib3.contrib.socks",
               "--collect-data", "selenium_stealth",
               "--collect-submodules", "selenium",
               "--collect-all", "webview", str(root / "main.py")]
    destination = Path(dist_dir).resolve() if dist_dir else root / "dist"
    command.extend(["--distpath", str(destination)])
    subprocess.run(command, cwd=root, check=True)
    if onefile:
        return destination / "XAnty.exe"
    return destination / "XAnty" / "XAnty.exe"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--onefile", action="store_true", help="Package everything in a single XAnty.exe.")
    parser.add_argument("--dist-dir", type=Path, help="Output folder for the new executable.")
    args = parser.parse_args()
    print(f"Build ready: {build(onefile=args.onefile, dist_dir=args.dist_dir)}")
