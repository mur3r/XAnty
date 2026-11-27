"""
aiohttp-сервер веб-интерфейса: JSON API + WebSocket (живое состояние и логи) + статика.

Фазы приложения:
  setup — нет paths.json: пользователь указывает базовую папку;
  ready — движок создан, интерфейс работает.
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import uuid
from contextlib import ExitStack
from datetime import datetime
import webbrowser
from pathlib import Path
from typing import Any, Optional

from aiohttp import web

from xgenius import __version__
from xgenius.config import default_base_dir, get_paths_from_base, read_saved_base_dir, save_base_dir
from xgenius.process_utils import force_kill_chromedrivers
from xgenius.settings import BROWSER_APP_MODE, OPEN_BROWSER, WEB_HOST, WEB_PORT
from xgenius.web.package_response import PackageFileResponse
from xgenius.web.actions import ActionError, Actions
from xgenius.web.engine import Engine
from xgenius.jobs import JobManager
from xgenius.transfer_storage import export_directory, publish_export
from xgenius.profile_archive import ArchiveError, export_package, import_package, inspect_package
from xgenius.preferences import read_preferences, save_preferences
from xgenius.updates import UpdateError, UpdateManager
from xgenius.profile_leases import ProfileLease
from xgenius.extension_sets import ExtensionSetStore
from xgenius.profile_settings import workspace_settings
from xgenius.web.workspace_api import WorkspaceApiMixin

STATIC_DIR = Path(__file__).resolve().parent / "static"


class WebApp(WorkspaceApiMixin):
    def __init__(self, loop: asyncio.AbstractEventLoop, desktop_mode: bool = False):
        self.loop = loop
        self.desktop_mode = desktop_mode
        self.engine: Optional[Engine] = None
        self.actions: Optional[Actions] = None
        self.setup_message = ""
        self._stop = asyncio.Event()
        self.jobs = JobManager()
        self._transfer_storage = None
        self.updates = UpdateManager()
        self.request_window_close = None
        self._active_profile_requests = 0

    # ------------------------------------------------------------------ lifecycle
    @property
    def phase(self) -> str:
        return "ready" if self.engine is not None else "setup"

    def start_engine(self) -> None:
        if self.engine is None:
            self.engine = Engine(self.loop)
            self.actions = Actions(self.engine)

    def state_payload(self) -> dict:
        if self.engine is not None:
            payload = self.engine.snapshot()
            if self.actions:
                for account in payload.get('accounts', []):
                    account['opening'] = account['username'] in self.actions._busy
                    account['closing'] = account['username'] in self.actions._closing
            return payload
        base = read_saved_base_dir()
        return {
            "phase": "setup",
            "version": __version__,
            "base_dir": str(base) if base else "",
            "suggested_base_dir": str(default_base_dir()),
            "setup_message": self.setup_message,
        }

    async def shutdown(self):
        await self.updates.shutdown()
        await self.jobs.shutdown()
        if self.engine is not None:
            try:
                await self.engine.shutdown()
            except Exception as e:
                print(f"shutdown error: {e}")
        self._stop.set()
        if self._transfer_storage and not any(j.status == 'running' for j in self.jobs.jobs.values()):
            self._transfer_storage.cleanup()

    def transfer_directory(self) -> Path:
        self._require_engine()
        if self._transfer_storage is None:
            self._transfer_storage = tempfile.TemporaryDirectory(prefix='.xanty-transfer-', dir=self.engine.config.base_dir)
        return Path(self._transfer_storage.name)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _json(data: Any, status: int = 200) -> web.Response:
        return web.json_response(data, status=status, dumps=lambda d: json.dumps(d, ensure_ascii=False, default=str))

    def _require_engine(self) -> Actions:
        if self.actions is None:
            raise ActionError("Движок ещё не запущен: укажите базовую папку на экране Setup.")
        return self.actions

    @staticmethod
    def _usernames(body: dict) -> list:
        names = body.get("usernames") or ([body["username"]] if body.get("username") else [])
        if not names:
            raise ActionError("No accounts selected!")
        return list(dict.fromkeys(str(n) for n in names))

    # ------------------------------------------------------------------ handlers
    async def index(self, request):
        # Страница живёт в /static/, чтобы её относительные пути (style.css, app.js)
        # работали и при открытии файла напрямую, без сервера.
        raise web.HTTPFound("/static/index.html")

    async def api_state(self, request):
        return self._json(self.state_payload())

    async def api_preferences(self, request):
        if request.method == 'GET':
            return self._json(read_preferences())
        try:
            prefs = save_preferences(await request.json())
            return self._json(prefs)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc

    async def api_updates(self, request):
        return self._json(self.updates.snapshot())

    async def api_release_history(self, request):
        return self._json({'releases': self.updates.release_notes.history()})

    async def api_release_notes_seen(self, request):
        body = await request.json()
        self.updates.release_notes.acknowledge(body.get('version'))
        return self._json(self.updates.snapshot())

    async def api_release_notes_open(self, request):
        if self.desktop_mode:
            import webview
            if webview.windows:
                await asyncio.to_thread(webview.windows[0].maximize)
        return self._json({'ok': True})

    async def api_update_check(self, request):
        body = await request.json() if request.can_read_body else {}
        return self._json(await self.updates.check(automatic=body.get('automatic') is True))

    async def api_update_download(self, request):
        return self._json(self.updates.start_download(), status=202)

    def require_update_idle(self):
        if self.actions and any(not task.done() for task in getattr(self.actions, '_proxy_rotations', {}).values()):
            raise UpdateError('Wait for proxy rotation to finish before installing the update.')
        if self._active_profile_requests:
            raise UpdateError('Wait for profile operations and transfers to finish before installing the update.')
        if self.engine:
            manager = self.engine.account_manager
            if any(st.browser for st in manager.accounts.values()):
                raise UpdateError('Close all profiles before installing the update.')
        if self.actions and (self.actions._busy or self.actions._closing or self.actions._transferring):
            raise UpdateError('Close all profiles and wait for current actions before installing the update.')
        if self.actions and any(not task.done() for task in getattr(self.actions, '_launch_tasks', set())):
            raise UpdateError('Close all profiles and wait for current actions before installing the update.')
        if any(job.status == 'running' for job in self.jobs.jobs.values()):
            raise UpdateError('Wait for the profile transfer to finish before installing the update.')

    async def api_update_install(self, request):
        if not self.desktop_mode or not self.request_window_close:
            raise UpdateError('Install updates from the XAnty desktop window.')
        self.require_update_idle()
        result = await self.updates.install()
        self.loop.call_later(0.8, self.request_window_close)
        return self._json(result, status=202)

    async def api_setup(self, request):
        body = await request.json()
        raw = (body.get("base_dir") or "").strip()
        if not raw:
            raise ActionError("Укажите путь к базовой папке")
        base = Path(raw)
        if not base.exists():
            if body.get("create"):
                base.mkdir(parents=True, exist_ok=True)
            else:
                raise ActionError(f"Папка не найдена: {base}. Отметьте «создать», чтобы создать её.")
        chrome, driver = get_paths_from_base(base)
        warnings = []
        if not chrome.exists():
            warnings.append(f"Не найден {chrome}")
        if not driver.exists():
            warnings.append(f"Не найден {driver}")
        save_base_dir(base)
        self.setup_message = "; ".join(warnings)
        self.start_engine()
        return self._json({"ok": True, "warnings": warnings, "phase": self.phase})

    async def api_logs(self, request):
        if self.engine is None:
            return self._json({"seq": 0, "lines": []})
        seq, lines = self.engine.logs_since(int(request.query.get("since", "0")))
        return self._json({"seq": seq, "lines": lines})

    async def api_help(self, request):
        return web.FileResponse(STATIC_DIR / "help.txt")

    async def api_sysmon(self, request):
        """Нагрузка сервера: последний замер, история для графиков, разбивка по аккаунтам."""
        if self.engine is None:
            return self._json({"enabled": False, "info": {}, "latest": {}, "history": []})
        return self._json(self.engine.sysmon.payload())

    async def api_sysmon_csv(self, request):
        """Скачать сегодняшний CSV мониторинга (kind=accounts — разбивку по аккаунтам)."""
        if self.engine is None:
            raise ActionError("Движок ещё не запущен")
        info = self.engine.sysmon.info
        path = Path(info["accounts_csv"] if request.query.get("kind") == "accounts" else info["csv"])
        if not path.exists():
            raise ActionError(f"Файл ещё не создан: {path}")
        return web.FileResponse(path, headers={"Content-Disposition": f'attachment; filename="{path.name}"'})

    async def api_shutdown(self, request):
        self.loop.create_task(self.shutdown())
        return self._json({"ok": True})

    async def api_accounts_add(self, request):
        self._require_engine().add_account(await request.json())
        return self._json({"ok": True})

    async def api_accounts_import(self, request):
        added, skipped = self._require_engine().import_accounts((await request.json()).get("text", ""))
        return self._json({"ok": True, "added": added, "skipped": skipped})

    async def api_dolphin_preview(self, request):
        body = await request.json()
        result = await self._require_engine().preview_dolphin(
            body.get('token', ''), body.get('id'), body.get('password', ''),
            body.get('username', ''), body.get('folder', 'Dolphin'))
        return self._json({'ok': True, **result})

    async def api_dolphin_import_one(self, request):
        body = await request.json()
        result = await self._require_engine().import_dolphin_one(
            body.get('token', ''), body.get('id'), body.get('password', ''),
            body.get('username', ''), body.get('folder', 'Dolphin'))
        return self._json({'ok': True, **result})

    async def api_dolphin_import_many(self, request):
        body = await request.json()
        result = await self._require_engine().import_dolphin_many(
            body.get('token', ''), body.get('folder', 'Dolphin'), body.get('limit', 100))
        return self._json({'ok': True, **result})

    async def api_dolphin_import_all(self, request):
        actions = self._require_engine()
        body = await request.json()
        token = body.get('token', '')
        if not isinstance(token, str) or not token.strip() or any(c.isspace() for c in token.strip()):
            raise ActionError('Enter a Dolphin API token')
        password = body.get('password', '')
        if not isinstance(password, str):
            raise ActionError('Invalid profile password')
        try:
            job = self.jobs.start('dolphin', lambda job: actions.import_dolphin_all(token, job, password=password))
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        return self._json(job.snapshot(), status=202)

    async def api_jobs(self, request):
        return self._json({'jobs': self.jobs.snapshots()})

    def _job(self, request):
        try:
            return self.jobs.get(request.match_info['job_id'])
        except ValueError as exc:
            raise ActionError(str(exc)) from exc

    async def api_job(self, request):
        return self._json(self._job(request).snapshot())

    async def api_job_cancel(self, request):
        job = self._job(request)
        job.cancel_event.set()
        return self._json(job.snapshot())

    async def api_job_report(self, request):
        job = self._job(request)
        response = self._json(job.snapshot())
        response.headers['Content-Disposition'] = f'attachment; filename="XAnty-{job.kind}-report.json"'
        response.headers['Cache-Control'] = 'no-store'
        return response

    async def api_profile_export(self, request):
        actions = self._require_engine()
        body = await request.json()
        accounts = actions.am.load_accounts()
        privacy = body.get('privacy')
        from xgenius.profile_archive import _privacy_policy
        _privacy_policy(privacy)
        names = {a['username'] for a in accounts} if body.get('all') else set(self._usernames(body))
        known = {a['username'] for a in accounts}
        if not names or not names.issubset(known):
            raise ActionError('No profiles to export')
        for name in names:
            state = actions.am.accounts.get(name)
            if name in actions._busy or name in actions._closing or name in actions._transferring or name in actions._profile_operations or (state and state.browser):
                raise ActionError('Close the selected profiles before exporting')
        selected = [a for a in accounts if a['username'] in names]
        save_directory = export_directory(body.get('export_directory'))
        remember_directory = 'export_directory' in body
        filename = f'XAnty-profiles-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}.xanty'
        destination = (save_directory if save_directory else self.transfer_directory()) / filename
        folders = self.engine.folders.list() if body.get('all') else []

        async def worker(job):
            actions._transferring.update(names)
            job.update(phase='exporting', total=len(selected))
            staged = None
            try:
                if save_directory:
                    def create_staging():
                        with tempfile.NamedTemporaryFile(prefix='.xanty-export-', suffix='.tmp', dir=save_directory, delete=False) as stream:
                            return Path(stream.name)
                    staged = await asyncio.to_thread(create_staging)
                output = staged if staged else destination
                def export_locked():
                    with ExitStack() as leases:
                        for name in names:
                            leases.enter_context(ProfileLease.acquire(self.engine.config,name))
                        return export_package(self.engine.config, selected, output, job.update,job.cancelled,folders,privacy)
                result = await asyncio.to_thread(export_locked)
                if staged:
                    job.update(phase='saving_export')
                    result['saved_path'] = await asyncio.to_thread(publish_export, staged, destination, job.cancelled)
                    result['filename'] = filename
                if remember_directory:
                    try:
                        save_preferences({'export_directory': str(save_directory) if save_directory else ''})
                    except (OSError, ValueError):
                        result['report'][0].setdefault('warnings', []).append('The package was saved, but the last folder could not be remembered.')
                        job.update(report=result['report'])
                job.file_path = destination
                return result
            finally:
                if staged:
                    staged.unlink(missing_ok=True)
                actions._transferring.difference_update(names)

        try:
            job = self.jobs.start('export', worker)
        except ValueError as exc:
            raise ActionError(str(exc)) from exc
        return self._json(job.snapshot(), status=202)

    async def api_profile_download(self, request):
        job = self._job(request)
        if job.status != 'completed' or not job.file_path or not job.file_path.is_file():
            raise ActionError('Profile package is not ready')
        return PackageFileResponse(job.file_path, headers={
            'Content-Type': 'application/octet-stream',
            'Content-Disposition': f'attachment; filename="{job.file_path.name}"',
            'Cache-Control': 'no-store',
        })

    async def api_profile_import(self, request):
        actions = self._require_engine()
        if any(j.status == 'running' for j in self.jobs.jobs.values()):
            raise ActionError('Another transfer operation is running')
        reader = await request.multipart()
        source = self.transfer_directory() / f'upload-{uuid.uuid4().hex}.xanty'
        duplicates, received, expected_size, count = 'rename', False, None, 0
        try:
            async for part in reader:
                if part.name == 'duplicates':
                    duplicates = await part.text()
                elif part.name == 'file_size':
                    value = await part.text()
                    if not value.isascii() or not value.isdecimal() or len(value) > 12 or not 0 < int(value) <= 64 * 1024 ** 3:
                        raise ActionError('Invalid profile package upload size')
                    expected_size = int(value)
                elif part.name == 'file' and not received:
                    received = True
                    count = 0
                    with source.open('wb') as target:
                        while True:
                            chunk = await part.read_chunk(1024 * 1024)
                            if not chunk:
                                break
                            count += len(chunk)
                            if count > 64 * 1024 ** 3:
                                raise ActionError('Profile package exceeds the 64 GB size limit')
                            await asyncio.to_thread(target.write, chunk)
                else:
                    await part.release()
            if not received:
                raise ActionError('Choose an XAnty profile package')
            if expected_size is not None and count != expected_size:
                raise ActionError('Profile package upload is incomplete. Choose the original file and try again.')
            if duplicates not in ('rename', 'skip'):
                raise ActionError('Choose rename or skip for existing profiles')
            preview = await asyncio.to_thread(inspect_package, source)

            async def worker(job):
                job.update(phase='importing', total=preview['total'])
                try:
                    result = await asyncio.to_thread(import_package, self.engine.config, actions.am,
                                                    self.engine.folders, source, duplicates, job.update,
                                                    job.cancelled, getattr(actions.am, '_data_lock', None))
                    self.engine.notify()
                    return result
                finally:
                    source.unlink(missing_ok=True)

            job = self.jobs.start('import', worker)
            return self._json(job.snapshot(), status=202)
        except Exception:
            source.unlink(missing_ok=True)
            raise

    async def api_accounts_get(self, request):
        return self._json(self._require_engine().get_account(request.match_info["username"]))

    async def api_cookies_export(self, request):
        cookies = await self._require_engine().export_cookies(request.match_info["username"])
        return self._json({"cookies": cookies}, status=200)

    async def api_cookies_import(self, request):
        body = await request.json()
        count = self._require_engine().import_cookies(request.match_info["username"], body.get("cookies"))
        return self._json({"ok": True, "imported": count})

    async def api_accounts_edit(self, request):
        self._require_engine().edit_account(request.match_info["username"], await request.json())
        return self._json({"ok": True})

    async def api_user_agent(self, request):
        from xgenius.user_agent import browser_identity
        actions = self._require_engine()
        return self._json(await actions._run_profile_worker(browser_identity, actions.e.config))

    async def api_user_agent(self, request):
        from xgenius.user_agent import browser_identity
        actions = self._require_engine()
        return self._json(await actions._run_profile_worker(browser_identity, actions.e.config))

    async def api_profile_tool(self,request):
        if request.method == 'GET' and request.match_info['tool'] not in ('cookies', 'user_agent'):
            raise web.HTTPMethodNotAllowed(request.method,['POST'])
        body = await request.json() if request.method == 'POST' and request.can_read_body else {}
        result = await self._require_engine().profile_tool(request.match_info['username'],request.match_info['tool'],body)
        return self._json({'ok':True,**result})

    async def api_extension_sets(self,request):
        store = ExtensionSetStore(self._require_engine().e.config)
        if request.method == 'GET':
            return self._json({'sets':await self.actions._run_profile_worker(store.list)})
        body = await request.json()
        if request.method == 'DELETE':
            await self.actions._run_profile_worker(store.delete,body.get('id'))
            return self._json({'ok':True})
        result = await self.actions._run_profile_worker(store.save,body.get('name'),body.get('directories'),body.get('id'))
        return self._json({'ok':True,'set':result})

    async def api_accounts_delete(self, request):
        body = await request.json()
        n = self._require_engine().delete(self._usernames(body), body.get('retention_days', 30), body.get('confirmation'))
        return self._json({"ok": True, "deleted": n})

    async def api_metadata(self, request):
        actions = self._require_engine()
        body = await request.json()
        n = actions.am.update_profile_metadata(self._usernames(body), body.get('metadata'))
        self.engine.notify()
        return self._json({'ok': True, 'updated': n})

    async def api_history(self, request):
        events = self._require_engine().am.profile_history(request.query.get('username'))
        return self._json({'events': events})

    async def api_trash(self, request):
        return self._json({'profiles': self._require_engine().am.trash_rows()})

    async def api_trash_action(self, request):
        actions = self._require_engine()
        body = await request.json()
        names = self._usernames(body)
        if any(u in actions._busy or u in actions._closing or u in actions._transferring for u in names):
            raise ActionError('Wait for the profile to finish opening or closing')
        operation = request.match_info['operation']
        if operation == 'restore':
            n = actions.am.restore_profiles(names)
            actions._sync_folders(actions.am.load_accounts())
        elif operation == 'retention':
            n = actions.am.set_trash_retention(names, body.get('retention_days'))
        elif operation == 'purge':
            actions.confirm_important_delete(names,body.get('confirmation'),trashed=True)
            n = await self.loop.run_in_executor(None, actions.am.purge_trash, names)
        else:
            raise web.HTTPNotFound()
        self.engine.notify()
        return self._json({'ok': True, 'updated': n})

    async def api_bulk_edit(self, request):
        body = await request.json()
        n = self._require_engine().bulk_edit(self._usernames(body), body.get("group"), body.get("proxies"),
                                             body.get("auto_login"), body.get("settings"), body.get('metadata'))
        return self._json({"ok": True, "updated": n})

    async def api_auto_login(self, request):
        body = await request.json()
        count = self._require_engine().set_auto_login(self._usernames(body), body.get("enabled"))
        return self._json({"ok": True, "updated": count, "enabled": body["enabled"]})

    async def api_folder_create(self, request):
        body = await request.json()
        name = self._require_engine().create_folder(body.get("name", ""), body.get("usernames") or [])
        return self._json({"ok": True, "name": name})

    async def api_folder_rename(self, request):
        body = await request.json()
        name = self._require_engine().rename_folder(request.match_info["name"], body.get("name", ""))
        return self._json({"ok": True, "name": name})

    async def api_folder_delete(self, request):
        moved = self._require_engine().delete_folder(request.match_info["name"])
        return self._json({"ok": True, "unfiled": moved})

    async def api_accounts_move(self, request):
        body = await request.json()
        moved = self._require_engine().move_to_folder(self._usernames(body), body.get("folder", ""))
        return self._json({"ok": True, "moved": moved})

    async def api_proxy_check(self, request):
        result = await self._require_engine().check_account_proxy(request.match_info["username"])
        return self._json(result)

    async def api_proxy_rotate(self, request):
        result = await self._require_engine().rotate_account_proxy(request.match_info['username'])
        return self._json(result)

    async def api_action(self, request):
        """POST /api/actions/{name} — login, close, view, reset_errors."""
        name = request.match_info["name"]
        body = await request.json() if request.can_read_body else {}
        a = self._require_engine()
        if name == "login":
            return self._json({"ok": True, "started": a.start_login(self._usernames(body))})
        if name == "close":
            n = a.close_all() if body.get("all") else a.close(self._usernames(body))
            return self._json({"ok": True, "closed": n})
        if name == "view":
            await a.view(body.get("username", ""))
            return self._json({"ok": True})
        if name == "reset_errors":
            return self._json({"ok": True, "reset": a.reset_errors()})
        raise ActionError(f"Unknown action: {name}")

    async def ws_handler(self, request):
        ws = web.WebSocketResponse(heartbeat=20)
        await ws.prepare(request)
        last_state = None
        last_seq = 0
        last_sysmon = 0
        try:
            while not ws.closed and not self._stop.is_set():
                state = self.state_payload()
                encoded = json.dumps(state, ensure_ascii=False, default=str, sort_keys=True)
                if encoded != last_state:
                    await ws.send_str(json.dumps({"type": "state", "data": state}, ensure_ascii=False, default=str))
                    last_state = encoded
                if self.engine is not None:
                    seq, lines = self.engine.logs_since(last_seq)
                    if lines:
                        await ws.send_str(json.dumps({"type": "logs", "seq": seq, "lines": lines}, ensure_ascii=False))
                    last_seq = seq
                    sm = self.engine.sysmon
                    if sm.seq != last_sysmon and sm.latest:
                        # Замер нагрузки идёт отдельным сообщением: состояние таблицы от него не меняется
                        await ws.send_str(json.dumps({"type": "sysmon", "data": sm.latest}, ensure_ascii=False))
                        last_sysmon = sm.seq
                    await self.engine.wait_change(0.7)
                else:
                    await asyncio.sleep(0.7)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception as e:
            print(f"ws error: {e}")
        return ws

    # ------------------------------------------------------------------ app wiring
    @web.middleware
    async def local_window_only(self, request, handler):
        """Reject cross-origin access to the desktop window's localhost API and WebSocket."""
        hostname = request.headers.get("Host", "").split(":", 1)[0].lower()
        if hostname not in {"127.0.0.1", "localhost"}:
            raise web.HTTPForbidden()
        origin = request.headers.get("Origin")
        if origin and origin != f"{request.scheme}://{request.host}":
            raise web.HTTPForbidden()
        if request.headers.get("Sec-Fetch-Site") == "cross-site":
            raise web.HTTPForbidden()
        return await handler(request)

    @web.middleware
    async def errors_middleware(self, request, handler):
        profile_request = (request.method not in ('GET', 'HEAD') and request.path.startswith(
            ('/api/accounts', '/api/folders', '/api/actions', '/api/profiles', '/api/dolphin', '/api/trash', '/api/workspace', '/api/window-sets')))
        if profile_request:
            self._active_profile_requests += 1
        try:
            if request.method not in ('GET','HEAD') and self.actions is not None and self.actions._stopping:
                raise ActionError('Application is shutting down')
            if profile_request and self.engine is not None and (
                    getattr(self.engine,'_backup_running',False) or getattr(self.actions,'_version_switching',False)):
                raise ActionError('Wait for the backup or Chromium version switch to finish.')
            if (self.updates.installing and request.method not in ('GET', 'HEAD')
                    and not request.path.startswith('/api/updates')):
                raise UpdateError('The update is being installed. Please wait for XAnty to restart.')
            if request.method not in ('GET', 'HEAD') and request.path.startswith(('/api/accounts', '/api/folders', '/api/actions', '/api/trash', '/api/window-sets')):
                if any(j.status == 'running' and j.kind in ('import', 'export') for j in self.jobs.jobs.values()):
                    raise ActionError('Profile transfer is running; wait for it to finish')
            return await handler(request)
        except (ActionError, ArchiveError, UpdateError, ValueError) as e:
            return self._json({"ok": False, "error": str(e)}, status=400)
        except web.HTTPException:
            raise
        except Exception as e:
            if self.engine is not None:
                self.engine.logger.error(f"API error {request.path}: {type(e).__name__}: {e}")
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, status=500)
        finally:
            if profile_request:
                self._active_profile_requests -= 1

    def build(self) -> web.Application:
        middlewares = [self.local_window_only, self.errors_middleware] if self.desktop_mode else [self.errors_middleware]
        app = web.Application(middlewares=middlewares, client_max_size=64 * 1024 ** 3)
        app.add_routes([
            web.get("/", self.index),
            web.get("/ws", self.ws_handler),
            web.get("/api/state", self.api_state),
            web.get("/api/browser/user-agent", self.api_user_agent),
            web.get("/api/preferences", self.api_preferences),
            web.put("/api/preferences", self.api_preferences),
            web.get('/api/updates', self.api_updates),
            web.get('/api/updates/history', self.api_release_history),
            web.post('/api/updates/notes/seen', self.api_release_notes_seen),
            web.post('/api/updates/notes/open', self.api_release_notes_open),
            web.post('/api/updates/check', self.api_update_check),
            web.post('/api/updates/download', self.api_update_download),
            web.post('/api/updates/install', self.api_update_install),
            web.post("/api/setup", self.api_setup),
            web.get("/api/logs", self.api_logs),
            web.get("/api/help", self.api_help),
            web.get("/api/sysmon", self.api_sysmon),
            web.get("/api/sysmon/csv", self.api_sysmon_csv),
            web.post("/api/shutdown", self.api_shutdown),
            web.post("/api/accounts", self.api_accounts_add),
            web.post("/api/accounts/import", self.api_accounts_import),
            web.post("/api/dolphin/preview", self.api_dolphin_preview),
            web.post("/api/dolphin/import-one", self.api_dolphin_import_one),
            web.post("/api/dolphin/import-many", self.api_dolphin_import_many),
            web.post("/api/dolphin/import-all", self.api_dolphin_import_all),
            web.get("/api/jobs", self.api_jobs),
            web.get("/api/jobs/{job_id}", self.api_job),
            web.post("/api/jobs/{job_id}/cancel", self.api_job_cancel),
            web.get("/api/jobs/{job_id}/report", self.api_job_report),
            web.post("/api/profiles/export", self.api_profile_export),
            web.post("/api/profiles/import", self.api_profile_import),
            web.get("/api/profiles/download/{job_id}", self.api_profile_download),
            web.post("/api/accounts/delete", self.api_accounts_delete),
            web.get('/api/extension-sets', self.api_extension_sets),
            web.post('/api/extension-sets', self.api_extension_sets),
            web.delete('/api/extension-sets', self.api_extension_sets),
            web.get('/api/accounts/{username}/tools/{tool}', self.api_profile_tool),
            web.post('/api/accounts/{username}/tools/{tool}', self.api_profile_tool),
            web.patch('/api/accounts/metadata', self.api_metadata),
            web.get('/api/history', self.api_history),
            web.get('/api/workspace', self.api_workspace),
            web.get('/api/workspace/chromium/available', self.api_chromium_available),
            web.post('/api/workspace/chromium/install', self.api_chromium_install),
            web.post('/api/workspace/chromium/select', self.api_chromium_select),
            web.delete('/api/workspace/chromium', self.api_chromium_select),
            web.get('/api/workspace/backups', self.api_backups),
            web.put('/api/workspace/backups', self.api_backups),
            web.post('/api/workspace/backups/run', self.api_backup_run),
            web.get('/api/workspace/storage', self.api_storage),
            web.post('/api/workspace/storage', self.api_storage),
            web.get('/api/window-sets', self.api_window_sets),
            web.post('/api/window-sets', self.api_window_sets),
            web.delete('/api/window-sets', self.api_window_sets),
            web.post('/api/window-sets/{set_id}/open', self.api_window_set_open),
            web.get('/api/trash', self.api_trash),
            web.post('/api/trash/{operation}', self.api_trash_action),
            web.post("/api/accounts/bulk_edit", self.api_bulk_edit),
            web.post("/api/accounts/auto_login", self.api_auto_login),
            web.post("/api/accounts/move", self.api_accounts_move),
            web.post("/api/folders", self.api_folder_create),
            web.put("/api/folders/{name}", self.api_folder_rename),
            web.delete("/api/folders/{name}", self.api_folder_delete),
            web.post("/api/accounts/{username}/proxy/check", self.api_proxy_check),
            web.post('/api/accounts/{username}/proxy/rotate', self.api_proxy_rotate),
            web.get("/api/accounts/{username}/cookies", self.api_cookies_export),
            web.post("/api/accounts/{username}/cookies", self.api_cookies_import),
            web.get("/api/accounts/{username}", self.api_accounts_get),
            web.get("/api/browser/user-agent", self.api_user_agent),
            web.put("/api/accounts/{username}", self.api_accounts_edit),
            web.post("/api/actions/{name}", self.api_action),
            web.static("/static", STATIC_DIR),
        ])
        return app

    async def run_forever(self, on_ready=None, host=None, port=None, launch_browser=None):
        if read_saved_base_dir() is not None:
            try:
                self.start_engine()
            except Exception as e:
                print(f"engine start failed, showing setup: {e}")
                self.setup_message = str(e)
        runner = web.AppRunner(self.build())
        await runner.setup()
        host = host or WEB_HOST
        port = WEB_PORT if port is None else port
        site = web.TCPSite(runner, host, port)
        await site.start()
        actual_port = site._server.sockets[0].getsockname()[1]
        url = f"http://{host}:{actual_port}/"
        print(f"X-Genius {__version__} web UI: {url}")
        if on_ready is not None:
            on_ready(url)
        if (OPEN_BROWSER if launch_browser is None else launch_browser):
            open_ui(url)
        try:
            await self._stop.wait()
        finally:
            await runner.cleanup()


def open_ui(url: str) -> None:
    """Открывает интерфейс: окно chrome --app (без адресной строки) из Bro/chrome.exe, иначе — браузер по умолчанию."""
    base = read_saved_base_dir()
    if BROWSER_APP_MODE and base is not None:
        chrome, _ = get_paths_from_base(base)
        if chrome.exists():
            try:
                profile = base / "webui_profile"
                subprocess.Popen([str(chrome), f"--app={url}", f"--user-data-dir={profile}",
                                  "--no-first-run", "--no-default-browser-check", "--window-size=1500,920"],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception as e:
                print(f"chrome --app launch failed: {e}")
    try:
        webbrowser.open(url)
    except Exception as e:
        print(f"browser open failed: {e}")


def serve() -> None:
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app = WebApp(loop)
    try:
        loop.run_until_complete(app.run_forever())
    except KeyboardInterrupt:
        print("Application terminated by user")
        try:
            loop.run_until_complete(app.shutdown())
        except Exception:
            pass
    finally:
        print("Final cleanup...")
        loop.close()
        sys.exit(0)
