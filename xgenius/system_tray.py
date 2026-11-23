"""Windows notification-area icon owned by a dedicated Win32 message loop."""

import ctypes
import sys
import threading
from ctypes import wintypes


_WM_NULL = 0x0000
_WM_CLOSE = 0x0010
_WM_CANCELMODE = 0x001F
_WM_CONTEXTMENU = 0x007B
_WM_LBUTTONDBLCLK = 0x0203
_WM_RBUTTONUP = 0x0205
_NIN_KEYSELECT = 0x0401
_TRAY_CALLBACK = 0x8050  # WM_APP + 80
_ICON_ID = 1
_OPEN = 1
_EXIT = 2

_NIM_ADD = 0
_NIM_MODIFY = 1
_NIM_DELETE = 2
_NIM_SETFOCUS = 3
_NIM_SETVERSION = 4
_NIF_MESSAGE = 0x01
_NIF_ICON = 0x02
_NIF_TIP = 0x04
_NIF_SHOWTIP = 0x80
_MSGFLT_ALLOW = 1


class SystemTray:
    def __init__(self, icon, on_open, on_exit, on_unavailable, record):
        self._icon = icon
        self._on_open = on_open
        self._on_exit = on_exit
        self._on_unavailable = on_unavailable
        self._record = record
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._lock = threading.Lock()
        self._native = None
        self._thread = threading.Thread(target=self._run, name='xanty-system-tray', daemon=True)

    @property
    def available(self) -> bool:
        return self._ready.is_set() and not self._stopping.is_set()

    def start(self) -> None:
        with self._lock:
            if self._thread.ident is None and not self._stopping.is_set():
                self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stopping.set()
            native = self._native
        if native is not None:
            native.request_stop()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=2)

    def _became_unavailable(self) -> None:
        was_ready = self._ready.is_set()
        self._ready.clear()
        if was_ready and not self._stopping.is_set():
            self._on_unavailable()

    def _register_icon(self) -> None:
        if self._native.register_icon():
            self._ready.set()
        else:
            self._record('tray_registration_failed')
            self._became_unavailable()

    def _run(self) -> None:
        native = None
        try:
            native = _WindowsTray(self._icon, self._handle_message)
            with self._lock:
                if self._stopping.is_set():
                    return
                self._native = native
            native.open()
            if not self._stopping.is_set():
                self._register_icon()
                native.run()
        except Exception as exc:
            self._record(f'tray_error {type(exc).__name__}: {exc}')
        finally:
            try:
                if native is not None:
                    native.close()
            finally:
                with self._lock:
                    self._native = None
                self._became_unavailable()

    def _handle_message(self, message, wparam, lparam) -> bool:
        if self._stopping.is_set():
            return False
        native = self._native
        try:
            if message == native.taskbar_created:
                self._register_icon()
                return True
            if message != _TRAY_CALLBACK:
                return False

            event = lparam & 0xFFFF
            icon_id = lparam >> 16 & 0xFFFF if native.version4 else wparam
            if icon_id != _ICON_ID or not self.available:
                return True
            context_event = _WM_CONTEXTMENU if native.version4 else _WM_RBUTTONUP
            if event == context_event:
                position = None
                if native.version4:
                    position = (ctypes.c_short(wparam & 0xFFFF).value,
                                ctypes.c_short(wparam >> 16 & 0xFFFF).value)
                command = native.show_menu(position)
                if self.available:
                    if command == _OPEN:
                        self._on_open()
                    elif command == _EXIT:
                        self._on_exit()
            elif event in (_WM_LBUTTONDBLCLK, _NIN_KEYSELECT):
                self._on_open()
            return True
        except Exception as exc:
            self._record(f'tray_event_error {type(exc).__name__}: {exc}')
            return False


class _WindowClass(ctypes.Structure):
    _fields_ = [
        ('style', wintypes.UINT), ('lpfnWndProc', ctypes.c_void_p),
        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
        ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
        ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR),
    ]


class _NotifyIconData(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD), ('hWnd', wintypes.HWND),
        ('uID', wintypes.UINT), ('uFlags', wintypes.UINT),
        ('uCallbackMessage', wintypes.UINT), ('hIcon', wintypes.HICON),
        ('szTip', wintypes.WCHAR * 128), ('dwState', wintypes.DWORD),
        ('dwStateMask', wintypes.DWORD), ('szInfo', wintypes.WCHAR * 256),
        ('uVersion', wintypes.UINT), ('szInfoTitle', wintypes.WCHAR * 64),
        ('dwInfoFlags', wintypes.DWORD), ('guidItem', ctypes.c_ubyte * 16),
        ('hBalloonIcon', wintypes.HICON),
    ]


def _bind(dll, name, result, *args):
    function = getattr(dll, name)
    function.restype = result
    function.argtypes = args
    return function


class _WindowsTray:
    def __init__(self, icon, handle_message):
        if sys.platform != 'win32':
            raise RuntimeError('The system tray requires Windows.')

        self._icon_path = str(icon)
        self._handle_message = handle_message
        self._hwnd = None
        self._menu = None
        self._class_atom = 0
        self._class_name = f'XAntySystemTray_{id(self):x}'
        self.taskbar_created = 0
        self.version4 = False
        self._data = _NotifyIconData(cbSize=ctypes.sizeof(_NotifyIconData), uID=_ICON_ID,
                                     uFlags=_NIF_MESSAGE | _NIF_ICON | _NIF_TIP | _NIF_SHOWTIP,
                                     uCallbackMessage=_TRAY_CALLBACK, szTip='XAnty', uVersion=4)

        user32 = ctypes.WinDLL('user32', use_last_error=True)
        shell32 = ctypes.WinDLL('shell32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        hwnd, uint, wparam, lparam = wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        msg_ptr = ctypes.POINTER(wintypes.MSG)
        lresult = ctypes.c_ssize_t
        self._window_proc = ctypes.WINFUNCTYPE(lresult, hwnd, uint, wparam, lparam)(self._dispatch)
        self._instance = _bind(kernel32, 'GetModuleHandleW', wintypes.HMODULE, wintypes.LPCWSTR)(None)
        self._register_class = _bind(user32, 'RegisterClassW', wintypes.WORD, ctypes.POINTER(_WindowClass))
        self._unregister_class = _bind(user32, 'UnregisterClassW', wintypes.BOOL, wintypes.LPCWSTR,
                                       wintypes.HINSTANCE)
        self._create_window = _bind(user32, 'CreateWindowExW', hwnd, wintypes.DWORD, wintypes.LPCWSTR,
                                    wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, hwnd, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
        self._destroy_window = _bind(user32, 'DestroyWindow', wintypes.BOOL, hwnd)
        self._default_proc = _bind(user32, 'DefWindowProcW', lresult, hwnd, uint, wparam, lparam)
        self._load_image = _bind(user32, 'LoadImageW', wintypes.HANDLE, wintypes.HINSTANCE, wintypes.LPCWSTR,
                                 uint, ctypes.c_int, ctypes.c_int, uint)
        self._destroy_icon = _bind(user32, 'DestroyIcon', wintypes.BOOL, wintypes.HICON)
        self._register_message = _bind(user32, 'RegisterWindowMessageW', uint, wintypes.LPCWSTR)
        self._change_message_filter = _bind(user32, 'ChangeWindowMessageFilterEx', wintypes.BOOL,
                                             hwnd, uint, wintypes.DWORD, wintypes.LPVOID)
        self._post_message = _bind(user32, 'PostMessageW', wintypes.BOOL, hwnd, uint, wparam, lparam)
        self._post_quit = _bind(user32, 'PostQuitMessage', None, ctypes.c_int)
        self._get_message = _bind(user32, 'GetMessageW', wintypes.BOOL, msg_ptr, hwnd, uint, uint)
        self._translate_message = _bind(user32, 'TranslateMessage', wintypes.BOOL, msg_ptr)
        self._dispatch_message = _bind(user32, 'DispatchMessageW', lresult, msg_ptr)
        self._create_menu = _bind(user32, 'CreatePopupMenu', wintypes.HMENU)
        self._destroy_menu = _bind(user32, 'DestroyMenu', wintypes.BOOL, wintypes.HMENU)
        self._append_menu = _bind(user32, 'AppendMenuW', wintypes.BOOL, wintypes.HMENU, uint,
                                   ctypes.c_size_t, wintypes.LPCWSTR)
        self._track_menu = _bind(user32, 'TrackPopupMenu', wintypes.BOOL, wintypes.HMENU, uint,
                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, hwnd, ctypes.POINTER(wintypes.RECT))
        self._get_cursor = _bind(user32, 'GetCursorPos', wintypes.BOOL, ctypes.POINTER(wintypes.POINT))
        self._set_foreground = _bind(user32, 'SetForegroundWindow', wintypes.BOOL, hwnd)
        self._notify = _bind(shell32, 'Shell_NotifyIconW', wintypes.BOOL, wintypes.DWORD,
                             ctypes.POINTER(_NotifyIconData))

    def open(self) -> None:
        self.taskbar_created = self._register_message('TaskbarCreated')
        window_class = _WindowClass(lpfnWndProc=ctypes.cast(self._window_proc, ctypes.c_void_p),
                                    hInstance=self._instance, lpszClassName=self._class_name)
        self._class_atom = self._register_class(ctypes.byref(window_class))
        if not self._class_atom or not self.taskbar_created:
            raise ctypes.WinError()

        self._data.hIcon = self._load_image(None, self._icon_path, 1, 0, 0, 0x0050)
        self._menu = self._create_menu()
        if not self._data.hIcon or not self._menu:
            raise ctypes.WinError()
        if not self._append_menu(self._menu, 0, _OPEN, 'Открыть') or not self._append_menu(self._menu, 0, _EXIT, 'Выход'):
            raise ctypes.WinError()

        # TaskbarCreated is broadcast to top-level windows, including hidden ones.
        self._hwnd = self._create_window(0x0080, self._class_name, '', 0x80000000, 0, 0, 0, 0,
                                         None, None, self._instance, None)
        if not self._hwnd:
            raise ctypes.WinError()
        self._data.hWnd = self._hwnd
        # Explorer may run at a lower integrity level. Allow only its restart broadcast on this window.
        if not self._change_message_filter(self._hwnd, self.taskbar_created, _MSGFLT_ALLOW, None):
            raise ctypes.WinError()

    def register_icon(self) -> bool:
        data = ctypes.byref(self._data)
        # Explorer also broadcasts TaskbarCreated on DPI changes while the icon may still exist.
        if not (self._notify(_NIM_ADD, data) or self._notify(_NIM_MODIFY, data)):
            return False
        self.version4 = bool(self._notify(_NIM_SETVERSION, data))
        return True

    def _dispatch(self, hwnd, message, wparam, lparam):
        if message == _WM_CLOSE:
            self._post_quit(0)
            return 0
        if self._handle_message(message, wparam, lparam):
            return 0
        return self._default_proc(hwnd, message, wparam, lparam)

    def run(self) -> None:
        message = wintypes.MSG()
        while (result := self._get_message(ctypes.byref(message), None, 0, 0)) > 0:
            self._translate_message(ctypes.byref(message))
            self._dispatch_message(ctypes.byref(message))
        if result == -1:
            raise ctypes.WinError()

    def show_menu(self, position) -> int:
        if position is None or position == (-1, -1):
            point = wintypes.POINT()
            self._get_cursor(ctypes.byref(point))
            position = point.x, point.y
        self._set_foreground(self._hwnd)
        # TPM_RETURNCMD | TPM_NONOTIFY | TPM_RIGHTBUTTON
        command = self._track_menu(self._menu, 0x0182, *position, 0, self._hwnd, None)
        self._post_message(self._hwnd, _WM_NULL, 0, 0)
        if not command:
            self._notify(_NIM_SETFOCUS, ctypes.byref(self._data))
        return command

    def request_stop(self) -> None:
        hwnd = self._hwnd
        if hwnd:
            self._post_message(hwnd, _WM_CANCELMODE, 0, 0)
            self._post_message(hwnd, _WM_CLOSE, 0, 0)

    def close(self) -> None:
        if self._hwnd:
            self._notify(_NIM_DELETE, ctypes.byref(self._data))
            self._destroy_window(self._hwnd)
            self._hwnd = None
        if self._menu:
            self._destroy_menu(self._menu)
        if self._data.hIcon:
            self._destroy_icon(self._data.hIcon)
        if self._class_atom:
            self._unregister_class(self._class_name, self._instance)
