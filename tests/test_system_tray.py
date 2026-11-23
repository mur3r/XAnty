"""Drive tray events without registering an icon in the user's notification area."""

import ctypes
import queue
import threading
import unittest
from unittest.mock import Mock, patch


class FakeWindowsTray:
    taskbar_created = 0xC001
    version4 = True

    def __init__(self, icon, handle_message):
        self.handle_message = handle_message
        self.messages = queue.Queue()
        self.started = threading.Event()
        self.registrations = 0
        self.register_success = True
        self.menu_selection = 0
        self.menu_position = None
        self.closed = False

    def send(self, message, wparam=0, lparam=0):
        processed = threading.Event()
        self.messages.put((message, wparam, lparam, processed))
        if not processed.wait(3):
            raise AssertionError(f'Tray did not process message {message:#x}')

    def open(self):
        pass

    def register_icon(self):
        self.registrations += 1
        return self.register_success

    def run(self):
        self.started.set()
        while (entry := self.messages.get(timeout=5)) is not None:
            message, wparam, lparam, processed = entry
            try:
                self.handle_message(message, wparam, lparam)
            finally:
                processed.set()

    def show_menu(self, position):
        self.menu_position = position
        return self.menu_selection

    def request_stop(self):
        self.messages.put(None)

    def close(self):
        self.closed = True


class SystemTrayTests(unittest.TestCase):
    def test_tray_window_allows_only_the_explorer_restart_message(self):
        from xgenius import system_tray

        for allow in (True, False):
            with self.subTest(filter_updated=allow):
                user32 = Mock()
                user32.RegisterWindowMessageW.return_value = 0xC123
                user32.RegisterClassW.return_value = 2
                user32.LoadImageW.return_value = 11
                user32.CreatePopupMenu.return_value = 12
                user32.AppendMenuW.return_value = True
                user32.CreateWindowExW.return_value = 13
                user32.ChangeWindowMessageFilterEx.return_value = allow
                kernel32 = Mock()
                kernel32.GetModuleHandleW.return_value = 14
                dlls = Mock(side_effect=[user32, Mock(), kernel32])
                with (patch.object(system_tray.sys, 'platform', 'win32'),
                      patch.object(ctypes, 'WinDLL', dlls, create=True),
                      patch.object(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE, create=True),
                      patch.object(ctypes, 'WinError', return_value=OSError('Access denied'), create=True)):
                    native = system_tray._WindowsTray('app.ico', lambda *args: False)
                    try:
                        if allow:
                            native.open()
                        else:
                            with self.assertRaises(OSError):
                                native.open()
                    finally:
                        native.close()

                user32.ChangeWindowMessageFilterEx.assert_called_once_with(13, 0xC123, 1, None)
                user32.ChangeWindowMessageFilter.assert_not_called()

    def start_tray(self, register_success=True):
        from xgenius import system_tray

        actions = []
        initialized = threading.Event()
        native = None

        def make_native(icon, callback):
            nonlocal native
            native = FakeWindowsTray(icon, callback)
            native.register_success = register_success
            initialized.set()
            return native

        with patch.object(system_tray, '_WindowsTray', make_native):
            tray = system_tray.SystemTray('app.ico', lambda: actions.append('open'),
                                         lambda: actions.append('exit'), lambda: actions.append('unavailable'),
                                         lambda message: None)
            self.addCleanup(tray.stop)
            tray.start()
            self.assertTrue(initialized.wait(3))
            self.assertTrue(native.started.wait(3))
        return tray, native, actions

    def test_shell_menu_and_double_click_dispatch_to_desktop(self):
        tray, native, actions = self.start_tray()
        self.assertTrue(tray.available)
        native.send(0x8050, lparam=0x00010203)  # WM_LBUTTONDBLCLK
        native.menu_selection = 1
        native.send(0x8050, wparam=0x0012FFF2, lparam=0x0001007B)  # WM_CONTEXTMENU
        self.assertEqual(native.menu_position, (-14, 18))
        native.menu_selection = 2
        native.send(0x8050, lparam=0x0001007B)
        self.assertEqual(actions, ['open', 'open', 'exit'])
        tray.stop()
        self.assertFalse(tray.available)
        self.assertTrue(native.closed)

    def test_explorer_restart_re_registers_icon_and_surfaces_registration_failure(self):
        tray, native, actions = self.start_tray()
        native.send(native.taskbar_created)
        self.assertEqual(native.registrations, 2)
        self.assertTrue(tray.available)
        self.assertEqual(actions, [])
        native.register_success = False
        native.send(native.taskbar_created)
        self.assertFalse(tray.available)
        self.assertEqual(actions, ['unavailable'])

    def test_initial_registration_failure_leaves_the_icon_unavailable_until_explorer_recovers(self):
        tray, native, actions = self.start_tray(register_success=False)
        self.assertFalse(tray.available)
        self.assertEqual(actions, [])
        native.register_success = True
        native.send(native.taskbar_created)
        self.assertTrue(tray.available)


if __name__ == '__main__':
    unittest.main()
