"""Optional native profile-color frames for the exact managed Chrome process.

No Selenium commands or desktop automation are used. Win11 uses DWM's border
color; older Windows uses four owned, click-through, non-activating strips only
while the target window is foreground and unobscured. All native window objects
belong to the monitor thread and are destroyed there on detach or browser exit.
"""
import atexit
import ctypes
import logging
import re
import sys
import threading
import time
from ctypes import wintypes

import psutil


_LOG = logging.getLogger(__name__)
_CHROME_NAMES = {'chrome.exe', 'chrome', 'chromium.exe', 'chromium'}
_DEFAULT_COLOR = 0xFFFFFFFF
_POLL_SECONDS = 0.15
_DISCOVERY_SECONDS = 15.0
_lock = threading.RLock()
_monitors = {}
_frames_enabled = True


def _colorref(color: str) -> int:
    """Convert strict #RRGGBB to Windows COLORREF (0x00BBGGRR)."""
    if not isinstance(color, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        raise ValueError('Frame color must be #RRGGBB')
    red, green, blue = (int(color[index:index + 2], 16) for index in (1, 3, 5))
    return red | (green << 8) | (blue << 16)


def _alive(process) -> bool:
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _root_chrome(process) -> bool:
    try:
        return (process.name().lower() in _CHROME_NAMES
                and not any(arg.startswith('--type=') for arg in process.cmdline())
                and _alive(process))
    except (AttributeError, psutil.Error):
        return False


def _find_browser_process(browser):
    """Never search machine-wide; ambiguous service descendants are refused."""
    tracked = getattr(browser, '_xg_browser_process', None)
    if tracked is not None:
        return tracked if _root_chrome(tracked) else None
    try:
        driver = browser.service.process
        poll = getattr(driver, 'poll', None)
        if callable(poll) and poll() is not None:
            return None
        roots = [child for child in psutil.Process(driver.pid).children(recursive=True)
                 if _root_chrome(child)]
        return roots[0] if len(roots) == 1 else None
    except (AttributeError, psutil.Error):
        return None


def _service_exited(browser):
    process = getattr(getattr(browser, 'service', None), 'process', None)
    poll = getattr(process, 'poll', None)
    return callable(poll) and poll() is not None


def attach_frame(browser, color: str, enabled: bool = True) -> None:
    """Attach/update a frame; ``enabled=False`` removes this browser's frame.

    Invalid colors raise ValueError. Unavailable native support is a safe no-op.
    Call after browser process tracking, and call detach_frame before quit().
    """
    value = _colorref(color)
    if browser is None:
        return
    if not enabled:
        detach_frame(browser)
        return
    with _lock:
        monitor = _monitors.get(id(browser))
        if monitor is not None and not monitor.stop_event.is_set():
            monitor.color = value
            monitor.wake.set()
            return
        monitor = _FrameMonitor(browser, value)
        _monitors[id(browser)] = monitor
        monitor.start()


def detach_frame(browser) -> None:
    """Stop this browser's monitor and restore/remove its native decorations."""
    with _lock:
        monitor = _monitors.pop(id(browser), None)
    if monitor is not None:
        monitor.stop()


def set_frames_enabled(enabled: bool) -> None:
    """Apply the global preference to running frames, retaining their colors."""
    global _frames_enabled
    with _lock:
        _frames_enabled = bool(enabled)
        for monitor in _monitors.values():
            monitor.wake.set()


def _native_factory():
    if sys.platform != 'win32':
        return None
    try:
        return _Win32Native()
    except (OSError, AttributeError):
        _LOG.debug('Native browser frames unavailable', exc_info=True)
        return None


class _FrameMonitor(threading.Thread):
    def __init__(self, browser, color):
        super().__init__(name='XAnty-window-frame', daemon=True)
        self.browser = browser
        self.color = color
        self.stop_event = threading.Event()
        self.wake = threading.Event()
        self.native = None
        self.process = None
        self.borders = {}
        self.applied_colors = {}
        self.fallbacks = set()

    def stop(self):
        self.stop_event.set()
        self.wake.set()
        if self is not threading.current_thread() and self.is_alive():
            self.join(timeout=2.0)

    def run(self):
        try:
            self.native = _native_factory()
            if self.native is None:
                return
            deadline = time.monotonic() + _DISCOVERY_SECONDS
            while not self.stop_event.is_set():
                self.wake.clear()
                self.native.pump_messages()
                if self.process is None:
                    self.process = _find_browser_process(self.browser)
                    tracked = getattr(self.browser, '_xg_browser_process', None)
                    if self.process is None and (tracked is not None or _service_exited(self.browser)
                                                 or time.monotonic() >= deadline):
                        break
                if self.process is not None and not self._tick():
                    break
                self.wake.wait(_POLL_SECONDS)
        except Exception:
            # Optional decoration must never break browser startup/shutdown.
            _LOG.debug('Native browser frame stopped', exc_info=True)
        finally:
            try:
                if self.native is not None:
                    try:
                        self._clear()
                    finally:
                        self.native.close()
            except Exception:
                _LOG.debug('Native browser frame cleanup failed', exc_info=True)
            finally:
                self.stop_event.set()
                with _lock:
                    if _monitors.get(id(self.browser)) is self:
                        _monitors.pop(id(self.browser), None)

    def _owns(self, hwnd):
        return self.native.window_pid(hwnd) == self.process.pid

    def _remove(self, hwnd):
        original = self.borders.pop(hwnd, None)
        self.applied_colors.pop(hwnd, None)
        self.fallbacks.discard(hwnd)
        if original is not None and _alive(self.process) and self._owns(hwnd):
            self.native.set_border(hwnd, original)
        self.native.hide_outline(hwnd, destroy=True)

    def _clear(self):
        for hwnd in set(self.borders) | self.fallbacks:
            self._remove(hwnd)

    def _tick(self):
        if not _alive(self.process):
            return False
        if not _frames_enabled:
            self._clear()
            return True
        windows = set(self.native.windows_for_pid(self.process.pid))
        for hwnd in (set(self.borders) | self.fallbacks) - windows:
            self._remove(hwnd)
        color = self.color
        for hwnd in windows:
            # HWNDs can be reused after enumeration. Recheck immediately before
            # mutating another process's native window.
            if not self._owns(hwnd):
                continue
            if hwnd not in self.borders and hwnd not in self.fallbacks:
                original = self.native.get_border(hwnd)
                if self.native.set_border(hwnd, color):
                    self.borders[hwnd] = original if original is not None else _DEFAULT_COLOR
                    self.applied_colors[hwnd] = color
                else:
                    self.fallbacks.add(hwnd)
            elif hwnd in self.borders and self.applied_colors[hwnd] != color:
                if self.native.set_border(hwnd, color):
                    self.applied_colors[hwnd] = color
            if hwnd in self.fallbacks:
                if self.native.foreground_unobscured(hwnd):
                    self.native.show_outline(hwnd, color)
                else:
                    self.native.hide_outline(hwnd)
        return True


class _Win32Native:
    """Small ctypes boundary; all methods run on the owning monitor thread.

    Signatures follow the Microsoft Win32 API. DWM border color is attribute 34
    (Win11 build 22000+); 0xFFFFFFFF restores the system default.
    https://learn.microsoft.com/windows/win32/api/dwmapi/ne-dwmapi-dwmwindowattribute
    Layered WS_EX_TRANSPARENT windows pass mouse input to windows underneath.
    https://learn.microsoft.com/windows/win32/winmsg/window-features#layered-windows
    """
    def __init__(self):
        self.user32 = ctypes.WinDLL('user32', use_last_error=True)
        self.gdi32 = ctypes.WinDLL('gdi32', use_last_error=True)
        self.kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        self.dwmapi = ctypes.WinDLL('dwmapi', use_last_error=True)
        self.WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                        wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', self.WNDPROC),
                        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                        ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                        ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]

        self.WNDCLASS = WNDCLASS
        self._bind()
        self.instance = self.kernel32.GetModuleHandleW(None)
        self.outlines = {}
        self._brush = None
        self._class_name = None
        self._outline_color = None
        # Retain the callback until all windows and the class are destroyed.
        self._wndproc = self.WNDPROC(self._window_proc)
        # DWM frame bounds use physical pixels. Scope DPI awareness to this
        # thread so secondary-monitor scaling does not offset fallback strips.
        self._previous_dpi = None
        try:
            dpi = self.user32.SetThreadDpiAwarenessContext
        except AttributeError:
            pass
        else:
            dpi.restype = ctypes.c_void_p
            dpi.argtypes = [ctypes.c_void_p]
            self._previous_dpi = dpi(ctypes.c_void_p(-4)) or dpi(ctypes.c_void_p(-3))

    @staticmethod
    def _signature(dll, name, result, *arguments):
        method = getattr(dll, name)
        method.restype = result
        method.argtypes = list(arguments)

    def _bind(self):
        u, g, k, d = self.user32, self.gdi32, self.kernel32, self.dwmapi
        h, b, i, uint, dw = wintypes.HWND, wintypes.BOOL, ctypes.c_int, wintypes.UINT, wintypes.DWORD
        rectp = ctypes.POINTER(wintypes.RECT)
        bind = self._signature
        bind(u, 'EnumWindows', b, self.ENUMPROC, wintypes.LPARAM)
        bind(u, 'GetWindowThreadProcessId', dw, h, ctypes.POINTER(dw))
        bind(u, 'GetClassNameW', i, h, wintypes.LPWSTR, i)
        bind(u, 'IsWindowVisible', b, h)
        bind(u, 'IsIconic', b, h)
        bind(u, 'GetForegroundWindow', h)
        bind(u, 'GetWindowRect', b, h, rectp)
        bind(u, 'CreateWindowExW', h, dw, wintypes.LPCWSTR, wintypes.LPCWSTR, dw,
             i, i, i, i, h, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID)
        bind(u, 'DefWindowProcW', ctypes.c_ssize_t, h, uint, wintypes.WPARAM, wintypes.LPARAM)
        bind(u, 'RegisterClassW', wintypes.ATOM, ctypes.POINTER(self.WNDCLASS))
        bind(u, 'UnregisterClassW', b, wintypes.LPCWSTR, wintypes.HINSTANCE)
        bind(u, 'DestroyWindow', b, h)
        bind(u, 'ShowWindow', b, h, i)
        bind(u, 'SetWindowPos', b, h, h, i, i, i, i, uint)
        bind(u, 'SetLayeredWindowAttributes', b, h, dw, wintypes.BYTE, dw)
        bind(u, 'PeekMessageW', b, ctypes.POINTER(wintypes.MSG), h, uint, uint, uint)
        bind(u, 'TranslateMessage', b, ctypes.POINTER(wintypes.MSG))
        bind(u, 'DispatchMessageW', ctypes.c_ssize_t, ctypes.POINTER(wintypes.MSG))
        bind(g, 'CreateSolidBrush', wintypes.HBRUSH, dw)
        bind(g, 'DeleteObject', b, wintypes.HANDLE)
        bind(k, 'GetModuleHandleW', wintypes.HMODULE, wintypes.LPCWSTR)
        for name in ('DwmSetWindowAttribute', 'DwmGetWindowAttribute'):
            bind(d, name, ctypes.c_long, h, dw, wintypes.LPVOID, dw)

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == 0x0021:  # WM_MOUSEACTIVATE / MA_NOACTIVATE
            return 3
        if message == 0x0084:  # WM_NCHITTEST / HTTRANSPARENT
            return -1
        return self.user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def pump_messages(self):
        message = wintypes.MSG()
        while self.user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1):
            self.user32.TranslateMessage(ctypes.byref(message))
            self.user32.DispatchMessageW(ctypes.byref(message))

    def window_pid(self, hwnd):
        pid = wintypes.DWORD()
        self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return pid.value

    def _enumerate(self):
        result = []
        callback = self.ENUMPROC(lambda hwnd, _: result.append(hwnd) is None)
        self.user32.EnumWindows(callback, 0)
        return result

    def windows_for_pid(self, pid):
        result = []
        for hwnd in self._enumerate():
            if self.window_pid(hwnd) != pid or not self.user32.IsWindowVisible(hwnd):
                continue
            name = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, name, len(name))
            if name.value.startswith('Chrome_WidgetWin_'):
                result.append(hwnd)
        return result

    def get_border(self, hwnd):
        value = wintypes.DWORD()
        status = self.dwmapi.DwmGetWindowAttribute(hwnd, 34, ctypes.byref(value), ctypes.sizeof(value))
        return value.value if status >= 0 else None

    def set_border(self, hwnd, color):
        value = wintypes.DWORD(color)
        return self.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(value), ctypes.sizeof(value)) >= 0

    def _cloaked(self, hwnd):
        value = wintypes.DWORD()
        return (self.dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value)) >= 0
                and bool(value.value))

    def _bounds(self, hwnd):
        rect = wintypes.RECT()
        if self.dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect)) < 0:
            if not self.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
        return rect if rect.right > rect.left and rect.bottom > rect.top else None

    def foreground_unobscured(self, hwnd):
        if (self.user32.GetForegroundWindow() != hwnd
                or not self.user32.IsWindowVisible(hwnd)
                or self.user32.IsIconic(hwnd) or self._cloaked(hwnd)):
            return False
        bounds = self._bounds(hwnd)
        if bounds is None:
            return False
        overlays = {strip for strips in self.outlines.values() for strip in strips}
        # EnumWindows is in Z order. Refuse even partial coverage by another
        # visible window, including non-activating toasts/tooltips.
        for other in self._enumerate():
            if other == hwnd:
                return True
            if (other in overlays or not self.user32.IsWindowVisible(other)
                    or self.user32.IsIconic(other) or self._cloaked(other)):
                continue
            rect = self._bounds(other)
            if (rect is not None and rect.left < bounds.right and rect.right > bounds.left
                    and rect.top < bounds.bottom and rect.bottom > bounds.top):
                return False
        return False

    def _ensure_class(self, color):
        if self._class_name is not None and self._outline_color == color:
            return
        self._destroy_class()
        self._brush = self.gdi32.CreateSolidBrush(color)
        if not self._brush:
            raise OSError('Cannot create frame brush')
        name = 'XAntyFrame_%x_%x' % (id(self), color)
        definition = self.WNDCLASS()
        definition.lpfnWndProc = self._wndproc
        definition.hInstance = self.instance
        definition.hbrBackground = self._brush
        definition.lpszClassName = name
        if not self.user32.RegisterClassW(ctypes.byref(definition)):
            self.gdi32.DeleteObject(self._brush)
            self._brush = None
            raise OSError('Cannot register frame window class')
        self._class_name = name
        self._outline_color = color

    def show_outline(self, hwnd, color):
        # Recheck after enumeration before constructing/raising any strips.
        if not self.foreground_unobscured(hwnd):
            self.hide_outline(hwnd)
            return
        self._ensure_class(color)
        bounds = self._bounds(hwnd)
        if bounds is None:
            self.hide_outline(hwnd)
            return
        strips = self.outlines.get(hwnd)
        if strips is None:
            strips = self.outlines[hwnd] = []
            for _ in range(4):
                # TOOLWINDOW | TRANSPARENT | LAYERED | NOACTIVATE; WS_POPUP.
                strip = self.user32.CreateWindowExW(0x080800A0, self._class_name, '', 0x80000000,
                                                   0, 0, 0, 0, hwnd, None, self.instance, None)
                if not strip:
                    self.hide_outline(hwnd, destroy=True)
                    return
                strips.append(strip)
                if not self.user32.SetLayeredWindowAttributes(strip, 0, 255, 2):
                    self.hide_outline(hwnd, destroy=True)
                    return
        width, height = bounds.right - bounds.left, bounds.bottom - bounds.top
        thickness = min(3, width, height)
        rectangles = [(bounds.left, bounds.top, width, thickness),
                      (bounds.left, bounds.bottom - thickness, width, thickness),
                      (bounds.left, bounds.top, thickness, height),
                      (bounds.right - thickness, bounds.top, thickness, height)]
        for strip, (x, y, w, h) in zip(strips, rectangles):
            # Owned, non-topmost popups follow their owner's z-order. No call
            # ever activates a window or changes keyboard focus.
            self.user32.SetWindowPos(strip, None, x, y, w, h, 0x0010 | 0x0040)

    def hide_outline(self, hwnd, destroy=False):
        for strip in self.outlines.get(hwnd, []):
            if destroy:
                self.user32.DestroyWindow(strip)
            else:
                self.user32.ShowWindow(strip, 0)
        if destroy:
            self.outlines.pop(hwnd, None)

    def _destroy_class(self):
        for hwnd in list(self.outlines):
            self.hide_outline(hwnd, destroy=True)
        if self._class_name is not None:
            self.user32.UnregisterClassW(self._class_name, self.instance)
            self._class_name = None
        if self._brush:
            self.gdi32.DeleteObject(self._brush)
            self._brush = None

    def close(self):
        try:
            self._destroy_class()
        finally:
            if self._previous_dpi:
                self.user32.SetThreadDpiAwarenessContext(self._previous_dpi)
                self._previous_dpi = None


def _shutdown():
    with _lock:
        monitors = list(_monitors.values())
        _monitors.clear()
    for monitor in monitors:
        monitor.stop()


atexit.register(_shutdown)
