"""Window-frame tests use a fake native boundary and never touch real windows."""
import ctypes
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import psutil

from xgenius import window_frames as frames


def chrome(pid=41, *, name='chrome.exe', arguments=None, alive=True):
    return SimpleNamespace(pid=pid, name=lambda: name,
                           cmdline=lambda: arguments or [],
                           is_running=lambda: alive, status=lambda: 'running')


class Native:
    def __init__(self, *, dwm=True):
        self.windows = {101: 41, 102: 99}
        self.dwm = dwm
        self.foreground = True
        self.calls = []
        self.changed = threading.Event()
        self.closed = threading.Event()

    def pump_messages(self):
        pass

    def windows_for_pid(self, pid):
        return [hwnd for hwnd, owner in self.windows.items() if owner == pid]

    def window_pid(self, hwnd):
        return self.windows.get(hwnd, 0)

    def get_border(self, hwnd):
        return 123

    def set_border(self, hwnd, color):
        self.calls.append(('border', hwnd, color))
        self.changed.set()
        return self.dwm

    def foreground_unobscured(self, hwnd):
        return self.foreground

    def show_outline(self, hwnd, color):
        self.calls.append(('show', hwnd, color))
        self.changed.set()

    def hide_outline(self, hwnd, destroy=False):
        self.calls.append(('hide', hwnd, destroy))

    def close(self):
        self.closed.set()


class ColorTests(unittest.TestCase):
    def test_colorref_uses_bgr_byte_order(self):
        self.assertEqual(frames._colorref('#1234Ab'), 0xAB3412)
        self.assertEqual(frames._colorref('#FF0000'), 255)
        self.assertEqual(frames._colorref('#0000FF'), 0xFF0000)

    def test_invalid_colors_are_rejected_before_starting_any_monitor(self):
        for color in ('red', '#123', '#1234567', '#ZZ0000', ' #123456', None, 1):
            with self.subTest(color=color), patch.object(frames, '_FrameMonitor') as monitor:
                with self.assertRaises(ValueError):
                    frames.attach_frame(object(), color)
                monitor.assert_not_called()


class ProcessSelectionTests(unittest.TestCase):
    def test_tracked_root_takes_priority_without_machine_wide_process_search(self):
        target = chrome()
        with patch.object(frames.psutil, 'Process') as lookup:
            self.assertIs(frames._find_browser_process(SimpleNamespace(_xg_browser_process=target)), target)
        lookup.assert_not_called()

    def test_service_children_select_only_a_single_chrome_root(self):
        target = chrome()
        children = [chrome(42, arguments=['--type=renderer']),
                    chrome(43, name='unrelated.exe'), target]
        driver = Mock()
        driver.children.return_value = children
        browser = SimpleNamespace(service=SimpleNamespace(process=SimpleNamespace(pid=17, poll=lambda: None)))
        with patch.object(frames.psutil, 'Process', return_value=driver) as lookup:
            self.assertIs(frames._find_browser_process(browser), target)
        lookup.assert_called_once_with(17)
        driver.children.assert_called_once_with(recursive=True)

    def test_ambiguous_descendants_are_refused(self):
        driver = Mock()
        driver.children.return_value = [chrome(41), chrome(42)]
        browser = SimpleNamespace(service=SimpleNamespace(process=SimpleNamespace(pid=17)))
        with patch.object(frames.psutil, 'Process', return_value=driver):
            self.assertIsNone(frames._find_browser_process(browser))

    def test_dead_tracked_root_never_falls_back_to_another_chrome(self):
        browser = SimpleNamespace(_xg_browser_process=chrome(alive=False))
        with patch.object(frames.psutil, 'Process') as lookup:
            self.assertIsNone(frames._find_browser_process(browser))
        lookup.assert_not_called()

    def test_access_denied_and_dead_service_are_safe(self):
        browser = SimpleNamespace(service=SimpleNamespace(process=SimpleNamespace(pid=17, poll=lambda: 0)))
        with patch.object(frames.psutil, 'Process') as lookup:
            self.assertIsNone(frames._find_browser_process(browser))
        lookup.assert_not_called()
        browser.service.process.poll = lambda: None
        with patch.object(frames.psutil, 'Process', side_effect=psutil.AccessDenied(17)):
            self.assertIsNone(frames._find_browser_process(browser))


class MonitorTests(unittest.TestCase):
    def setUp(self):
        frames._shutdown()
        frames.set_frames_enabled(True)
        self.browser = SimpleNamespace(_xg_browser_process=chrome())
        self.native = Native()
        self.monitor = frames._FrameMonitor(self.browser, 0x123456)
        self.monitor.native = self.native
        self.monitor.process = self.browser._xg_browser_process

    def tearDown(self):
        frames._shutdown()
        frames.set_frames_enabled(True)

    def test_exact_pid_is_decorated_once_and_original_color_restored(self):
        self.assertTrue(self.monitor._tick())
        self.monitor._tick()
        self.assertEqual(self.native.calls, [('border', 101, 0x123456)])
        self.monitor._clear()
        self.assertIn(('border', 101, 123), self.native.calls)
        self.assertIn(('hide', 101, True), self.native.calls)

    def test_changed_color_updates_an_existing_border(self):
        self.monitor._tick()
        self.monitor.color = 55
        self.monitor._tick()
        self.assertEqual(self.native.calls[-1], ('border', 101, 55))
        self.assertEqual(self.monitor.borders, {101: 123})

    def test_fallback_hides_when_not_foreground_or_unobscured(self):
        self.native.dwm = False
        self.monitor._tick()
        self.assertIn(('show', 101, 0x123456), self.native.calls)
        self.native.foreground = False
        self.monitor._tick()
        self.assertEqual(self.native.calls[-1], ('hide', 101, False))
        self.assertEqual(sum(call[0] == 'border' for call in self.native.calls), 1)

    def test_global_preference_disables_and_reenables_running_frames(self):
        self.monitor._tick()
        frames.set_frames_enabled(False)
        self.monitor._tick()
        self.assertFalse(self.monitor.borders)
        self.assertIn(('border', 101, 123), self.native.calls)
        frames.set_frames_enabled(True)
        self.monitor._tick()
        self.assertEqual(self.native.calls[-1], ('border', 101, 0x123456))

    def test_handle_reused_by_unrelated_process_is_never_reset(self):
        self.monitor._tick()
        self.native.windows[101] = 99
        self.monitor._tick()
        self.assertEqual([call for call in self.native.calls if call[0] == 'border'],
                         [('border', 101, 0x123456)])

    def test_enumeration_race_cannot_decorate_an_unrelated_handle(self):
        self.native.windows_for_pid = lambda pid: [102]
        self.monitor._tick()
        self.assertEqual(self.native.calls, [])

    def test_browser_exit_stops_monitor_without_resetting_reused_handles(self):
        self.monitor._tick()
        self.browser._xg_browser_process.is_running = lambda: False
        self.assertFalse(self.monitor._tick())
        self.monitor._clear()
        self.assertEqual(sum(call[0] == 'border' for call in self.native.calls), 1)

    def test_attach_update_and_detach_use_one_monitor_and_cleanup(self):
        with patch.object(frames, '_native_factory', return_value=self.native):
            frames.attach_frame(self.browser, '#123456')
            self.assertTrue(self.native.changed.wait(2), 'Monitor never reached fake native boundary')
            running = frames._monitors[id(self.browser)]
            frames.attach_frame(self.browser, '#ABCDEF')
            self.assertIs(frames._monitors[id(self.browser)], running)
            self.assertEqual(running.color, 0xEFCDAB)
            frames.detach_frame(self.browser)
            self.assertTrue(self.native.closed.is_set())
            self.assertFalse(running.is_alive())
            self.assertNotIn(id(self.browser), frames._monitors)
            frames.detach_frame(self.browser)

    def test_disabled_attachment_detaches_without_starting_another_thread(self):
        with patch.object(frames, '_native_factory', return_value=self.native):
            frames.attach_frame(self.browser, '#123456')
            self.assertTrue(self.native.changed.wait(2))
            frames.attach_frame(self.browser, '#123456', enabled=False)
        self.assertTrue(self.native.closed.is_set())
        self.assertNotIn(id(self.browser), frames._monitors)

    def test_thread_exits_and_destroys_fallback_when_browser_exits(self):
        self.native.dwm = False
        with patch.object(frames, '_native_factory', return_value=self.native):
            frames.attach_frame(self.browser, '#123456')
            self.assertTrue(self.native.changed.wait(2))
            running = frames._monitors[id(self.browser)]
            self.browser._xg_browser_process.is_running = lambda: False
            running.wake.set()
            running.join(2)
        self.assertFalse(running.is_alive())
        self.assertTrue(self.native.closed.is_set())
        self.assertIn(('hide', 101, True), self.native.calls)
        self.assertNotIn(id(self.browser), frames._monitors)

    def test_unsupported_platform_does_not_load_windows_libraries(self):
        with patch.object(frames.sys, 'platform', 'linux'), \
                patch.object(frames, '_Win32Native') as native:
            self.assertIsNone(frames._native_factory())
        native.assert_not_called()

    def test_closed_service_during_discovery_exits_without_waiting_for_timeout(self):
        browser = SimpleNamespace(service=SimpleNamespace(process=SimpleNamespace(pid=17, poll=lambda: 0)))
        with patch.object(frames, '_native_factory', return_value=self.native), \
                patch.object(frames.psutil, 'Process') as lookup:
            frames.attach_frame(browser, '#123456')
            self.assertTrue(self.native.closed.wait(2))
        lookup.assert_not_called()
        self.assertEqual(self.native.calls, [])

    def test_native_objects_close_even_if_restoring_a_border_fails(self):
        with patch.object(frames, '_native_factory', return_value=self.native):
            frames.attach_frame(self.browser, '#123456')
            self.assertTrue(self.native.changed.wait(2))
            self.native.set_border = Mock(side_effect=OSError('Unavailable native window'))
            frames.detach_frame(self.browser)
        self.assertTrue(self.native.closed.is_set())


class NativeBoundaryTests(unittest.TestCase):
    @staticmethod
    def native():
        native = object.__new__(frames._Win32Native)
        native.user32 = Mock()
        native.user32.GetForegroundWindow.return_value = 101
        native.user32.IsWindowVisible.return_value = True
        native.user32.IsIconic.return_value = False
        native.outlines = {}
        native._cloaked = Mock(return_value=False)
        native._enumerate = Mock(return_value=[101])
        native._bounds = Mock(return_value=SimpleNamespace(left=10, top=20, right=610, bottom=420))
        return native

    def test_minimized_cloaked_and_other_app_windows_suppress_outline(self):
        for state in ('other_app', 'minimized', 'cloaked', 'hidden'):
            with self.subTest(state=state):
                native = self.native()
                if state == 'other_app':
                    native.user32.GetForegroundWindow.return_value = 102
                elif state == 'minimized':
                    native.user32.IsIconic.return_value = True
                elif state == 'cloaked':
                    native._cloaked.return_value = True
                else:
                    native.user32.IsWindowVisible.return_value = False
                self.assertFalse(native.foreground_unobscured(101))

    def test_partial_occlusion_suppresses_outline_and_own_strips_do_not(self):
        native = self.native()
        native._enumerate.return_value = [201, 101]
        self.assertFalse(native.foreground_unobscured(101))
        native.outlines[101] = [201]
        self.assertTrue(native.foreground_unobscured(101))

    def test_nonintersecting_windows_above_target_do_not_suppress_outline(self):
        native = self.native()
        native._enumerate.return_value = [201, 101]
        native._bounds.side_effect = [SimpleNamespace(left=10, top=20, right=610, bottom=420),
                                     SimpleNamespace(left=700, top=20, right=800, bottom=420)]
        self.assertTrue(native.foreground_unobscured(101))

    def test_fallback_strips_are_owned_click_through_and_never_activated(self):
        native = self.native()
        native._ensure_class = Mock()
        native._class_name = 'FakeFrameClass'
        native.instance = 900
        native.user32.CreateWindowExW.side_effect = [201, 202, 203, 204]
        native.show_outline(101, 0x123456)
        self.assertEqual(native.outlines[101], [201, 202, 203, 204])
        for call in native.user32.CreateWindowExW.call_args_list:
            styles = call.args[0]
            self.assertEqual(styles & 0x080800A0, 0x080800A0)
            self.assertEqual(call.args[8], 101)
        for call in native.user32.SetWindowPos.call_args_list:
            self.assertTrue(call.args[-1] & 0x10, 'SWP_NOACTIVATE must always be present')
            self.assertNotEqual(call.args[1], -1, 'Outline must not be globally topmost')
        native.user32.SetForegroundWindow.assert_not_called()
        native.user32.SetActiveWindow.assert_not_called()
        native.hide_outline(101, destroy=True)
        self.assertEqual(native.user32.DestroyWindow.call_count, 4)
        self.assertFalse(native.outlines)

    def test_failed_strip_creation_cleans_up_partial_outline(self):
        native = self.native()
        native._ensure_class = Mock()
        native._class_name = 'FakeFrameClass'
        native.instance = 900
        native.user32.CreateWindowExW.side_effect = [201, 0]
        native.show_outline(101, 0x123456)
        native.user32.DestroyWindow.assert_called_once_with(201)
        self.assertFalse(native.outlines)

    def test_win32_signatures_preserve_pointer_sized_handles(self):
        if not hasattr(ctypes, 'WINFUNCTYPE'):
            self.skipTest('Windows ctypes declarations')
        dlls = {name: Mock() for name in ('user32', 'gdi32', 'kernel32', 'dwmapi')}
        dlls['kernel32'].GetModuleHandleW.return_value = 0x123456789
        with patch.object(ctypes, 'WinDLL', side_effect=lambda name, **kwargs: dlls[name]):
            native = frames._Win32Native()
        self.assertIs(dlls['user32'].CreateWindowExW.restype, frames.wintypes.HWND)
        self.assertIs(dlls['user32'].DefWindowProcW.restype, ctypes.c_ssize_t)
        self.assertIs(dlls['user32'].SetWindowPos.argtypes[1], frames.wintypes.HWND)
        self.assertEqual(native.instance, 0x123456789)
        self.assertIsNotNone(native._wndproc)
        self.assertEqual(native._window_proc(1, 0x0021, 0, 0), 3)
        self.assertEqual(native._window_proc(1, 0x0084, 0, 0), -1)


if __name__ == '__main__':
    unittest.main()
