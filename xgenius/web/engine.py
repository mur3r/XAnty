"""Runtime browser sessions and state for the local web interface."""
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xgenius import __version__
from xgenius.accounts.manager import AccountManager
from xgenius.auto_login_policy import is_auto_login_enabled
from xgenius.config import Config
from xgenius.folders import FolderStore
from xgenius.logger import Logger
from xgenius.process_utils import kill_orphan_chrome
from xgenius.proxy_service import ProxyCheckError, parse_proxy
from xgenius.settings import EXECUTOR_MAX_WORKERS
from xgenius.sysmon import CountingExecutor, SystemMonitor

# Статусы, которые считаем "ошибкой" в сводке (всё, кроме служебных пауз/восстановления)
_NON_ERROR_STATUS_PREFIXES = ("RECOVERING", "DM LIMIT", "SEND STALL")


class Engine:
    def __init__(self, loop: asyncio.AbstractEventLoop, base_dir: Optional[Path] = None):
        self.loop = loop
        self.started_at = datetime.now()

        self.config = Config(base_dir)
        self.logger = Logger(self.config)
        self.account_manager = AccountManager(self.config, self.logger)
        self.folders = FolderStore(self.config.base_dir / "folders.json")
        saved_accounts = self.account_manager.load_accounts()
        self.folders.sync(a.get("group", "") for a in saved_accounts)
        folder_names = {name.casefold(): name for name in self.folders.list()}
        changed = False
        for account in saved_accounts:
            group = account.get("group") or ""
            canonical = folder_names.get(group.casefold(), group)
            if canonical != group:
                account["group"] = canonical
                changed = True
        if changed:
            self.account_manager.save_accounts(saved_accounts)

        # Пул потоков для блокирующих вызовов Selenium (>= число аккаунтов). CountingExecutor
        # считает вызовы в работе и их длительность — это видно на вкладке Load и в [SYSMON].
        self.executor = CountingExecutor(max_workers=EXECUTOR_MAX_WORKERS, thread_name_prefix="xg")
        self.loop.set_default_executor(self.executor)
        self.sysmon = SystemMonitor(self, self.executor)
        try:
            killed = kill_orphan_chrome(self.config.browser_profiles_dir)
            if killed:
                self.logger.info(f"Добиты осиротевшие процессы chrome с прошлого запуска: {killed}")
        except Exception:
            pass

        self._changed = asyncio.Event()
        self.account_manager.on_state_change = self.notify
        self._tasks: List[asyncio.Task] = [
            self.loop.create_task(self.account_manager.idle_health_watchdog()),
            self.loop.create_task(self.sysmon.run()),
        ]
        self.logger.info(f"X-Genius {__version__}: движок запущен, база: {self.config.base_dir}")

    # ------------------------------------------------------------------
    # Account list changes notify connected clients.
    # ------------------------------------------------------------------
    def notify(self) -> None:
        try:
            self.loop.call_soon_threadsafe(self._changed.set)
        except RuntimeError:
            pass

    def update_account_table_threadsafe(self) -> None:
        self.notify()

    def update_account_table(self, force: bool = False) -> None:
        self.notify()

    async def wait_change(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._changed.wait(), timeout)
            self._changed.clear()
            return True
        except asyncio.TimeoutError:
            return False

    # ------------------------------------------------------------------
    # Снимок состояния для интерфейса
    # ------------------------------------------------------------------
    def _status_is_error(self, reason: str) -> bool:
        if not reason:
            return False
        return not reason.upper().startswith(_NON_ERROR_STATUS_PREFIXES)

    def account_rows(self) -> List[Dict[str, Any]]:
        am = self.account_manager
        am.refresh_closed_browsers()
        rows = []
        for index, acc in enumerate(am.load_accounts(), 1):
            u = acc["username"]
            st = am.accounts.get(u)
            rows.append({
                "index": index,
                "username": u,
                "profile_name": acc.get("profile_name") or acc.get("dolphin_name") or u,
                "notes": acc.get("notes", ""),
                "tags": acc.get("tags", []),
                "dolphin_profile_id": acc.get("dolphin_profile_id"),
                "import_warnings": acc.get("import_warnings", []),
                "group": acc.get("group", "") or "",
                "proxy": self.proxy_label(acc.get("proxy", "")),
                "proxy_status": st.proxy_status if st else "",
                "proxy_ip": st.proxy_ip if st else "",
                "proxy_error": st.proxy_error if st else "",
                "proxy_location": getattr(st, 'proxy_location', {}) if st else {},
                "proxy_location_error": getattr(st, 'proxy_location_error', '') if st else '',
                "launch_error": getattr(st, 'launch_error', '') if st else '',
                "launch_error_seq": getattr(st, 'launch_error_seq', 0) if st else 0,
                "has_token": bool(acc.get("auth_token")),
                "has_password": bool(acc.get("password")),
                "auto_login": is_auto_login_enabled(acc),
                "browser_language": acc.get("browser_language", ""),
                "browser_timezone": acc.get("browser_timezone", ""),
                "browser_version": st.browser_version if st and st.browser else "",
                "browser_user_agent": st.browser_user_agent if st and st.browser else "",
                "login_status": ("needs_attention" if st and st.status_reason else
                                 "signed_in" if st and st.is_active else
                                 "manual" if st and st.browser and not is_auto_login_enabled(acc) else
                                 "open" if st and st.browser else "closed"),
                "status": (st.status_reason if st and st.status_reason else
                           "SIGNED IN" if st and st.is_active else
                           "MANUAL" if st and st.browser and not is_auto_login_enabled(acc) else
                           "OPEN" if st and st.browser else "CLOSED"),
                "status_color": "#d35400" if st and st.status_reason else "#27ae60" if st and st.browser else "gray",
                "status_reason": st.status_reason if st else "",
                "last_launch": st.last_action_time.strftime("%H:%M:%S") if st and st.browser else "N/A",
                "is_active": bool(st and st.is_active),
                "need_relogin": bool(st and st.need_relogin),
                "has_browser": bool(st and st.browser),
            })
        return rows

    @staticmethod
    def proxy_label(raw: str) -> str:
        if not raw:
            return ""
        try:
            proxy = parse_proxy(raw)
            return proxy.server[7:]
        except ProxyCheckError:
            return "Invalid proxy"

    def summary(self, rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        total = {"all": len(rows), "error": 0, "ready": 0, "inactive": 0, "browsers": 0}
        for r in rows:
            if r["has_browser"]:
                total["browsers"] += 1
            if self._status_is_error(r["status_reason"]):
                total["error"] += 1
            elif r["is_active"]:
                total["ready"] += 1
            else:
                total["inactive"] += 1
        return total

    def snapshot(self) -> Dict[str, Any]:
        rows = self.account_rows()
        groups = self.folders.list()
        return {
            "phase": "ready",
            "version": __version__,
            "base_dir": str(self.config.base_dir),
            "summary": self.summary(rows),
            "groups": groups,
            "folders": groups,
            "accounts": rows,
            "log_seq": self.logger.seq,
            "sysmon_enabled": self.sysmon.enabled,
        }

    def logs_since(self, seq: int) -> Tuple[int, List[str]]:
        current = self.logger.seq
        new_count = current - seq
        if new_count <= 0:
            return current, []
        buffer = list(self.logger.log_buffer)
        if new_count >= len(buffer):
            return current, buffer
        return current, buffer[-new_count:]

    # ------------------------------------------------------------------
    async def shutdown(self) -> None:
        for t in self._tasks:
            t.cancel()
        try:
            self.account_manager.stop_worker = True
        except Exception:
            pass
        try:
            await self.loop.run_in_executor(None, self.account_manager.shutdown_all_browsers)
        except Exception as e:
            self.logger.error(f"Ошибка при закрытии браузеров: {e}")
