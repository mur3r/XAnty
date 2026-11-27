"""
Операции над аккаунтами для веб-интерфейса. Это перенесённая логика прежних
GUI-миксинов (sessions / login_parse / dialogs / settings_windows), без tkinter:
никаких потоков и messagebox — всё выполняется в asyncio-цикле движка.
"""
import asyncio
import json
import re
from contextlib import ExitStack
from typing import Any, Dict, List, Optional, Tuple

from xgenius.models import AccountCredentials, AccountState
from xgenius.cookies import CookieError, get_cookies_file_path, normalize_cookies, read_cookies, save_cookies, store_cookies
from xgenius.dolphin_import import DolphinClient, DolphinError, profile_id, map_profile
from xgenius.folders import FolderError, folder_name
from xgenius.auto_login_policy import apply_auto_login, is_auto_login_enabled
from xgenius.process_utils import hard_close_browser, kill_orphan_chrome
from xgenius.proxy_service import ProxyCheckError, check_proxy, lookup_proxy_location, parse_proxy
from xgenius.proxy_rotation import ProxyRotationError, request_rotation, rotation_url
from xgenius.error_messages import safe_launch_error
from xgenius.profile_settings import ProfileSettingsError, browser_settings, workspace_settings
from xgenius.preferences import read_preferences
from xgenius.user_agent import browser_identity, profile_identity, user_agent_settings
from xgenius.browser_workspace import browser_lock, save_workspace, parse_cookie_input, live_cookies, clear_cache, profile_directory
from xgenius.profile_leases import ProfileLease
from xgenius.portable_session import export_session, store_session
from xgenius.extension_sets import ExtensionSetStore
from xgenius.network_diagnostics import diagnose
from xgenius.profile_metadata import metadata_values, record_session_time, name_key
from xgenius.settings import LOGIN_DELAY_SECONDS


class ActionError(Exception):
    pass

ERROR_STATUSES_RESET = ("Error", "LOCKED", "EMAIL LOCK", "LOCKED (CAPTCHA)", "RELOGIN FAILED", "BROWSER_CLOSED")


def _credentials(acc: dict) -> AccountCredentials:
    settings = browser_settings(acc)
    return AccountCredentials(
        username=acc["username"],
        password=acc.get("password", ""),
        profile_name=acc.get('profile_name') or acc['username'],
        profile_id=acc.get('profile_id',''),
        profile_number=acc.get('profile_number'),
        icon_text=acc.get('icon_text',''),
        proxy=acc.get("proxy"),
        user_agent=acc.get("user_agent"),
        user_agent_mode=acc.get("user_agent_mode", "auto"),
        headless=acc.get("headless", False),
        group=acc.get("group", ""),
        auth_token=acc.get("auth_token"),
        ct0_token=acc.get("ct0_token"),
        auto_login=is_auto_login_enabled(acc),
        **settings,
        **workspace_settings(acc),
    )


class Actions:
    def __init__(self, engine):
        self.e = engine
        self._busy: set = set()
        self._closing: set = set()
        self._transferring: set = set()
        self._proxy_checks = {}
        self._proxy_rotations = {}
        self._rotating_urls = set()
        self._launch_tasks = set()
        self._profile_operations = set()
        self._closing_futures = set()
        self._file_futures = set()
        self._stopping = False
        self.e.actions = self
        self.am._session_is_busy = lambda u: u in self._busy or u in self._closing or u in self._transferring or u in self._profile_operations

    async def shutdown(self):
        self._stopping = True
        tasks = list(self._launch_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks,return_exceptions=True)
        if self._proxy_rotations:
            await asyncio.gather(*(asyncio.shield(task) for task in list(self._proxy_rotations.values())),
                                 return_exceptions=True)
        manager = getattr(self.am,'browser_manager',None)
        if manager is not None:
            await manager.shutdown()
        if self._closing_futures or self._file_futures:
            await asyncio.gather(*[asyncio.shield(f) for f in self._closing_futures | self._file_futures],return_exceptions=True)

    async def _run_profile_worker(self, function, *args):
        if self._stopping:
            raise ActionError('Application is shutting down')
        future = self.e.loop.run_in_executor(None,function,*args)
        self._file_futures.add(future)
        future.add_done_callback(self._file_futures.discard)
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            # A disconnected request does not stop a disk worker. Keep caller
            # reservations alive until the real filesystem operation completes.
            try:
                await asyncio.shield(future)
            except (Exception,asyncio.CancelledError):
                pass
            raise

    # ------------------------------------------------------------------ helpers
    @property
    def am(self):
        return self.e.account_manager

    def _account(self, username: str) -> Optional[dict]:
        return next((a for a in self.am.load_accounts() if a.get("username") == username), None)

    def _state(self, username: str) -> Optional[AccountState]:
        return self.am.accounts.get(username)

    def _log(self, msg: str, username: Optional[str] = None, level: str = "info") -> None:
        getattr(self.e.logger, level)(msg, username)

    def _sync_folders(self, accounts: List[dict]) -> None:
        try:
            self.e.folders.sync(a.get("group", "") for a in accounts)
            names = {name.casefold(): name for name in self.e.folders.list()}
            for account in accounts:
                group = account.get("group") or ""
                if isinstance(group, str) and group.casefold() in names:
                    account["group"] = names[group.casefold()]
        except FolderError as exc:
            raise ActionError(str(exc)) from exc

    def create_folder(self, name: str, usernames: List[str]) -> str:
        accounts = self.am.load_accounts()
        selected = set(usernames)
        if selected - {a["username"] for a in accounts}:
            raise ActionError("One or more selected profiles no longer exist.")
        try:
            name = self.e.folders.create(name)
        except FolderError as exc:
            raise ActionError(str(exc)) from exc
        if selected:
            try:
                for acc in accounts:
                    if acc["username"] in selected:
                        acc["group"] = name
                self.am.save_accounts(accounts)
            except Exception:
                self.e.folders.delete(name)
                raise
        self._log(f"Folder created: {name}; profiles added: {len(selected)}")
        self.e.notify()
        return name

    def move_to_folder(self, usernames: List[str], name: str) -> int:
        requested = name
        try:
            name = self.e.folders.get(name) if name else ""
        except FolderError as exc:
            raise ActionError(str(exc)) from exc
        if requested and not name:
            raise ActionError("Folder not found.")
        accounts = self.am.load_accounts()
        selected = set(usernames)
        if selected - {a["username"] for a in accounts}:
            raise ActionError("One or more selected profiles no longer exist.")
        for acc in accounts:
            if acc["username"] in selected:
                acc["group"] = name
        self.am.save_accounts(accounts)
        self._log(f"Moved {len(selected)} profile(s) to {name or 'No folder'}")
        self.e.notify()
        return len(selected)

    def rename_folder(self, old: str, new: str) -> str:
        try:
            new = folder_name(new)
            old = self.e.folders.get(old)
            if not old:
                raise FolderError("Folder not found.")
            if self.e.folders.get(new) and new.casefold() != old.casefold():
                raise FolderError("A folder with this name already exists.")
        except FolderError as exc:
            raise ActionError(str(exc)) from exc
        accounts = self.am.load_accounts()
        affected = {a["username"] for a in accounts if a.get("group") == old}
        for acc in accounts:
            if acc["username"] in affected:
                acc["group"] = new
        self.am.save_accounts(accounts)
        try:
            self.e.folders.rename(old, new)
        except Exception:
            for acc in accounts:
                if acc["username"] in affected:
                    acc["group"] = old
            self.am.save_accounts(accounts)
            raise
        self._log(f"Folder renamed: {old} -> {new}")
        self.e.notify()
        return new

    def delete_folder(self, name: str) -> int:
        try:
            name = self.e.folders.get(name)
            if not name:
                raise FolderError("Folder not found.")
        except FolderError as exc:
            raise ActionError(str(exc)) from exc
        accounts = self.am.load_accounts()
        affected = {a["username"] for a in accounts if a.get("group") == name}
        moved = len(affected)
        for acc in accounts:
            if acc["username"] in affected:
                acc["group"] = ""
        self.am.save_accounts(accounts)
        try:
            self.e.folders.delete(name)
        except Exception:
            for acc in accounts:
                if acc["username"] in affected:
                    acc["group"] = name
            self.am.save_accounts(accounts)
            raise
        self._log(f"Folder removed: {name}; {moved} profile(s) left unfiled")
        self.e.notify()
        return moved

    async def rotate_account_proxy(self, username: str) -> dict:
        if self._stopping:
            raise ActionError('Application is shutting down')
        task = self._proxy_rotations.get(username)
        if task is None or task.done():
            task = self._proxy_rotations[username] = asyncio.create_task(self._rotate_account_proxy(username))
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._proxy_rotations.get(username) is task:
                self._proxy_rotations.pop(username, None)

    async def _rotate_account_proxy(self, username: str) -> dict:
        account = self._account(username)
        if account is None:
            raise ActionError('Account not found')
        try:
            parse_proxy(account.get('proxy'))
            url = rotation_url(account.get('proxy_rotation_url'))
        except (ProxyCheckError, ProxyRotationError) as exc:
            raise ActionError(str(exc)) from None
        if not url:
            raise ActionError('Add a proxy rotation link in the profile settings first.')
        if url in self._rotating_urls:
            raise ActionError('This proxy rotation link is already in use. Wait for the current rotation to finish.')
        if self.am._session_is_busy(username):
            raise ActionError('Wait for current profile operations before rotating the proxy.')
        self._rotating_urls.add(url)
        self._profile_operations.add(username)
        state = self.am.accounts.setdefault(username, AccountState(username=username))
        state.proxy_rotating = True
        self.e.notify()
        requested = False

        def unchanged():
            current = self._account(username) or {}
            return (self._state(username) is state and current.get('proxy') == account.get('proxy')
                    and current.get('proxy_rotation_url') == account.get('proxy_rotation_url'))

        try:
            checking = self._proxy_checks.get(username)
            if checking and not checking.done():
                await asyncio.shield(checking)
            if not unchanged():
                raise ActionError('Proxy settings changed during rotation. Check the current IP.')
            if not state.proxy_ip:
                await self.check_account_proxy(username)
            if not unchanged():
                raise ActionError('Proxy settings changed during rotation. Check the current IP.')
            previous_ip = state.proxy_ip
            state.proxy_status = ''
            state.proxy_ip = ''
            state.proxy_error = ''
            state.proxy_location = {}
            state.proxy_location_error = ''
            await self._run_profile_worker(request_rotation, url)
            requested = True
            if not unchanged():
                raise ActionError('Proxy settings changed during rotation. Check the current IP.')
            result = {}
            for delay in (0, 3, 6, 10, 15):
                if delay:
                    await asyncio.sleep(delay)
                if not unchanged():
                    raise ActionError('Proxy settings changed during rotation. Check the current IP.')
                result = await self.check_account_proxy(username)
                if result.get('ok') and (not previous_ip or result.get('ip') != previous_ip):
                    break
            if not unchanged():
                raise ActionError('Proxy settings changed during rotation. Check the current IP.')
            self._log('Proxy rotation requested; external IP rechecked', username)
            return {'ok': True, 'requested': True, 'ip': result.get('ip', ''),
                    'changed': result.get('ip') != previous_ip if result.get('ok') and previous_ip else None,
                    'check_error': result.get('error', '')}
        except ProxyRotationError as exc:
            self._log('Proxy rotation request did not complete', username, 'error')
            return {'ok': False, 'requested': requested, 'error': str(exc)}
        finally:
            state.proxy_rotating = False
            self._profile_operations.discard(username)
            self._rotating_urls.discard(url)
            self.e.notify()

    async def check_account_proxy(self, username: str) -> dict:
        task = self._proxy_checks.get(username)
        if task is None or task.done():
            task = self._proxy_checks[username] = asyncio.create_task(self._check_account_proxy(username))
        try:
            return await asyncio.shield(task)
        finally:
            if task.done() and self._proxy_checks.get(username) is task:
                self._proxy_checks.pop(username, None)

    async def _check_account_proxy(self, username: str) -> dict:
        acc = self._account(username)
        if acc is None:
            raise ActionError("Account not found")
        st = self._state(username)
        if st is None:
            st = AccountState(username=username)
            self.am.accounts[username] = st
        st.proxy_status = "checking"
        st.proxy_ip = ""
        st.proxy_error = ""
        st.proxy_location = {}
        st.proxy_location_error = ""
        self.e.notify()
        try:
            proxy = parse_proxy(acc.get("proxy"))
            ip = await self.e.loop.run_in_executor(None, check_proxy, proxy)
            location, location_error = {}, ''
            try:
                location = await self.e.loop.run_in_executor(None, lookup_proxy_location, proxy, ip)
            except ProxyCheckError as exc:
                location_error = str(exc)
            if (self._account(username) or {}).get('proxy') != acc.get('proxy'):
                st.proxy_status = ''
                return {'ok': False, 'error': 'Proxy changed during the check. Please check it again.'}
            st.proxy_ip = ip
            st.proxy_location = location
            st.proxy_location_error = location_error
            st.proxy_status = "ok"
            if st.status_reason == "PROXY ERROR":
                st.status_reason = ""
                st.launch_error = ''
                if not st.browser:
                    st.need_relogin = False
            self._log(f"Proxy check succeeded. External IP: {ip}", username)
            return {"ok": True, "ip": ip, 'location': location, 'location_error': location_error}
        except ProxyCheckError as exc:
            if (self._account(username) or {}).get('proxy') != acc.get('proxy'):
                st.proxy_status = ''
                return {'ok': False, 'error': 'Proxy changed during the check. Please check it again.'}
            st.proxy_status = "error"
            st.proxy_error = str(exc)
            st.status_reason = "PROXY ERROR"
            self._log(f"Proxy check failed: {exc}", username, "error")
            return {"ok": False, "error": str(exc)}
        finally:
            self.e.notify()

    # ------------------------------------------------------------------ login
    async def login_one(self, username: str) -> bool:
        acc = self._account(username)
        if not acc:
            self._log("Аккаунт не найден в accounts.json", username, "error")
            return False
        st = self._state(username)
        if st and st.browser:
            self._log("Browser profile is already open", username)
            return True
        if username in self._busy or username in self._closing or username in self._transferring or username in self._profile_operations:
            self._log("Логин уже выполняется", username, "warning")
            return False
        self._busy.add(username)
        if st is None:
            st = AccountState(username=username)
            self.am.accounts[username] = st
        st.launch_error = ''
        self.e.notify()
        try:
            self._log("Opening browser profile", username)
            await asyncio.wait_for(self.am.login_account(_credentials(acc), fetch_followers=False, notify=True), timeout=240)
            self._log("X sign-in completed" if is_auto_login_enabled(acc) else "Browser opened without X sign-in", username)
            return True
        except asyncio.TimeoutError:
            st = self._state(username)
            if st:
                st.status_reason = "LOGIN TIMEOUT" if is_auto_login_enabled(acc) else "BROWSER TIMEOUT"
                st.launch_error = 'Browser launch or sign-in timed out (240s). Check the proxy and try again.'
                st.launch_error_seq += 1
                st.need_relogin = is_auto_login_enabled(acc)
            self._log("Login timeout (240s)", username, "error")
            return False
        except Exception as ex:
            st = self._state(username)
            message = safe_launch_error(ex, acc)
            if st:
                st.launch_error = message
                st.launch_error_seq += 1
                if not st.status_reason:
                    st.status_reason = 'LOGIN FAILED' if is_auto_login_enabled(acc) else 'BROWSER ERROR'
            self._log(f"Login failed: {message}", username, "error")
            return False
        finally:
            self._busy.discard(username)
            self.e.notify()

    async def login_many(self, usernames: List[str], delay: int = LOGIN_DELAY_SECONDS) -> None:
        total = len(usernames)
        ok, failed = 0, []
        for i, u in enumerate(usernames):
            self._log(f"Starting login ({i + 1}/{total})", u)
            if await self.login_one(u):
                ok += 1
            else:
                failed.append(u)
            if i < total - 1:
                await asyncio.sleep(delay)
        if failed:
            self._log(f"Login completed: {ok} success, {len(failed)} errors. Failed: {', '.join(failed)}")
        else:
            self._log(f"Login completed: {ok}/{total} accounts successfully logged in")

    def start_login(self, usernames: List[str]) -> int:
        if self._stopping:
            raise ActionError('Application is shutting down')
        usernames = [u for u in usernames if u not in self._busy and u not in self._closing and u not in self._transferring and u not in self._profile_operations]
        if not usernames:
            raise ActionError("Нечего запускать: аккаунты не выбраны или уже логинятся")
        if len(usernames) == 1:
            task = self.e.loop.create_task(self.login_one(usernames[0]))
        else:
            task = self.e.loop.create_task(self.login_many(usernames))
        self._launch_tasks.add(task)
        task.add_done_callback(self._launch_tasks.discard)
        return len(usernames)

    # ------------------------------------------------------------------ close / delete

    def _close_state(self, st: AccountState):
        u = st.username
        browser = st.browser
        record_session_time(self.am, u)
        st.browser = None
        st.is_active = False
        st.need_relogin = False
        st.status_reason = ""
        st.launch_error = ''
        if browser is not None:
            self._closing.add(u)
            def persist_and_close():
                with browser_lock(browser):
                    try:
                        save_workspace(browser, self.e.config, u)
                        save_cookies(browser, self.e.config, u)
                    except Exception as exc:
                        self._log(f"Could not save session: {type(exc).__name__}", u, "warning")
                    finally:
                        try:
                            hard_close_browser(browser)
                        finally:
                            self.e.loop.call_soon_threadsafe(self._closing.discard, u)
            future = self.e.loop.run_in_executor(None, persist_and_close)
            self._closing_futures.add(future)
            future.add_done_callback(self._closing_futures.discard)
            return future
        return None

    def close(self, usernames: List[str]) -> int:
        n = 0
        for u in usernames:
            st = self._state(u)
            if st:
                self._close_state(st)
                self._log(f"Browser session ended for {u}", u)
                n += 1
        self.e.notify()
        return n

    def close_all(self) -> int:
        n = 0
        pending = []
        for st in list(self.am.accounts.values()):
            if st.browser or st.is_active:
                n += 1
            task = self._close_state(st)
            if task is not None:
                pending.append(task)
        async def cleanup():
            if pending:
                await asyncio.gather(*[asyncio.shield(f) for f in pending], return_exceptions=True)
        self.e.loop.create_task(cleanup())
        self._log(f"All sessions closed ({n})")
        self.e.notify()
        return n

    async def view(self, username: str) -> None:
        st = self._state(username)
        if not st or not st.browser:
            raise ActionError("Browser is not open")
        browser = st.browser
        def bring_to_front():
            browser.minimize_window()
            browser.maximize_window()
        await self.e.loop.run_in_executor(None, bring_to_front)

    def reset_errors(self) -> int:
        count = 0
        for st in self.am.accounts.values():
            if st.status_reason:
                st.status_reason = ""
                count += 1
        self.e.notify()
        return count

    def confirm_important_delete(self, usernames, confirmation=None, trashed=False):
        records = self.am.trash_rows() if trashed else self.am.load_accounts()
        selected = set(usernames)
        if any(a.get('important') or a.get('favorite') for a in records if a['username'] in selected):
            if confirmation != 'DELETE':
                raise ActionError('Type DELETE to confirm deletion of an important or favorite profile.')

    def delete(self, usernames: List[str], retention_days: int = 30, confirmation=None) -> int:
        self.confirm_important_delete(usernames, confirmation)
        for u in usernames:
            st = self._state(u)
            if u in self._busy or u in self._closing or u in self._transferring or u in self._profile_operations or (st and st.browser):
                raise ActionError('Закройте выбранные профили и дождитесь завершения операций перед удалением в корзину.')
        with ExitStack() as leases:
            for username in usernames:
                leases.enter_context(ProfileLease.acquire(self.e.config,username))
            n = self.am.trash_profiles(usernames, retention_days)
        for u in usernames:
            self.am.accounts.pop(u, None)
        self._log(f"Moved {n} profile(s) to trash")
        self.e.notify()
        return n

    async def open_window_set(self, set_id, exact=True, confirm_close=False):
        if type(exact) is not bool or type(confirm_close) is not bool:
            raise ActionError('Window set options must be booleans')
        names = self.am.resolve_window_set(set_id)
        if self._stopping or self._busy or self._closing or self._transferring or self._profile_operations or any(not t.done() for t in self._launch_tasks):
            raise ActionError('Wait for current profile operations to finish')
        outside = [st for u, st in self.am.accounts.items() if st.browser and u not in names] if exact else []
        if outside and not confirm_close:
            raise ActionError('Confirm closing profiles outside this window set.')
        reserved = set(names) | {st.username for st in outside}
        self._profile_operations.update(reserved)
        try:
            pending = [future for st in outside if (future := self._close_state(st)) is not None]
            if pending:
                await asyncio.gather(*[asyncio.shield(f) for f in pending])
            to_open = [u for u in names if not (self._state(u) and self._state(u).browser)]
        finally:
            self._profile_operations.difference_update(reserved)
        opened = self.start_login(to_open) if to_open else 0
        self.e.notify()
        return {'opened':opened,'closed':len(outside)}

    # ------------------------------------------------------------------ accounts CRUD
    def get_account(self, username: str) -> dict:
        acc = self._account(username)
        if not acc:
            raise ActionError("Account not found")
        return {**acc, **browser_settings(acc), **workspace_settings(acc), "auto_login": is_auto_login_enabled(acc)}

    def _idle_profile(self, username, require_closed=False):
        if self._stopping:
            raise ActionError('Application is shutting down')
        if self._account(username) is None:
            raise ActionError('Account not found')
        st = self._state(username)
        if self.am._session_is_busy(username):
            raise ActionError('Wait for the profile to finish opening or closing')
        if require_closed and st and st.browser:
            raise ActionError('Close this profile before changing local files')
        return st

    async def profile_tool(self, username, operation, data=None):
        st = self._idle_profile(username, require_closed=operation in ('cache','cookies_import'))
        data = data or {}
        browser = st.browser if st else None
        if operation == 'folder':
            import os
            path = profile_directory(self.e.config, username)
            path.mkdir(parents=True, exist_ok=True)
            if not hasattr(os, 'startfile'):
                raise ActionError('Opening profile folders is available on Windows')
            os.startfile(str(path))
            return {'path': str(path)}
        if operation in ('save','diagnostics') and not (st and st.browser):
            raise ActionError('Browser is not open')
        self._profile_operations.add(username)
        try:
            if operation == 'user_agent':
                account = self._account(username)
                if browser:
                    from xgenius.browser_cdp import browser_connection
                    def read_identity():
                        with browser_lock(browser), browser_connection(browser) as connection:
                            current = connection.call('Browser.getVersion')
                        return {'available': True, 'user_agent': current['userAgent'],
                                'browser_version': current['product'].split('/', 1)[-1],
                                'source': 'live', 'mode': account.get('user_agent_mode', 'auto'), 'error': ''}
                    try:
                        return await self._run_profile_worker(read_identity)
                    except Exception:
                        raise ActionError('Could not read the live User-Agent. Check that the profile is still open.') from None
                return profile_identity(self._account(username), await self._run_profile_worker(browser_identity, self.e.config))
            if operation == 'cache':
                return await self._run_profile_worker( clear_cache, self.e.config, username)
            if operation == 'cookies':
                if st and st.browser:
                    def read_live():
                        with browser_lock(browser):
                            return live_cookies(browser)
                    cookies = await self._run_profile_worker( read_live)
                    return {'cookies': cookies, 'source':'live', 'warnings':[]}
                def read_saved():
                    with ProfileLease.acquire(self.e.config,username):
                        cookies, warnings = export_session(self.e.config,username)
                        return {'cookies':cookies,'source':'saved','warnings':warnings}
                return await self._run_profile_worker(read_saved)
            if operation == 'cookies_import':
                cookies = parse_cookie_input(data.get('cookies'))
                def import_prepared():
                    with ProfileLease.acquire(self.e.config,username):
                        previous, _ = export_session(self.e.config,username)
                        merged = {(c['domain'],c['path'],c['name']):c for c in previous}
                        merged.update({(c['domain'],c['path'],c['name']):c for c in cookies})
                        store_session(self.e.config,username,list(merged.values()),pending=True)
                    return {'imported':len(cookies),'total':len(merged)}
                return await self._run_profile_worker( import_prepared)
            if operation == 'diagnostics':
                return await self._run_profile_worker( diagnose, browser, st.proxy_ip)
            if operation == 'save':
                result = await self._run_profile_worker( save_workspace, browser, self.e.config,username)
                st.session_saved_at = result['saved_at']; st.session_save_error = ''
                self.e.notify()
                return result
            raise ActionError('Unknown profile tool')
        finally:
            self._profile_operations.discard(username)

    async def export_cookies(self, username: str) -> list[dict]:
        if self._account(username) is None:
            raise ActionError("Account not found")
        st = self._state(username)
        if username in self._busy or username in self._closing:
            raise ActionError("Wait for the profile to finish opening or closing")
        if st and st.browser:
            try:
                cookies = await self.e.loop.run_in_executor(None, st.browser.get_cookies)
                return normalize_cookies(cookies)
            except CookieError:
                pass  # Current tab is not on X; use the last saved snapshot.
            except Exception as exc:
                raise ActionError(f"Could not read browser cookies: {type(exc).__name__}") from exc
        try:
            return read_cookies(self.e.config, username)
        except CookieError as exc:
            raise ActionError(str(exc)) from exc

    def import_cookies(self, username: str, data) -> int:
        if self._account(username) is None:
            raise ActionError("Account not found")
        st = self._state(username)
        if username in self._busy or username in self._closing or (st and st.browser):
            raise ActionError("Close this profile before importing cookies")
        try:
            count = store_cookies(self.e.config, username, data)
        except CookieError as exc:
            raise ActionError(str(exc)) from exc
        self._log(f"Imported {count} X/Twitter cookies; restart profile to apply", username)
        return count

    def set_auto_login(self, usernames: List[str], enabled: bool) -> int:
        accounts = self.am.load_accounts()
        try:
            count = apply_auto_login(accounts, usernames, enabled)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        self.am.save_accounts(accounts)
        self._log(f"X auto sign-in {'enabled' if enabled else 'disabled'} for {count} profile(s)")
        self.e.notify()
        return count

    def add_account(self, data: dict) -> None:
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        auth_token = (data.get("auth_token") or "").strip()
        if not username:
            raise ActionError("Username is required!")
        if type(data.get("auto_login", False)) is not bool:
            raise ActionError("auto_login must be a boolean")
        try:
            settings = browser_settings(data)
            settings.update(user_agent_settings(data, self.e.config))
            settings.update(workspace_settings({**data, 'username':username}))
            metadata = metadata_values({k: data[k] for k in ('profile_status', 'favorite', 'tags', 'important', 'reminder_at', 'reminder_note', 'icon_text') if k in data})
        except ProfileSettingsError as exc:
            raise ActionError(str(exc)) from exc
        acs = self.am.load_accounts()
        if any(a["username"] == username for a in acs):
            raise ActionError(f"Account with username '{username}' already exists!")
        if name_key(username) in getattr(self.am,'reserved_profile_names',lambda:set())():
            raise ActionError('A profile with this name already exists or is in trash')
        acs.append({
            "username": username,
            "profile_name": str(data.get("profile_name") or username).strip(),
            "notes": str(data.get("notes") or ""),
            "password": password,
            "proxy": (data.get("proxy") or "").strip(),
            "proxy_rotation_url": rotation_url(data.get('proxy_rotation_url')),
            "user_agent": (data.get("user_agent") or "").strip(),
            "group": (data.get("group") or "").strip(),
            "auth_token": auth_token,
            "ct0_token": (data.get("ct0_token") or "").strip(),
            "auto_login": data.get("auto_login", False) is True,
            **settings,
            "headless": False,
            **metadata,
        })
        self._sync_folders(acs)
        if settings.get('extension_set'):
            with ProfileLease.acquire(self.e.config,username):
                ExtensionSetStore(self.e.config).materialize(settings['extension_set'], profile_directory(self.e.config,username))
        self.am.save_accounts(acs)
        self._log(f"Account added: {username}")

    def import_accounts(self, text: str) -> Tuple[int, int]:
        """Формат строки: username|auth_token|ct0_token|proxy|group (auth_token обязателен)."""
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if not lines:
            raise ActionError("Please enter account data!")
        acs = self.am.load_accounts()
        existing = {a["username"] for a in acs}
        added = skipped = 0
        for line in lines:
            parts = [p.strip() for p in line.split("|")]
            if len(parts) < 2:
                skipped += 1
                continue
            username, auth_token = parts[0], parts[1]
            if not username or not auth_token or username in existing:
                skipped += 1
                continue
            acs.append({
                "username": username, "password": "", "proxy": parts[3] if len(parts) > 3 else "",
                "user_agent": "", "group": parts[4] if len(parts) > 4 else "",
                "auth_token": auth_token, "ct0_token": parts[2] if len(parts) > 2 else "", "headless": False,
                "auto_login": False,
            })
            existing.add(username)
            added += 1
        self._sync_folders(acs)
        self.am.save_accounts(acs)
        self._log(f"Import: added {added}, skipped {skipped}")
        return added, skipped

    @staticmethod
    def _fetch_dolphin(token: str, source_id, password: str, username: str, folder: str):
        client = DolphinClient(token)
        try:
            return client.inspect(source_id, password, username, folder)
        finally:
            client.close()

    @staticmethod
    def _dolphin_ids(token: str, limit: int) -> list[int]:
        client = DolphinClient(token)
        try:
            return client.profile_ids(limit)
        finally:
            client.close()

    async def preview_dolphin(self, token: str, source_id, password: str = '',
                              username: str = '', folder: str = 'Dolphin') -> dict:
        try:
            folder = folder_name(folder or 'Dolphin')
            account, cookies, warnings = await self.e.loop.run_in_executor(
                None, self._fetch_dolphin, token, source_id, password, username, folder)
        except (DolphinError, FolderError) as exc:
            raise ActionError(str(exc)) from exc
        existing = self.am.load_accounts()
        imported = next((a['username'] for a in existing if
                         str(a.get('dolphin_profile_id', '')) == str(account['dolphin_profile_id'])), '')
        return {'id': account['dolphin_profile_id'], 'name': account['dolphin_name'],
                'username': account['username'], 'folder': folder,
                'proxy': self.e.proxy_label(account['proxy']),
                'browser_language': account['browser_language'],
                'browser_timezone': account['browser_timezone'],
                'window_width': account['window_width'], 'window_height': account['window_height'],
                'x_cookies': len(cookies), 'warnings': warnings, 'already_imported_as': imported}

    def _commit_dolphin(self, account: dict, cookies: list[dict], warnings: list[str], portable=None) -> dict:
        accounts = self.am.load_accounts()
        source_id = account['dolphin_profile_id']
        if any(str(a.get('dolphin_profile_id', '')) == str(source_id) for a in accounts):
            raise ActionError('This Dolphin profile is already imported')
        username = account['username']
        reserved = getattr(self.am, 'reserved_profile_names', lambda: {name_key(a['username']) for a in accounts})()
        if name_key(username) in reserved:
            raise ActionError('Username already exists; choose another username')
        path = get_cookies_file_path(self.e.config, username)
        if cookies and path.exists():
            raise ActionError('Saved cookies already exist under this username')
        accounts.append(account)
        self._sync_folders(accounts)
        created = False
        portable_path = None
        try:
            if cookies:
                store_cookies(self.e.config, username, cookies)
                created = True
            if portable:
                from xgenius.portable_session import store_session, session_path
                portable_path = session_path(self.e.config, username)
                store_session(self.e.config, username, portable, pending=True)
            self.am.save_accounts(accounts)
        except Exception:
            if created:
                path.unlink(missing_ok=True)
            if portable_path:
                portable_path.unlink(missing_ok=True)
            raise
        self._log(f"Dolphin profile {source_id} imported as @{username}; X cookies: {len(cookies)}")
        self.e.notify()
        return {'id': source_id, 'username': username, 'name': account['dolphin_name'],
                'status': 'added', 'cookies': len(cookies), 'all_cookies': len(portable or cookies), 'warnings': warnings}

    async def import_dolphin_all(self, token: str, job, password: str = '') -> dict:
        """Enumerate every cursor page, then import each accessible profile once."""
        from xgenius.profile_archive import unique_name
        client = DolphinClient(token, cancelled=job.cancelled)
        report, rows, seen = [], [], set()
        try:
            job.update(phase='listing')
            pages = client.profile_pages()

            def next_page():
                return next(pages, None)

            while not job.cancelled():
                page = await self.e.loop.run_in_executor(None, next_page)
                if page is None:
                    break
                items, total, _ = page
                for item in items:
                    number = profile_id(item['id'])
                    if number not in seen:
                        rows.append(item)
                        seen.add(number)
                job.update(total=max(len(rows), total if isinstance(total, int) else 0))
            if job.cancelled():
                return {'total': len(rows), 'report': report}
            job.update(total=len(rows), phase='importing')
            try:
                remote_folders = await self.e.loop.run_in_executor(None, client.folders)
            except DolphinError:
                remote_folders = {}
            for index, listed in enumerate(rows):
                if job.cancelled():
                    break
                number = profile_id(listed['id'])
                existing = self.am.load_accounts()
                imported = next((a for a in existing if str(a.get('dolphin_profile_id', '')) == str(number)), None)
                if imported:
                    report.append({'id': number, 'username': imported['username'], 'status': 'skipped',
                                   'message': 'Already imported'})
                else:
                    try:
                        warnings = []
                        try:
                            source = await self.e.loop.run_in_executor(None, client.get_profile, number, password)
                        except DolphinError as exc:
                            if exc.status == 401:
                                raise
                            # Even password-protected records remain visible in XAnty,
                            # with an explicit notice that their session is incomplete.
                            source = listed
                            warnings.append(f'Profile details unavailable: {exc}')
                        raw_group = remote_folders.get(str(source.get('folderId', source.get('folder', ''))), '')
                        group = re.sub(r'[/\\\x00-\x1f]', '-', raw_group).strip()[:64] if raw_group else 'Dolphin'
                        if group == '__none__' or not group:
                            group = 'Dolphin'
                        account, mapping_warnings = map_profile(source, folder=group)
                        warnings.extend(w for w in mapping_warnings if not w.startswith(
                            ('Dolphin fingerprint', 'Local storage and extensions')))
                        reserved = {a['username'].casefold() for a in existing}
                        reserved.update(getattr(self.am, 'reserved_profile_names', lambda: set())())
                        reserved.update(p.name.removeprefix('profile_').casefold()
                                        for p in self.e.config.browser_profiles_dir.glob('profile_*'))
                        cookies_root = self.e.config.base_dir / 'kook'
                        if cookies_root.is_dir():
                            reserved.update(p.name.lstrip('@').casefold() for p in cookies_root.iterdir())
                        account['username'] = unique_name(account['username'], reserved)
                        portable, cookie_warning = await self.e.loop.run_in_executor(
                            None, lambda: client.export_cookies(number, password, all_sites=True))
                        if cookie_warning:
                            warnings.append(cookie_warning)
                        try:
                            x_cookies = normalize_cookies(portable)
                        except CookieError:
                            x_cookies = []
                        account['auto_login'] = any(c['name'] == 'auth_token' for c in x_cookies)
                        account['import_warnings'] = list(warnings)
                        report.append(self._commit_dolphin(account, x_cookies, warnings, portable=portable))
                    except (DolphinError, ValueError, OSError) as exc:
                        report.append({'id': number, 'name': str(listed.get('name') or ''),
                                       'status': 'error', 'message': str(exc)})
                        if isinstance(exc, DolphinError) and exc.status == 401:
                            job.update(processed=index + 1, report=report)
                            raise
                job.update(processed=index + 1, report=report)
                self.e.notify()
            self._log(f"Dolphin: {sum(r['status'] == 'added' for r in report)} imported, "
                      f"{sum(r['status'] == 'skipped' for r in report)} skipped, "
                      f"{sum(r['status'] == 'error' for r in report)} errors")
            return {'total': len(rows), 'report': report}
        finally:
            client.close()

    async def import_dolphin_one(self, token: str, source_id, password: str = '',
                                 username: str = '', folder: str = 'Dolphin') -> dict:
        try:
            folder = folder_name(folder or 'Dolphin')
            account, cookies, warnings = await self.e.loop.run_in_executor(
                None, self._fetch_dolphin, token, source_id, password, username, folder)
            return self._commit_dolphin(account, cookies, warnings)
        except (DolphinError, FolderError, CookieError) as exc:
            raise ActionError(str(exc)) from exc

    async def import_dolphin_many(self, token: str, folder: str = 'Dolphin', limit: int = 100) -> dict:
        try:
            folder = folder_name(folder or 'Dolphin')
            if isinstance(limit, bool) or not str(limit).isdigit() or not 1 <= int(limit) <= 500:
                raise DolphinError('Import limit must be from 1 to 500')
            ids = await self.e.loop.run_in_executor(None, self._dolphin_ids, token, int(limit))
        except (DolphinError, FolderError) as exc:
            raise ActionError(str(exc)) from exc
        report = []
        for source_id in ids:
            existing = next((a for a in self.am.load_accounts() if
                             str(a.get('dolphin_profile_id', '')) == str(source_id)), None)
            if existing:
                report.append({'id': source_id, 'username': existing['username'],
                               'status': 'skipped', 'message': 'Already imported'})
                continue
            try:
                report.append(await self.import_dolphin_one(token, source_id, folder=folder))
            except ActionError as exc:
                report.append({'id': source_id, 'status': 'error', 'message': str(exc)})
        self._log(f"Dolphin import: {sum(r['status'] == 'added' for r in report)} added, "
                  f"{sum(r['status'] == 'skipped' for r in report)} skipped, "
                  f"{sum(r['status'] == 'error' for r in report)} errors")
        return {'total': len(ids), 'report': report}

    def edit_account(self, original: str, data: dict) -> None:
        new_username = (data.get("username") or "").strip()
        if not new_username:
            raise ActionError("Username cannot be empty!")
        previous = self._account(original)
        if previous is None:
            raise ActionError("Account not found")
        try:
            settings = browser_settings({**previous, **data})
            settings.update(user_agent_settings({**previous, **data}, self.e.config))
            settings.update(workspace_settings({**previous,**data}))
            metadata = metadata_values({k: data[k] for k in ('profile_status', 'favorite', 'tags', 'important', 'reminder_at', 'reminder_note', 'icon_text') if k in data})
        except ProfileSettingsError as exc:
            raise ActionError(str(exc)) from exc
        saved_rotation_url = rotation_url(data.get('proxy_rotation_url', previous.get('proxy_rotation_url')))
        moves = []
        if new_username != original:
            if self.am._session_is_busy(original) or (self._state(original) and self._state(original).browser):
                raise ActionError("Close the profile before renaming it")
            # Browser and cookie directories are keyed by username; move both when renaming.
            for root, prefix in ((self.e.config.browser_profiles_dir, 'profile_'),
                                 (self.e.config.base_dir / 'kook', '@')):
                root = root.resolve()
                source = (root / f'{prefix}{original}').resolve()
                target = (root / f'{prefix}{new_username}').resolve()
                if not source.is_relative_to(root) or not target.is_relative_to(root):
                    raise ActionError("Invalid profile name")
                if source.exists():
                    if target.exists():
                        raise ActionError("Profile data already exists under the new name")
                    moves.append((source, target))
        acs = self.am.load_accounts()
        if new_username != original and any(a["username"] == new_username for a in acs):
            raise ActionError(f"Username '{new_username}' is already taken!")
        found = False
        for a in acs:
            if a["username"] == original:
                a["username"] = new_username
                a["password"] = data.get("password", a.get("password", ""))
                a["proxy"] = (data.get("proxy") or "").strip()
                a['proxy_rotation_url'] = saved_rotation_url
                # Keep old data for compatibility; Chrome now supplies its own UA.
                a["user_agent"] = a.get("user_agent", "")
                a.update(settings)
                a.update(metadata)
                if "profile_name" in data:
                    a["profile_name"] = str(data.get("profile_name") or new_username).strip()
                if "notes" in data:
                    a["notes"] = str(data.get("notes") or "")
                a["group"] = (data.get("group") or "").strip()
                a["auth_token"] = (data.get("auth_token") or "").strip()
                a["ct0_token"] = (data.get("ct0_token") or "").strip()
                if "auto_login" in data:
                    if type(data["auto_login"]) is not bool:
                        raise ActionError("auto_login must be a boolean")
                    a["auto_login"] = data["auto_login"]
                a["headless"] = False
                found = True
                break
        if not found:
            raise ActionError("Account not found")
        self._sync_folders(acs)
        completed = []
        try:
            with ExitStack() as leases:
                if new_username != original:
                    for name in (original,new_username):
                        leases.enter_context(ProfileLease.acquire_path(profile_directory(self.e.config,name),create_profile=False))
                for source, target in moves:
                    source.rename(target)
                    completed.append((source, target))
                self.am.save_accounts(acs)
        except Exception:
            for source, target in reversed(completed):
                target.rename(source)
            raise
        if new_username != original and original in self.am.accounts:
            self.am.accounts[new_username] = self.am.accounts.pop(original)
            self.am.accounts[new_username].username = new_username
        st = self._state(new_username)
        if st:
            st.proxy_status = ""
            st.proxy_ip = ""
            st.proxy_error = ""
            st.proxy_location = {}
            st.proxy_location_error = ''
        self._log(f"Account updated: {original}" + (f" -> {new_username}" if new_username != original else ""))
        self.e.notify()

    def bulk_edit(self, usernames: List[str], group: Optional[str], proxies_text: Optional[str],
                  auto_login: Optional[bool] = None, settings: Optional[dict] = None,
                  metadata: Optional[dict] = None) -> int:
        change_group = group is not None
        metadata = metadata_values({} if metadata is None else metadata)
        settings = {} if settings is None else settings
        if not isinstance(settings, dict) or set(settings) - {
                "browser_language", "browser_timezone", "window_width", "window_height"}:
            raise ActionError("Invalid browser settings")
        proxies: List[str] = []
        if proxies_text is not None:
            proxies = [p.strip() for p in proxies_text.strip().splitlines() if p.strip()]
            if not proxies:
                raise ActionError("Proxy field is checked but contains no data.")
            if len(proxies) != 1 and len(proxies) != len(usernames):
                raise ActionError(
                    f"Incorrect number of proxies ({len(proxies)}). Provide 1 proxy for all, or {len(usernames)} (one per account).")
        if not change_group and not proxies and auto_login is None and not settings and not metadata:
            raise ActionError("No action selected. Choose folder, proxy, X auto-login or browser settings.")
        accounts = self.am.load_accounts()
        selected = set(usernames)
        if selected - {a["username"] for a in accounts}:
            raise ActionError("One or more selected profiles no longer exist.")
        resolved_settings = {}
        try:
            for account in accounts:
                if account["username"] in selected and settings:
                    resolved_settings[account["username"]] = browser_settings({**account, **settings})
        except ProfileSettingsError as exc:
            raise ActionError(str(exc)) from exc
        if auto_login is not None:
            try:
                apply_auto_login(accounts, usernames, auto_login)
            except ValueError as exc:
                raise ActionError(str(exc)) from exc
        n = 0
        for a in accounts:
            if a["username"] in usernames:
                a.update(metadata)
                if change_group:
                    a["group"] = group.strip()
                if proxies:
                    a["proxy"] = proxies[0] if len(proxies) == 1 else proxies[usernames.index(a["username"])]
                if settings:
                    a.update(resolved_settings[a["username"]])
                n += 1
        self._sync_folders(accounts)
        self.am.save_accounts(accounts)
        if proxies:
            for username in usernames:
                st = self._state(username)
                if st:
                    st.proxy_status = ""
                    st.proxy_ip = ""
                    st.proxy_error = ""
                    st.proxy_location = {}
                    st.proxy_location_error = ''
        self._log(f"Bulk edit applied to {n} account(s)")
        return n
