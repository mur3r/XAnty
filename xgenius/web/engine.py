"""Runtime browser sessions and state for the local web interface."""
import asyncio
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from xgenius import __version__
from xgenius.accounts.manager import AccountManager
from xgenius.backups import BackupError, BackupManager
from xgenius.auto_login_policy import is_auto_login_enabled
from xgenius.config import Config
from xgenius.folders import FolderStore
from xgenius.logger import Logger
from xgenius.process_utils import kill_orphan_chrome
from xgenius.proxy_service import ProxyCheckError, parse_proxy
from xgenius.settings import EXECUTOR_MAX_WORKERS
from xgenius.sysmon import CountingExecutor, SystemMonitor
from xgenius.browser_workspace import save_workspace
from xgenius.preferences import read_preferences
from xgenius.profile_leases import ProfileInUseError, ProfileLease, profile_directory
from xgenius.workspace_operations import profile_size

# Статусы, которые считаем "ошибкой" в сводке (всё, кроме служебных пауз/восстановления)
_NON_ERROR_STATUS_PREFIXES = ("RECOVERING", "DM LIMIT", "SEND STALL")


class Engine:
    def __init__(self, loop: asyncio.AbstractEventLoop, base_dir: Optional[Path] = None):
        try:
            self._initialize(loop,base_dir)
        except BaseException:
            cancellation = getattr(self, '_shutdown_event', None)
            if cancellation is not None:
                cancellation.set()
            for task in getattr(self,'_tasks',[]):
                task.cancel()
            manager = getattr(self,'account_manager',None)
            if manager is not None:
                manager.stop_worker = True
                manager.workspace_lease.release()
            executor = getattr(self,'executor',None)
            if executor is not None:
                executor.shutdown(wait=False)
            raise

    def _initialize(self, loop, base_dir):
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
            self.account_manager.purge_trash()
        except Exception as exc:
            self.logger.error(f'Trash cleanup failed: {exc}')

        self._changed = asyncio.Event()
        self._workspace_futures = set()
        self.backups = BackupManager(self.config)
        self._profile_sizes = {}
        self._profile_size_checked = {}
        self._backup_jobs = set()
        self._backup_running = False
        self._shutdown_event = threading.Event()
        self._stopping = False
        self.account_manager.on_state_change = self.notify
        self._tasks: List[asyncio.Task] = [
            self.loop.create_task(self.account_manager.idle_health_watchdog()),
            self.loop.create_task(self.sysmon.run()),
            self.loop.create_task(self._profile_maintenance()),
            self.loop.create_task(self._autosave_workspaces()),
            self.loop.create_task(self._workspace_maintenance()),
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
                "index": acc.get('profile_number', index),
                "profile_id": acc.get('profile_id'),
                "profile_status": acc.get('profile_status', 'new'),
                "favorite": acc.get('favorite', False),
                "important": acc.get('important', False),
                "reminder_at": acc.get('reminder_at'),
                "reminder_note": acc.get('reminder_note', ''),
                "profile_size": (dict(getattr(self, '_profile_sizes', {}).get(u) or {}) or None),
                "runtime_seconds": acc.get('runtime_seconds', 0),
                "runtime_checkpoint": acc.get('runtime_checkpoint'),
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
                "restore_tabs": acc.get('restore_tabs',True),
                "extension_set": acc.get('extension_set',''),
                "frame_color": acc.get('frame_color',''),
                "session_saved_at": getattr(st,'session_saved_at','') if st else '',
                "session_save_error": getattr(st,'session_save_error','') if st else '',
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
                "last_launch": acc.get('last_launch'),
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
        backups = getattr(self, 'backups', None)
        try:
            backup_status = backups.snapshot() if backups is not None else None
        except BackupError as exc:
            backup_status = {'enabled': False, 'running': False, 'last_status': 'failed', 'error': str(exc)}
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
            "backups": backup_status,
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
    async def _autosave_workspaces(self):
        while True:
            await asyncio.sleep(10)
            prefs = read_preferences()
            for username,state in list(self.account_manager.accounts.items()):
                browser = state.browser
                if browser is None or getattr(self.account_manager,'_session_is_busy',lambda u:False)(username):
                    continue
                full = prefs['session_autosave'] and time.monotonic() - getattr(browser,'_xg_last_full_save',0) >= prefs['autosave_seconds']
                try:
                    future = self.loop.run_in_executor(None, save_workspace,browser,self.config,username,full)
                    self._workspace_futures.add(future)
                    future.add_done_callback(self._workspace_futures.discard)
                    result = await asyncio.shield(future)
                    if full:
                        browser._xg_last_full_save = time.monotonic()
                        state.session_saved_at = result['saved_at']; state.session_save_error = ''
                        self.notify()
                except Exception as exc:
                    if state.browser is browser:
                        state.session_save_error = f'Session save failed: {type(exc).__name__}'
                        self.notify()

    async def _profile_maintenance(self):
        tick = 0
        while True:
            await asyncio.sleep(30)
            try:
                await self._run_workspace_worker(self.account_manager.checkpoint_sessions)
                tick += 1
                if tick % 2 == 0:
                    removed = await self._run_workspace_worker(self.account_manager.purge_trash)
                    if removed:
                        self.notify()
            except Exception as exc:
                self.logger.error(f'Profile maintenance failed: {exc}')

    async def _run_workspace_worker(self,function,*args):
        future=self.loop.run_in_executor(None,function,*args)
        self._workspace_futures.add(future)
        future.add_done_callback(self._workspace_futures.discard)
        return await asyncio.shield(future)

    def _workspace_is_idle(self) -> bool:
        actions = getattr(self, 'actions', None)
        if (getattr(self, '_stopping', False) or actions is None or getattr(actions, '_stopping', False)
                or getattr(self, '_backup_running', False)):
            return False
        if any(getattr(state, 'browser', None) is not None for state in self.account_manager.accounts.values()):
            return False
        for field in ('_busy', '_closing', '_transferring', '_profile_operations'):
            if getattr(actions, field, None):
                return False
        for field in ('_launch_tasks', '_file_futures', '_closing_futures'):
            if any(not item.done() for item in getattr(actions, field, ())):
                return False
        if any(not item.done() for item in getattr(actions, '_proxy_checks', {}).values()):
            return False
        return True

    async def run_backup(self, progress=None, cancelled=None) -> dict:
        """Reserve profiles on the event loop and keep them reserved until I/O ends."""
        if getattr(self, '_stopping', False):
            raise BackupError('Application is shutting down')
        self.account_manager.refresh_closed_browsers()
        if not self._workspace_is_idle():
            raise BackupError('Close all profiles and wait for active operations before creating a backup')
        accounts = self.account_manager.load_accounts()
        if not accounts:
            raise BackupError('No profiles to back up')
        actions = self.actions
        names = {account['username'] for account in accounts} | set(self.account_manager.accounts)
        folders = self.folders.list()
        local_cancel = threading.Event()
        shutdown = self._shutdown_event
        self._backup_running = True
        actions._transferring.update(names)
        self.notify()

        def is_cancelled():
            return local_cancel.is_set() or shutdown.is_set() or bool(cancelled and cancelled())

        async def execute():
            try:
                return await self._run_workspace_worker(
                    lambda: self.backups.run(accounts, folders=folders, progress=progress, cancelled=is_cancelled))
            finally:
                actions._transferring.difference_update(names)
                self._backup_running = False
                self.notify()

        job = self.loop.create_task(execute())
        self._backup_jobs.add(job)
        job.add_done_callback(self._backup_jobs.discard)
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            local_cancel.set()
            # Cancelling an await does not stop an executor thread. The shielded
            # job owns its reservations and releases them after real completion.
            try:
                await asyncio.shield(job)
            except (Exception, asyncio.CancelledError):
                pass
            raise

    def _measure_profile_sizes(self, names):
        result = {}
        cancellation = self._shutdown_event
        for username in names:
            if cancellation.is_set():
                break
            try:
                with ProfileLease.acquire_path(profile_directory(self.config, username), create_profile=False):
                    result[username] = profile_size(self.config, username)
            except (ProfileInUseError, OSError, ValueError):
                continue
        return result

    async def _refresh_profile_sizes(self):
        if getattr(self, '_stopping', False):
            return
        accounts = self.account_manager.load_accounts()
        names = {account['username'] for account in accounts}
        cache = getattr(self, '_profile_sizes', {})
        checked = getattr(self, '_profile_size_checked', {})
        self._profile_sizes, self._profile_size_checked = cache, checked
        for username in set(cache) - names:
            cache.pop(username, None)
            checked.pop(username, None)
        eligible = []
        moment = time.monotonic()
        for username in names:
            state = self.account_manager.accounts.get(username)
            if state is not None and getattr(state, 'browser', None) is not None:
                continue
            if getattr(self.account_manager, '_session_is_busy', lambda name: False)(username):
                continue
            if username in checked and moment - checked[username] < 300:
                continue
            eligible.append(username)
        if not eligible:
            return
        measurements = await self._run_workspace_worker(self._measure_profile_sizes, eligible)
        current = {account['username'] for account in self.account_manager.load_accounts()}
        for username, measurement in measurements.items():
            if username in current:
                cache[username] = measurement
                checked[username] = time.monotonic()
        if measurements:
            self.notify()

    async def _workspace_maintenance_once(self):
        if getattr(self, '_stopping', False):
            return
        self.account_manager.refresh_closed_browsers()
        if self._workspace_is_idle() and self.account_manager.load_accounts() and self.backups.due():
            try:
                await self.run_backup()
            except BackupError as exc:
                self.logger.error(f'Automatic backup postponed or failed: {exc}')
        await self._refresh_profile_sizes()

    async def _workspace_maintenance(self):
        while True:
            try:
                await self._workspace_maintenance_once()
            except Exception as exc:
                self.logger.error(f'Workspace maintenance failed: {type(exc).__name__}')
            await asyncio.sleep(30)

    async def shutdown(self) -> None:
        self._stopping = True
        cancellation = getattr(self, '_shutdown_event', None)
        if cancellation is not None:
            cancellation.set()
        if getattr(self,'actions',None) is not None:
            await self.actions.shutdown()
        for t in self._tasks:
            t.cancel()
        await asyncio.gather(*self._tasks,return_exceptions=True)
        jobs = getattr(self, '_backup_jobs', set())
        if jobs:
            await asyncio.gather(*list(jobs), return_exceptions=True)
        if self._workspace_futures:
            await asyncio.gather(*list(self._workspace_futures),return_exceptions=True)
        try:
            self.account_manager.stop_worker = True
        except Exception:
            pass
        try:
            await self.loop.run_in_executor(None, self.account_manager.shutdown_all_browsers)
        except Exception as e:
            self.logger.error(f"Ошибка при закрытии браузеров: {e}")
        finally:
            lease = getattr(self.account_manager,'workspace_lease',None)
            if lease is not None:
                lease.release()
