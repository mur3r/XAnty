"""Own the native window and the local HTTP server in one desktop process."""

import asyncio
import json
import os
import sys
import threading
import time
from pathlib import Path


class DesktopApi:
    def __init__(self):
        self._window = None

    def close(self):
        """Called by the Exit button in the native window."""
        if self._window is not None:
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
    closing = threading.Event()
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
        return (template.replace('{{LOGO}}', logo).replace('{{ERROR}}', escape(error))
                .replace('{{MODE}}', 'error' if error else 'loading'))

    bridge = DesktopApi()
    if getattr(sys, 'frozen', False):
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.restype = wintypes.HANDLE
        # Presence is enough for Inno Setup; independent workspaces may still coexist.
        state['installer_mutex'] = kernel.CreateMutexW(None, False, 'Local\\XAnty.App.Running')

    def startup_status(message):
        from html import escape
        page = loading_page().replace('Загружаем профили и настройки…', escape(message))
        bridge._window.html = page
        try:
            bridge._window.evaluate_js('document.getElementById("startup-status").textContent=' + json.dumps(message))
        except Exception:
            pass

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = None
        state["loop"] = loop
        try:
            if getattr(sys, 'frozen', False):
                from xgenius.updates import UpdateManager
                updater = UpdateManager()
                state['startup_updater'] = updater
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
                            Path(health).write_text(json.dumps({'version': __version__, 'pid': os.getpid()}), encoding='utf-8')
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
            updater = state.get('startup_updater')
            if updater is not None:
                loop.run_until_complete(updater.shutdown())
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
    try:
        storage = root / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        bridge._window = webview.create_window("XAnty", html=loading_page(), js_api=bridge,
                                              width=1500, height=920, min_size=(950, 620),
                                              background_color='#101014')
        record('window_created')
        # Require the modern renderer; the deprecated MSHTML engine cannot render this UI.
        # pywebview starts this callback in a worker; the native GUI loop never waits for the backend.
        webview.start(worker.start, gui="edgechromium", private_mode=False, storage_path=str(storage), icon=str(icon))
    finally:
        closing.set()
        loop = state.get("loop")
        app = state.get("app")
        if loop is not None and app is not None and worker.is_alive():
            try:
                loop.call_soon_threadsafe(lambda: loop.create_task(app.shutdown()))
            except RuntimeError:
                pass
            worker.join(timeout=25)
