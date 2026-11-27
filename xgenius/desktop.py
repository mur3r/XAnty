"""Own the native window and the local HTTP server in one desktop process."""

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path

from xgenius.system_tray import SystemTray


class DesktopApi:
    def __init__(self):
        self._window = None
        self._tray = None
        self._hidden = False
        self._closing = threading.Event()
        self._window_lock = threading.Lock()

    def hide(self) -> bool:
        """Hide the window when the notification icon can bring it back."""
        with self._window_lock:
            if self._window is None or self._closing.is_set() or self._tray is None or not self._tray.available:
                return False
            if not self._hidden:
                self._window.hide()
                self._hidden = True
            return True

    def _show(self, only_if_hidden=False):
        with self._window_lock:
            window = self._window
            if window is None or self._closing.is_set() or (only_if_hidden and not self._hidden):
                return
            form = getattr(window, 'native', None)
            if str(getattr(form, 'WindowState', '')) == 'Minimized':
                window.restore()
            window.show()
            self._hidden = False

    def choose_folder(self, initial=''):
        """Open the OS folder picker only in response to an interface action."""
        with self._window_lock:
            window = self._window
            if window is None or self._closing.is_set():
                return None
        import webview
        try:
            directory = str(initial) if isinstance(initial, str) and len(initial) <= 4096 and Path(initial).is_dir() else ''
        except (OSError, ValueError):
            directory = ''
        kind = webview.FileDialog.FOLDER if hasattr(webview, 'FileDialog') else webview.FOLDER_DIALOG
        selected = window.create_file_dialog(kind, directory=directory, allow_multiple=False)
        return str(selected[0]) if selected else None

    def close(self):
        """Exit through the native window's shutdown path."""
        with self._window_lock:
            if self._window is not None and not self._closing.is_set():
                self._window.destroy()


def run_desktop() -> None:
    if sys.platform != "win32":
        raise RuntimeError("The XAnty desktop build currently supports Windows.")

    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("Install desktop dependencies: pip install -r requirements.txt") from exc

    from xgenius.config import application_home
    icon = Path(__file__).resolve().parent / 'web' / 'static' / 'assets' / 'app.ico'

    if hasattr(webview, 'settings'):
        webview.settings['ALLOW_DOWNLOADS'] = True

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    bridge = DesktopApi()
    closing = bridge._closing
    packaged = getattr(sys, 'frozen', False)
    state = {}
    started = time.monotonic()
    root = application_home()
    root.mkdir(parents=True, exist_ok=True)
    log_path = root / 'startup.log'
    try:
        if log_path.exists() and log_path.stat().st_size > 128 * 1024:
            log_path.write_text('', encoding='utf-8')
    except OSError:
        pass

    def record(message):
        try:
            with log_path.open('a', encoding='utf-8') as stream:
                stream.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} +{time.monotonic()-started:.2f}s {message}\n')
        except OSError:
            pass

    def loading_page(error=''):
        import base64
        from html import escape
        static = icon.parent.parent
        template = (static / 'startup.html').read_text(encoding='utf-8')
        logo = base64.b64encode((icon.parent / 'app-icon.png').read_bytes()).decode('ascii')
        shortcuts = (static / 'desktop-shortcuts.js').read_text(encoding='utf-8')
        return (template.replace('{{DESKTOP_SHORTCUTS}}', shortcuts)
                .replace('{{LOGO}}', logo).replace('{{ERROR}}', escape(error))
                .replace('{{MODE}}', 'error' if error else 'loading'))

    def startup_status(message):
        from html import escape
        bridge._window.html = loading_page().replace('Загружаем профили и настройки…', escape(message))
        try:
            bridge._window.evaluate_js('document.getElementById("startup-status").textContent=' + json.dumps(message))
        except Exception:
            pass

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = None
        updater = None
        state["loop"] = loop
        try:
            if closing.is_set():
                return
            if packaged:
                from xgenius.updates import UpdateManager
                updater = UpdateManager()
                record('update_check_started')
                restarting = loop.run_until_complete(updater.update_on_startup(closing, startup_status))
                record('update_check_finished ' + updater.status)
                if restarting:
                    bridge.close()
                    return
                if closing.is_set():
                    return
                startup_status('Загружаем профили и настройки…')
                from xgenius.config import default_base_dir, get_paths_from_base, read_saved_base_dir, save_base_dir
                if read_saved_base_dir() is None:
                    base = default_base_dir()
                    if all(path.is_file() for path in get_paths_from_base(base)):
                        save_base_dir(base)
            record('backend_import_started')
            from xgenius.web.server import WebApp
            if closing.is_set():
                return
            app = WebApp(loop, desktop_mode=True)
            state['app'] = app
            app.request_window_close = bridge.close

            def signal_ready(url):
                state["url"] = url
                record('backend_ready')
                if closing.is_set():
                    loop.create_task(app.shutdown())
                else:
                    bridge._window.load_url(url)
                    health = os.environ.pop('XANTY_UPDATE_HEALTH_FILE', '')
                    if health:
                        from xgenius import __version__
                        try:
                            destination = Path(health)
                            temporary = destination.with_suffix('.tmp')
                            temporary.write_text(json.dumps({'version': __version__, 'pid': os.getpid()}), encoding='utf-8')
                            os.replace(temporary, destination)
                        except OSError:
                            pass

            loop.run_until_complete(app.run_forever(on_ready=signal_ready, host="127.0.0.1",
                                                     port=0, launch_browser=False))
        except BaseException as exc:
            state["error"] = exc
            record(f'backend_error {type(exc).__name__}: {exc}')
            if not closing.is_set():
                try:
                    error_page = loading_page(str(exc))
                    # WebView2 may still be initializing and later reloads window.html.
                    bridge._window.html = error_page
                    bridge._window.load_html(error_page)
                except Exception:
                    pass
        finally:
            if updater is not None:
                try:
                    loop.run_until_complete(updater.shutdown())
                except Exception as exc:
                    record(f'update_shutdown_error {type(exc).__name__}: {exc}')
            if app is not None and not app._stop.is_set():
                try:
                    loop.run_until_complete(app.shutdown())
                except Exception:
                    pass
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            record('backend_stopped')

    worker = threading.Thread(target=run_server, name="xanty-local-server", daemon=True)
    tray = SystemTray(icon, bridge._show, bridge.close, lambda: bridge._show(only_if_hidden=True), record)
    bridge._tray = tray
    installer_mutex = None
    if packaged:
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        # Inno Setup checks for the mutex. Workspaces can still coexist.
        installer_mutex = kernel.CreateMutexW(None, False, 'Local\\XAnty.App.Running')
    try:
        storage = root / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        bridge._window = webview.create_window("XAnty", html=loading_page(), js_api=bridge,
                                              width=1500, height=920, min_size=(950, 620),
                                              background_color='#101014')
        bridge._window.events.shown += tray.start
        record('window_created')
        # Require the modern renderer; the deprecated MSHTML engine cannot render this UI.
        # pywebview starts this callback in a worker; the native GUI loop never waits for the backend.
        webview.start(worker.start, gui="edgechromium", private_mode=False, storage_path=str(storage), icon=str(icon))
    finally:
        closing.set()
        tray.stop()
        loop = state.get("loop")
        app = state.get("app")
        if worker.is_alive():
            if loop is not None and app is not None:
                try:
                    loop.call_soon_threadsafe(lambda: loop.create_task(app.shutdown()))
                except RuntimeError:
                    pass
            worker.join(timeout=25)
        if installer_mutex:
            kernel.CloseHandle(installer_mutex)
