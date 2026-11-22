"""Closing the native window stops its background server."""
import asyncio
import importlib.util
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "xgenius" / "desktop.py"
spec = importlib.util.spec_from_file_location("desktop_lifecycle", ROOT)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class DesktopLifecycleTests(unittest.TestCase):
    def test_native_window_starts_after_server_and_stops_it_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {}

            class FakeWebApp:
                def __init__(self, loop, desktop_mode=False):
                    state["app"] = self
                    self._stop = asyncio.Event()
                    self.desktop_mode = desktop_mode

                async def run_forever(self, on_ready=None, host=None, port=None, launch_browser=None):
                    state["server_thread"] = threading.current_thread().name
                    state["server_settings"] = (host, port, launch_browser)
                    on_ready("http://127.0.0.1:12345/")
                    await self._stop.wait()

                async def shutdown(self):
                    self._stop.set()

            class FakeWindow:
                closed = False

                def destroy(self):
                    self.closed = True

            def create_window(title, url, **kwargs):
                state["title"] = title
                state["url"] = url
                state["bridge"] = kwargs["js_api"]
                state["window"] = FakeWindow()
                return state["window"]

            def start(**kwargs):
                state["renderer"] = kwargs["gui"]
                state["bridge"].close()

            package = types.ModuleType("xgenius")
            package.__path__ = []
            web = types.ModuleType("xgenius.web")
            web.__path__ = []
            modules = {
                "webview": types.SimpleNamespace(create_window=create_window, start=start),
                "xgenius": package,
                "xgenius.web": web,
                "xgenius.config": types.SimpleNamespace(application_home=lambda: Path(directory)),
                "xgenius.web.server": types.SimpleNamespace(WebApp=FakeWebApp),
            }
            with patch.dict(sys.modules, modules):
                desktop.run_desktop()

            self.assertTrue(state["app"].desktop_mode)
            self.assertEqual(state["server_settings"], ("127.0.0.1", 0, False))
            self.assertEqual(state["title"], "XAnty")
            self.assertEqual(state["url"], "http://127.0.0.1:12345/")
            self.assertEqual(state["renderer"], "edgechromium")
            self.assertTrue(state["window"].closed)
            self.assertTrue(state["app"]._stop.is_set())
            self.assertNotEqual(state["server_thread"], threading.current_thread().name)


if __name__ == "__main__":
    unittest.main()
