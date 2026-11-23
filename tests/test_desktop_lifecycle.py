"""Closing the native window stops its background server."""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from webview.event import Event


ROOT = Path(__file__).resolve().parents[1] / "xgenius" / "desktop.py"
spec = importlib.util.spec_from_file_location("desktop_lifecycle", ROOT)
desktop = importlib.util.module_from_spec(spec)
spec.loader.exec_module(desktop)


class DesktopLifecycleTests(unittest.TestCase):
    def test_startup_update_restarts_before_any_workspace_is_loaded(self):
        from xgenius import updates

        with tempfile.TemporaryDirectory() as directory:
            finished = threading.Event()
            window = Mock()
            window.destroy.side_effect = finished.set
            window.events = types.SimpleNamespace(shown=Event(window))

            async def install_on_startup(closing, progress):
                progress('Устанавливаем обновление…')
                return True

            updater = types.SimpleNamespace(status='installing',
                                            update_on_startup=AsyncMock(side_effect=install_on_startup),
                                            shutdown=AsyncMock())
            backend = Mock(side_effect=AssertionError('Workspace started before replacement'))
            kernel = Mock()

            def start(func, **kwargs):
                func()
                self.assertTrue(finished.wait(3), 'Startup updater did not close the old window')

            modules = {
                'webview': types.SimpleNamespace(create_window=lambda *a, **kw: window, start=start),
                'xgenius.config': types.SimpleNamespace(application_home=lambda: Path(directory)),
                'xgenius.web.server': types.SimpleNamespace(WebApp=backend),
            }
            with patch.dict(sys.modules, modules), patch.object(sys, 'frozen', True, create=True), \
                    patch('ctypes.WinDLL', return_value=kernel), patch.object(updates, 'UpdateManager', return_value=updater):
                desktop.run_desktop()

            kernel.CreateMutexW.assert_called_once_with(None, False, 'Local\\XAnty.App.Running')
            kernel.CloseHandle.assert_called_once_with(kernel.CreateMutexW.return_value)
            updater.update_on_startup.assert_awaited_once()
            updater.shutdown.assert_awaited_once()
            window.evaluate_js.assert_called_once()
            self.assertIn('Устанавливаем обновление…', window.html)
            backend.assert_not_called()
            window.load_url.assert_not_called()

    def test_javascript_bridge_does_not_walk_native_window_properties(self):
        from webview.util import inject_pywebview
        from unittest.mock import Mock
        accessed = threading.Event()
        class NativeWindow:
            @property
            def native(self):
                accessed.set()
                return None
        bridge = desktop.DesktopApi()
        field = next(name for name in vars(bridge) if name.endswith('window'))
        setattr(bridge, field, NativeWindow())
        loaded = threading.Event()
        window = types.SimpleNamespace(_js_api=bridge, _functions={}, _expose_lock=threading.Lock(),
            events=types.SimpleNamespace(before_load=threading.Event(),loaded=loaded,_pywebviewready=threading.Event()),
            run_js=Mock())
        with patch('webview.util.load_js_files', return_value=('bridge', '%s')):
            inject_pywebview('winforms', window)
            self.assertTrue(loaded.wait(2))
        self.assertFalse(accessed.is_set(), 'The JS bridge traversed native window properties during startup')

    def test_native_window_is_created_before_backend_initialization(self):
        from xgenius import __version__

        with tempfile.TemporaryDirectory() as directory:
            health = Path(directory) / 'update.health.json'
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
                def __init__(self):
                    self.events = types.SimpleNamespace(shown=Event(self))

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
            with patch.dict(sys.modules, modules), patch.dict(os.environ, {'XANTY_UPDATE_HEALTH_FILE': str(health)}):
                desktop.run_desktop()
                self.assertIsNone(os.environ.get('XANTY_UPDATE_HEALTH_FILE'))
            self.assertIn('XAnty', state['loading_html'])
            self.assertEqual(state.get('url'), 'http://127.0.0.1:12345/', state)
            self.assertEqual(json.loads(health.read_text(encoding='utf-8')), {'version': __version__, 'pid': os.getpid()})

    def test_tray_starts_after_window_shows_and_exit_drains_the_server(self):
        with tempfile.TemporaryDirectory() as directory:
            state = {}
            loaded = threading.Event()
            tray_started = threading.Event()

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
                visible = True

                def __init__(self):
                    self.events = types.SimpleNamespace(shown=Event(self))

                def destroy(self):
                    self.closed = True

                def hide(self):
                    self.visible = False

                def show(self):
                    self.visible = True

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

            class FakeTray:
                def __init__(self, icon, on_open, on_exit, on_unavailable, record):
                    self.on_open = on_open
                    self.on_exit = on_exit
                    self.on_unavailable = on_unavailable
                    self.available = False
                    state['tray'] = self

                def start(self):
                    tray_started.set()

                def stop(self):
                    state['tray_stopped'] = True

            def start(func=None, **kwargs):
                state["renderer"] = kwargs["gui"]
                if func:
                    func()
                self.assertTrue(loaded.wait(3), state)
                self.assertFalse(tray_started.is_set())
                window = state['window']
                window.events.shown.set()
                self.assertTrue(tray_started.wait(3), 'Tray did not start when the native window was shown')
                tray = state['tray']
                bridge = state['bridge']
                self.assertFalse(bridge.hide())
                self.assertTrue(window.visible)
                tray.available = True
                self.assertTrue(bridge.hide())
                self.assertFalse(window.visible)
                tray.on_open()
                self.assertTrue(window.visible)
                self.assertTrue(bridge.hide())
                tray.available = False
                tray.on_unavailable()
                self.assertTrue(window.visible)
                self.assertFalse(state['app']._stop.is_set())
                tray.on_exit()

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
            with patch.dict(sys.modules, modules), patch.object(desktop, 'SystemTray', FakeTray, create=True):
                desktop.run_desktop()

            self.assertTrue(state["app"].desktop_mode)
            self.assertEqual(state["server_settings"], ("127.0.0.1", 0, False))
            self.assertEqual(state["title"], "XAnty")
            self.assertEqual(state["url"], "http://127.0.0.1:12345/")
            self.assertEqual(state["renderer"], "edgechromium")
            self.assertTrue(state["window"].closed)
            self.assertTrue(state['tray_stopped'])
            self.assertTrue(state["app"]._stop.is_set())
            self.assertNotEqual(state["server_thread"], threading.current_thread().name)

    def test_backend_failure_is_displayed_without_blocking_or_crashing_the_gui(self):
        with tempfile.TemporaryDirectory() as directory:
            shown = threading.Event()
            state = {}
            class Window:
                def __init__(self, html):
                    self.html = html
                    self.events = types.SimpleNamespace(shown=Event(self))

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
            window.events = types.SimpleNamespace(shown=Event(window))
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
