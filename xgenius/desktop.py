"""Own the native window and the local HTTP server in one desktop process."""

import asyncio
import sys
import threading
from pathlib import Path


class DesktopApi:
    def __init__(self):
        self.window = None

    def close(self):
        """Called by the Exit button in the native window."""
        if self.window is not None:
            self.window.destroy()


def run_desktop() -> None:
    if sys.platform != "win32":
        raise RuntimeError("The XAnty desktop build currently supports Windows.")

    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("Install desktop dependencies: pip install -r requirements.txt") from exc

    from xgenius.config import application_home
    from xgenius.web.server import WebApp

    icon = Path(__file__).resolve().parent / 'web' / 'static' / 'assets' / 'app.ico'

    if hasattr(webview, 'settings'):
        webview.settings['ALLOW_DOWNLOADS'] = True

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    ready = threading.Event()
    state = {}

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        app = WebApp(loop, desktop_mode=True)
        state["loop"] = loop
        state["app"] = app
        try:
            def signal_ready(url):
                state["url"] = url
                ready.set()

            loop.run_until_complete(app.run_forever(on_ready=signal_ready, host="127.0.0.1",
                                                     port=0, launch_browser=False))
        except BaseException as exc:
            state["error"] = exc
        finally:
            if not app._stop.is_set():
                try:
                    loop.run_until_complete(app.shutdown())
                except Exception:
                    pass
            loop.close()
            ready.set()

    worker = threading.Thread(target=run_server, name="xanty-local-server", daemon=True)
    worker.start()
    try:
        if not ready.wait(25):
            raise RuntimeError("The local XAnty server did not start within 25 seconds.")
        if "error" in state:
            raise RuntimeError(f"The local XAnty server failed: {state['error']}") from state["error"]
        if "url" not in state:
            raise RuntimeError("The local XAnty server stopped before the window opened.")

        storage = application_home() / "webview"
        storage.mkdir(parents=True, exist_ok=True)
        bridge = DesktopApi()
        bridge.window = webview.create_window("XAnty", state["url"], js_api=bridge,
                                              width=1500, height=920, min_size=(950, 620))
        state['app'].request_window_close = bridge.close
        # Require the modern renderer; the deprecated MSHTML engine cannot render this UI.
        webview.start(gui="edgechromium", private_mode=False, storage_path=str(storage), icon=str(icon))
    finally:
        loop = state.get("loop")
        app = state.get("app")
        if loop is not None and app is not None and worker.is_alive():
            try:
                loop.call_soon_threadsafe(lambda: loop.create_task(app.shutdown()))
            except RuntimeError:
                pass
            worker.join(timeout=25)
