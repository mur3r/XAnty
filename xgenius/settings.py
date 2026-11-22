"""Runtime settings for the local profile manager."""
import json
from pathlib import Path

SETTINGS_FILE = Path(__file__).resolve().parents[1] / "config" / "settings.json"
# Legacy license module is not used by the local profile manager.
LICENSE_SHEET_URL = ""
WEB_HOST = "127.0.0.1"
WEB_PORT = 8765
OPEN_BROWSER = False
BROWSER_APP_MODE = False
LOGIN_DELAY_SECONDS = 40
EXECUTOR_MAX_WORKERS = 128
HEALTH_TIMEOUT_STRIKES = 3
IDLE_HEALTH_INTERVAL = 2
BLOCK_MEDIA_URLS = True
SYSMON_INTERVAL = 5
SYSMON_LOG_EVERY = 60
SYSMON_ACCOUNTS_EVERY = 60
SYSMON_HISTORY_MINUTES = 60


def _apply_overrides():
    if not SETTINGS_FILE.exists():
        return
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"[settings] Invalid settings.json: {exc}")
        return
    if not isinstance(data, dict):
        return
    allowed = {
        "WEB_HOST", "WEB_PORT", "OPEN_BROWSER", "BROWSER_APP_MODE", "LOGIN_DELAY_SECONDS",
        "EXECUTOR_MAX_WORKERS", "HEALTH_TIMEOUT_STRIKES", "IDLE_HEALTH_INTERVAL", "BLOCK_MEDIA_URLS",
        "SYSMON_INTERVAL", "SYSMON_LOG_EVERY", "SYSMON_ACCOUNTS_EVERY", "SYSMON_HISTORY_MINUTES",
    }
    for key in allowed & data.keys():
        globals()[key] = data[key]


_apply_overrides()
