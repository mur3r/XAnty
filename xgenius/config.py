"""
Пути проекта: базовая папка (Bro/chrome.exe, Drivers/chromedriver.exe, данные аккаунтов),
файлы состояния. Базовая папка хранится в paths.json рядом с main.py; выбирается
на экране Setup веб-интерфейса (раньше — диалог tkinter при первом запуске).
"""
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple


class ConfigError(Exception):
    pass


def application_home() -> Path:
    """Writable location for desktop settings, independent of the EXE directory."""
    root = os.environ.get("LOCALAPPDATA")
    return (Path(root) if root else Path.home() / "AppData" / "Local") / "XAnty"


def paths_file() -> Path:
    if getattr(sys, "frozen", False):
        return application_home() / "paths.json"
    return Path.cwd() / "paths.json"


def default_base_dir() -> Path:
    return (application_home() / "data") if getattr(sys, "frozen", False) else (Path.cwd() / "SoftTwitter")


def read_saved_base_dir() -> Optional[Path]:
    candidates = [paths_file()]
    if getattr(sys, "frozen", False):
        candidates.extend([Path(sys.executable).resolve().parent / "paths.json", Path.cwd() / "paths.json"])
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            with candidate.open("r", encoding="utf-8") as fh:
                base = json.load(fh).get("base_dir", "")
            if base:
                return Path(base)
        except (OSError, ValueError, TypeError):
            continue
    return None


def save_base_dir(base_dir: Path) -> None:
    target = paths_file()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as fh:
        json.dump({"base_dir": str(base_dir)}, fh, indent=4)


def get_paths_from_base(base_folder: Path) -> Tuple[Path, Path]:
    chrome_path = base_folder / "Bro" / "chrome.exe"
    chromedriver_path = base_folder / "Drivers" / "chromedriver.exe"
    return chrome_path, chromedriver_path


class Config:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            base_dir = read_saved_base_dir()
        if base_dir is None:
            raise ConfigError("Базовая папка не выбрана (нет paths.json). Откройте экран Setup.")
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.refresh_browser_paths()
        self.browser_profiles_dir = self.base_dir / "browser_profiles"
        self.browser_profiles_dir.mkdir(parents=True, exist_ok=True)
        self.accounts_file = self.base_dir / "accounts.json"
        self.logs_dir = self.base_dir / "logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def refresh_browser_paths(self) -> None:
        """Apply the validated selected pair; retain Bro/Drivers as the default."""
        from xgenius.chromium_versions import ChromiumVersionManager
        self.chrome_path, self.chromedriver_path = ChromiumVersionManager(self).active_paths()

    def get_profile_dir(self, username: str) -> Path:
        profile_dir = self.browser_profiles_dir / f"profile_{username}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        return profile_dir
