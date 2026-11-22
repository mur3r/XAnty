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
    def test_native_window_is_created_before_backend_initialization(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {'gui_started': False}
            loaded = threading.Event()

            class FakeWebApp:
                def __init__(self, loop, desktop_mode=False):
                    self._stop = asyncio.Event()
                    self.desktop_mode = desktop_mode
                    if not state['gui_started']:
                        raise RuntimeError('Backend was initialized before the GUI started')

                async def run_forever(self, on_ready=None, **kwargs):
                    await asyncio.sleep(0.05)
                    on_ready('http://127.0.0.1:12345/')
                    await self._stop.wait()

                async def shutdown(self):
                    self._stop.set()

            class Window:
                def destroy(self): pass
                def load_url(self, url):
                    state['url'] = url
                    loaded.set()
                def load_html(self, html):
                    state['error_page'] = html
                    loaded.set()

            def create_window(title, url=None, **kwargs):
                state['loading_html'] = kwargs.get('html', '')
                return Window()

            def start(func=None, **kwargs):
                state['gui_started'] = True
                if func:
                    func()
                self.assertTrue(loaded.wait(3), 'Slow backend did not eventually load')

            modules = {
                'webview': types.SimpleNamespace(create_window=create_window, start=start),
                'xgenius.config': types.SimpleNamespace(application_home=lambda: Path(directory)),
                'xgenius.web.server': types.SimpleNamespace(WebApp=FakeWebApp),
            }
            with patch.dict(sys.modules, modules):
                desktop.run_desktop()
            self.assertIn('XAnty', state['loading_html'])
            self.assertEqual(state.get('url'), 'http://127.0.0.1:12345/', state)

    def test_native_window_starts_after_server_and_stops_it_on_close(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {}
            loaded = threading.Event()

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

                def load_url(self, url):
                    state['url'] = url
                    loaded.set()

                def load_html(self, html):
                    state['error'] = html
                    loaded.set()

            def create_window(title, url=None, **kwargs):
                state["title"] = title
                state["url"] = url
                state["bridge"] = kwargs["js_api"]
                state["window"] = FakeWindow()
                return state["window"]

            def start(func=None, **kwargs):
                state["renderer"] = kwargs["gui"]
                if func:
                    func()
                self.assertTrue(loaded.wait(3), state)
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

    def test_backend_failure_is_displayed_without_blocking_or_crashing_the_gui(self):
        with tempfile.TemporaryDirectory() as directory:
            shown = threading.Event()
            state = {}
            class Window:
                def __init__(self, html): self.html = html
                def load_html(self, html):
                    state['rendered'] = html
                    shown.set()
            def create_window(*args, **kwargs):
                state['window'] = Window(kwargs['html'])
                return state['window']
            def fail(*args, **kwargs):
                raise RuntimeError('Workspace is unavailable')
            def start(func, **kwargs):
                func()
                self.assertTrue(shown.wait(3))
                # WebView2 finishing initialization reloads the window's stored HTML.
                state['rendered'] = state['window'].html
            modules = {
                'webview': types.SimpleNamespace(create_window=create_window, start=start),
                'xgenius.config': types.SimpleNamespace(application_home=lambda: Path(directory)),
                'xgenius.web.server': types.SimpleNamespace(WebApp=fail),
            }
            with patch.dict(sys.modules, modules):
                desktop.run_desktop()
            self.assertTrue('Workspace is unavailable' in state['rendered'], 'Early error was replaced by the loading page')
            self.assertIn('backend_error', (Path(directory)/'startup.log').read_text(encoding='utf-8'))

    def test_closing_while_starting_never_navigates_to_a_late_server(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            beginning = threading.Event()
            window = Mock()
            class SlowApp:
                def __init__(self, *a, **kw): self._stop = asyncio.Event()
                async def run_forever(self, on_ready, **kwargs):
                    beginning.set()
                    await asyncio.sleep(0.05)
                    on_ready('http://127.0.0.1:12345/')
                    await self._stop.wait()
                async def shutdown(self): self._stop.set()
            def start(func, **kwargs):
                func()
                self.assertTrue(beginning.wait(3))
                # Return as if the user closed the native window during loading.
            modules = {
                'webview': types.SimpleNamespace(create_window=lambda *a, **kw: window, start=start),
                'xgenius.config': types.SimpleNamespace(application_home=lambda: Path(directory)),
                'xgenius.web.server': types.SimpleNamespace(WebApp=SlowApp),
            }
            with patch.dict(sys.modules, modules): desktop.run_desktop()
            window.load_url.assert_not_called()


if __name__ == "__main__":
    unittest.main()
