"""Chrome profile names and per-profile Windows taskbar windows."""

import ctypes
import hashlib
import json
import logging
import os
import re
import struct
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from ctypes import wintypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import psutil

from xgenius.browser_workspace import _atomic_json


_LOG = logging.getLogger(__name__)
_BACKGROUNDS = (0x24527A, 0x2F6846, 0x854424, 0x62469B, 0x8C3650, 0x216666,
                0x744E27, 0x474F62, 0x8B402A, 0x365482, 0x743971, 0x476229)


@dataclass(frozen=True)
class ProfileIdentity:
    name: str
    app_id: str
    icon_text: str
    icon_path: Optional[Path]


def _name_preferences(path, name):
    if path.exists():
        with path.open(encoding='utf-8') as stream:
            prefs = json.load(stream)
    else:
        prefs = {}
    if not isinstance(prefs, dict):
        raise ValueError('Unexpected Chrome preferences')
    profile = prefs.setdefault('profile', {})
    if not isinstance(profile, dict):
        raise ValueError('Unexpected Chrome profile preferences')
    if profile.get('name') != name or profile.get('using_default_name') is not False:
        profile.update(name=name, using_default_name=False)
        _atomic_json(path, prefs)


def _name_cached_profile(path, name):
    if not path.is_file():
        return
    with path.open(encoding='utf-8') as stream:
        state = json.load(stream)
    # Chrome initializes this entry itself for a new profile.
    entry = state
    for key in ('profile', 'info_cache', 'Default'):
        if not isinstance(entry, dict):
            return
        entry = entry.get(key)
    if isinstance(entry, dict) and (entry.get('name') != name or entry.get('is_using_default_name') is not False):
        entry.update(name=name, is_using_default_name=False)
        _atomic_json(path, state)


def _icon_text(name, override, number, digest):
    if override:
        return ' '.join(override.replace('\0', '').split())[:8]
    if len(name) <= 8:
        return name
    parts = re.findall(r'[^\W_]+', unicodedata.normalize('NFC', name))
    initials = ''.join(part[0] for part in parts[:3]) if len(parts) > 1 else ''.join(parts)[:4]
    return (initials.upper() + str(number or digest[:2]).upper())[:8]


def prepare_identity(config, username, profile_name='', profile_id='', profile_number=None, icon_text=''):
    """Set Chrome's display name before launch, while the profile lease is held."""
    path = config.get_profile_dir(username)
    name = ' '.join((profile_name or '').replace('\0', '').split()) or username
    workspace = os.path.normcase(str(path.parent.resolve()))
    key = str(profile_id or username).casefold()
    digest = hashlib.sha256(f'{workspace}\0{key}'.encode()).hexdigest()
    text = _icon_text(name, icon_text, profile_number, digest)
    background = _BACKGROUNDS[int(digest[:8], 16) % len(_BACKGROUNDS)]
    for update, file_path in ((_name_preferences, path / 'Default' / 'Preferences'),
                              (_name_cached_profile, path / 'Local State')):
        try:
            update(file_path, name)
        except (OSError, UnicodeError, ValueError):
            _LOG.warning('Could not update the Chrome profile name in %s', file_path.name)
    icon_path = None
    if sys.platform == 'win32':
        try:
            icon_path = _write_icon(path / '.xanty-taskbar.ico', text, background)
        except OSError:
            _LOG.warning('Could not prepare the Windows taskbar icon')
    return ProfileIdentity(name, f'XAnty.Browser.{digest[:32]}', text, icon_path)


def _bind(dll, name, result, *arguments):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, arguments
    return function


def _icon_rows(text):
    if len(text) <= 4:
        return (text,)
    words=text.split()
    if len(words)==2 and all(len(word)<=4 for word in words):return tuple(words)
    numbered=re.fullmatch(r'(.{1,4}?)([0-9]{1,4})',text)
    if numbered:return numbered.groups()
    split = len(text) // 2
    return text[:split].strip(), text[split:].strip()


def _write_icon(path, text, color):
    sizes = (16, 32, 48, 256)
    painter = _IconPainter()
    images = [painter.draw(size, _icon_rows(text), color) for size in sizes]
    directory = bytearray(struct.pack('<HHH', 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for size, data in zip(sizes, images):
        directory.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        offset += len(data)
    data = bytes(directory) + b''.join(images)
    if path.is_file() and path.read_bytes() == data:
        return path
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('wb', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


class _IconPainter:
    """Use Windows font fallback to draw text in each ICO image at native size."""

    def __init__(self):
        gdi = ctypes.WinDLL('gdi32', use_last_error=True)
        user = ctypes.WinDLL('user32', use_last_error=True)
        handle = wintypes.HANDLE
        integer = ctypes.c_int
        self.create_dc = _bind(gdi, 'CreateCompatibleDC', handle, handle)
        self.delete_dc = _bind(gdi, 'DeleteDC', wintypes.BOOL, handle)
        self.create_dib = _bind(gdi, 'CreateDIBSection', handle, handle, ctypes.c_void_p,
                                wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), handle, wintypes.DWORD)
        self.select_object = _bind(gdi, 'SelectObject', handle, handle, handle)
        self.delete_object = _bind(gdi, 'DeleteObject', wintypes.BOOL, handle)
        self.set_text_color = _bind(gdi, 'SetTextColor', wintypes.DWORD, handle, wintypes.DWORD)
        self.set_bk_mode = _bind(gdi, 'SetBkMode', integer, handle, integer)
        self.flush = _bind(gdi, 'GdiFlush', wintypes.BOOL)
        self.create_font = _bind(gdi, 'CreateFontW', handle, *([integer] * 5), *([wintypes.DWORD] * 8),
                                 wintypes.LPCWSTR)
        self.draw_text = _bind(user, 'DrawTextW', integer, handle, wintypes.LPCWSTR, integer,
                               ctypes.POINTER(wintypes.RECT), wintypes.UINT)
        self.measure = _bind(gdi, 'GetTextExtentPoint32W', wintypes.BOOL, handle, wintypes.LPCWSTR,
                             integer, ctypes.POINTER(wintypes.SIZE))

    def draw(self, size, rows, color):
        dc = self.create_dc(None)
        if not dc:
            raise ctypes.WinError(ctypes.get_last_error())
        bitmap = old_bitmap = None
        data = ctypes.c_void_p()
        header = struct.pack('<IiiHHIIiiII', 40, size, size, 1, 32, 0, 0, 0, 0, 0, 0)
        try:
            bitmap = self.create_dib(dc, ctypes.create_string_buffer(header), 0, ctypes.byref(data), None, 0)
            if not bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            old_bitmap = self.select_object(dc, bitmap)
            if not old_bitmap:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(data, color.to_bytes(4, 'little') * (size * size), size * size * 4)
            self.set_text_color(dc, 0xffffff)
            self.set_bk_mode(dc, 1)  # TRANSPARENT
            self._draw_rows(dc, size, rows)
            self.flush()
            pixels = bytearray(ctypes.string_at(data, size * size * 4))
        finally:
            if old_bitmap:
                self.select_object(dc, old_bitmap)
            if bitmap:
                self.delete_object(bitmap)
            self.delete_dc(dc)

        pixels[3::4] = b'\xff' * (size * size)
        pitch = ((size + 31) // 32) * 4
        mask = bytearray(pitch * size)
        radius = max(1, size // 6)
        for y in range(radius):
            for x in range(radius):
                if (radius - x - 0.5) ** 2 + (radius - y - 0.5) ** 2 > radius ** 2:
                    for corner_y in (y, size - 1 - y):
                        for corner_x in (x, size - 1 - x):
                            pixel = (corner_y * size + corner_x) * 4
                            pixels[pixel:pixel + 4] = b'\0' * 4
                            mask[corner_y * pitch + corner_x // 8] |= 0x80 >> (corner_x % 8)
        return header[:8] + struct.pack('<i', size * 2) + header[12:] + pixels + mask

    def _draw_rows(self, dc, size, rows):
        margin = max(1, size // 10)
        row_height = (size - margin * 2) // len(rows)
        font_height = round(row_height * 0.81)
        width_limit = size - margin * 2
        font_width = 0
        lengths = [len(row.encode('utf-16-le')) // 2 for row in rows]
        for _ in range(3):
            font = self.create_font(-font_height, font_width, 0, 0, 700, 0, 0, 0, 1, 0, 0, 4, 0, 'Segoe UI')
            if not font:
                raise ctypes.WinError(ctypes.get_last_error())
            old_font = self.select_object(dc, font)
            try:
                widths = []
                for row, length in zip(rows, lengths):
                    measured = wintypes.SIZE()
                    self.measure(dc, row, length, ctypes.byref(measured))
                    widths.append(measured.cx)
                if max(widths) <= width_limit or font_width == 1:
                    for index, (row, length) in enumerate(zip(rows, lengths)):
                        top = margin + index * row_height
                        rectangle = wintypes.RECT(0, top, size, top + row_height)
                        # DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX.
                        self.draw_text(dc, row, length, ctypes.byref(rectangle), 0x0825)
                    return
                font_width = max(1, (font_width or round(font_height * 0.51)) * width_limit // max(widths) - 1)
            finally:
                self.select_object(dc, old_font)
                self.delete_object(font)


@dataclass
class _WindowState:
    title: str = ''
    applied_title: Optional[str] = None
    shell_identity: tuple = (None, None)
    original_icons: dict = field(default_factory=dict)


class _TaskbarWindows:
    def __init__(self, native, pid, identity):
        self.native = native
        self.pid = pid
        self.name = identity.name
        self.shell_identity = (identity.app_id, True)
        self.windows = {}

    def refresh(self, hwnd):
        if not self.native.owns_window(hwnd, self.pid):
            return
        state = self.windows.setdefault(hwnd, _WindowState())
        try:
            current = self.native.get_identity(hwnd)
            if current != self.shell_identity:
                state.shell_identity = tuple(
                    previous if value == target else value
                    for previous, value, target in zip(state.shell_identity, current, self.shell_identity)
                )
                self.native.set_identity(hwnd, *self.shell_identity)
        except OSError:
            _LOG.debug('Could not update the Chrome window taskbar group', exc_info=True)

        try:
            for kind, icon in self.native.icons.items():
                current = self.native.get_icon(hwnd, kind)
                if current != icon:
                    state.original_icons[kind] = current
                    self.native.set_icon(hwnd, kind, icon)
            title = self.native.get_title(hwnd)
            if state.applied_title != title:
                new_title = f'{self.name} | {title}' if title else self.name
                self.native.set_title(hwnd, new_title)
                state.title, state.applied_title = title, new_title
        except OSError:
            _LOG.debug('Could not update the Chrome window icon or title', exc_info=True)

    def restore(self):
        """Return whether every surviving window released our icon handles."""
        release_icons = True
        for hwnd, state in self.windows.items():
            if not self.native.owns_window(hwnd, self.pid, visible=False):
                continue
            try:
                if self.native.get_title(hwnd) == state.applied_title:
                    self.native.set_title(hwnd, state.title)
                identity = self.native.get_identity(hwnd)
                if identity == self.shell_identity:
                    self.native.set_identity(hwnd, *state.shell_identity)
            except OSError:
                _LOG.debug('Could not restore Chrome window metadata', exc_info=True)
            for kind, previous_icon in state.original_icons.items():
                try:
                    if self.native.get_icon(hwnd, kind) == self.native.icons[kind]:
                        self.native.set_icon(hwnd, kind, previous_icon)
                except OSError:
                    release_icons = False
        self.windows.clear()
        return release_icons


def attach_identity(browser, identity):
    """Watch the exact Chrome process established by browser lifecycle tracking."""
    process = getattr(browser, '_xg_browser_process', None)
    if sys.platform != 'win32' or process is None or getattr(browser, '_xg_identity_monitor', None) is not None:
        return
    browser._xg_identity_monitor = monitor = _IdentityMonitor(process, identity)
    monitor.start()


def detach_identity(browser):
    monitor = getattr(browser, '_xg_identity_monitor', None)
    if monitor is not None:
        browser._xg_identity_monitor = None
        monitor.stopping.set()
        monitor.join(timeout=0.75)


class _IdentityMonitor(threading.Thread):
    def __init__(self, process, identity):
        super().__init__(name=f'XAnty-taskbar-{process.pid}', daemon=True)
        self.process = process
        self.identity = identity
        self.stopping = threading.Event()

    def run(self):
        native = windows = None
        try:
            native = _WindowsNative(self.identity.icon_path)
            pid = self.process.pid
            windows = _TaskbarWindows(native, pid, self.identity)
            native.observe(pid)
            next_search = 0
            while not self.stopping.is_set() and self.process.is_running():
                for event, hwnd in native.pump_messages():
                    if event == 0x8001:  # EVENT_OBJECT_DESTROY
                        windows.windows.pop(hwnd, None)
                    elif not self.stopping.is_set():
                        windows.refresh(hwnd)
                if time.monotonic() >= next_search:
                    for hwnd in native.enumerate_windows():
                        if self.stopping.is_set():
                            break
                        windows.refresh(hwnd)
                    next_search = time.monotonic() + 1.0
                native.wait()
        except (OSError, psutil.Error):
            _LOG.debug('Windows taskbar identity observer stopped', exc_info=True)
        finally:
            if native is not None:
                in_use = windows is not None and self.process.is_running() and not windows.restore()
                native.close()
                if in_use:
                    try:
                        self.process.wait(timeout=20)
                    except psutil.Error:
                        return
                native.destroy_icons()


_GUID = ctypes.c_ubyte * 16
_IID_IPROPERTY_STORE = _GUID.from_buffer_copy(uuid.UUID('886d8eeb-8cf2-4446-8d02-cdba1dbdcf99').bytes_le)
_APP_MODEL_GUID = _GUID.from_buffer_copy(uuid.UUID('9f4c2855-9f79-4b39-a8d0-e1d42de1d5f3').bytes_le)


class _PropertyKey(ctypes.Structure):
    _fields_ = [('guid', _GUID), ('id', wintypes.DWORD)]


class _PropertyVector(ctypes.Structure):
    _fields_ = [('size', wintypes.ULONG), ('values', ctypes.c_void_p)]


class _PropertyData(ctypes.Union):
    _fields_ = [('string', ctypes.c_void_p), ('boolean', ctypes.c_short), ('_vector', _PropertyVector)]


class _PropertyVariant(ctypes.Structure):
    _fields_ = [('type', wintypes.USHORT), ('_reserved', wintypes.USHORT * 3), ('data', _PropertyData)]


_APP_ID = _PropertyKey(_APP_MODEL_GUID, 5)
_PREVENT_PINNING = _PropertyKey(_APP_MODEL_GUID, 9)


class _WindowPropertyStore:
    def __init__(self, shell, ole, hwnd):
        self.pointer = ctypes.c_void_p()
        self.clear = _bind(ole, 'PropVariantClear', ctypes.c_long, ctypes.POINTER(_PropertyVariant))
        get_store = _bind(shell, 'SHGetPropertyStoreForWindow', ctypes.c_long, wintypes.HWND,
                          ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))
        self.check(get_store(hwnd, ctypes.byref(_IID_IPROPERTY_STORE), ctypes.byref(self.pointer)))
        self.methods = ctypes.cast(self.pointer, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents

    @staticmethod
    def check(result):
        if result < 0:
            raise OSError(f'Windows window property error 0x{result & 0xffffffff:08x}')

    def _call(self, index, restype, args, *values):
        return ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *args)(self.methods[index])(self.pointer, *values)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self._call(2, wintypes.ULONG, ())  # IUnknown::Release

    def get(self, key):
        value = _PropertyVariant()
        args = (ctypes.POINTER(_PropertyKey), ctypes.POINTER(_PropertyVariant))
        try:
            self.check(self._call(5, ctypes.c_long, args, ctypes.byref(key), ctypes.byref(value)))
            if value.type == 31 and value.data.string:  # VT_LPWSTR
                return ctypes.wstring_at(value.data.string)
            if value.type == 11:  # VT_BOOL
                return bool(value.data.boolean)
            return None
        finally:
            self.clear(ctypes.byref(value))

    def set(self, key, data):
        value = _PropertyVariant()
        if isinstance(data, str):
            buffer = ctypes.create_unicode_buffer(data)
            value.type, value.data.string = 31, ctypes.addressof(buffer)
        elif isinstance(data, bool):
            value.type, value.data.boolean = 11, -1 if data else 0
        args = (ctypes.POINTER(_PropertyKey), ctypes.POINTER(_PropertyVariant))
        self.check(self._call(6, ctypes.c_long, args, ctypes.byref(key), ctypes.byref(value)))


class _WindowsNative:
    def __init__(self, icon_path):
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.shell = ctypes.WinDLL('shell32', use_last_error=True)
        self.ole = ctypes.WinDLL('ole32', use_last_error=True)
        self.events = []
        self.hook = None
        self.icons = {}
        self._bind_functions()
        _WindowPropertyStore.check(self.ole.CoInitializeEx(None, 2))  # COINIT_APARTMENTTHREADED
        if icon_path:
            # ICON_SMALL and ICON_BIG dimensions follow the Windows system metrics.
            for kind, x_metric, y_metric in ((0, 49, 50), (1, 11, 12)):
                icon = self.load_image(None, str(icon_path), 1, self.metrics(x_metric), self.metrics(y_metric), 0x10)
                if icon:
                    self.icons[kind] = icon

    def _bind_functions(self):
        user = self.user
        hwnd, boolean, uint, dword = wintypes.HWND, wintypes.BOOL, wintypes.UINT, wintypes.DWORD
        handle, wparam, lparam = wintypes.HANDLE, wintypes.WPARAM, wintypes.LPARAM
        integer = ctypes.c_int
        self.enum_callback = ctypes.WINFUNCTYPE(boolean, hwnd, lparam)
        self.event_callback = ctypes.WINFUNCTYPE(None, handle, dword, hwnd, wintypes.LONG, wintypes.LONG, dword, dword)
        self.enum_windows = _bind(user, 'EnumWindows', boolean, self.enum_callback, lparam)
        self.pid_for_window = _bind(user, 'GetWindowThreadProcessId', dword, hwnd, ctypes.POINTER(dword))
        self.get_window = _bind(user, 'GetWindow', hwnd, hwnd, uint)
        self.visible = _bind(user, 'IsWindowVisible', boolean, hwnd)
        self.class_name = _bind(user, 'GetClassNameW', integer, hwnd, wintypes.LPWSTR, integer)
        self.title_length = _bind(user, 'GetWindowTextLengthW', integer, hwnd)
        self.window_text = _bind(user, 'GetWindowTextW', integer, hwnd, wintypes.LPWSTR, integer)
        self.send = _bind(user, 'SendMessageTimeoutW', ctypes.c_ssize_t, hwnd, uint, wparam, lparam, uint, uint,
                          ctypes.POINTER(ctypes.c_size_t))
        self.set_hook = _bind(user, 'SetWinEventHook', handle, dword, dword, handle, self.event_callback, dword, dword, uint)
        self.unhook = _bind(user, 'UnhookWinEvent', boolean, handle)
        msg = ctypes.POINTER(wintypes.MSG)
        self.peek = _bind(user, 'PeekMessageW', boolean, msg, hwnd, uint, uint, uint)
        self.dispatch = _bind(user, 'DispatchMessageW', ctypes.c_ssize_t, msg)
        self.wait_messages = _bind(user, 'MsgWaitForMultipleObjectsEx', dword, dword, ctypes.POINTER(handle), dword, dword, dword)
        self.metrics = _bind(user, 'GetSystemMetrics', integer, integer)
        self.load_image = _bind(user, 'LoadImageW', handle, handle, wintypes.LPCWSTR, uint, integer, integer, uint)
        self.destroy_icon = _bind(user, 'DestroyIcon', boolean, handle)
        _bind(self.ole, 'CoInitializeEx', ctypes.c_long, ctypes.c_void_p, dword)
        _bind(self.ole, 'CoUninitialize', None)

    def observe(self, pid):
        @self.event_callback
        def event(_hook, code, hwnd, obj, child, _thread, _time):
            if hwnd and obj == child == 0 and code in (0x8000, 0x8001, 0x8002, 0x800C):
                self.events.append((code, hwnd))

        self.on_event = event  # The callback remains referenced until unhooked.
        self.hook = self.set_hook(0x8000, 0x800C, None, event, pid, 0, 0)

    def pump_messages(self):
        message = wintypes.MSG()
        while self.peek(ctypes.byref(message), None, 0, 0, 1):
            self.dispatch(ctypes.byref(message))
        events, self.events = self.events, []
        return events

    def wait(self):
        self.wait_messages(0, None, 150, 0x04FF, 4)  # QS_ALLINPUT, MWMO_INPUTAVAILABLE

    def enumerate_windows(self):
        windows = []

        @self.enum_callback
        def add(hwnd, _context):
            windows.append(hwnd)
            return True

        self.enum_windows(add, 0)
        return windows

    def owns_window(self, hwnd, pid, visible=True):
        owner = wintypes.DWORD()
        if not self.pid_for_window(hwnd, ctypes.byref(owner)) or owner.value != pid:
            return False
        if visible and (not self.visible(hwnd) or self.get_window(hwnd, 4)):  # GW_OWNER
            return False
        name = ctypes.create_unicode_buffer(64)
        self.class_name(hwnd, name, len(name))
        return name.value == 'Chrome_WidgetWin_1'

    def _message(self, hwnd, code, wparam=0, lparam=0):
        result = ctypes.c_size_t()
        # SMTO_ABORTIFHUNG | SMTO_ERRORONEXIT.
        if not self.send(hwnd, code, wparam, lparam, 0x22, 100, ctypes.byref(result)):
            raise ctypes.WinError(ctypes.get_last_error())
        return result.value

    def get_title(self, hwnd):
        text = ctypes.create_unicode_buffer(self.title_length(hwnd) + 1)
        self.window_text(hwnd, text, len(text))
        return text.value

    def set_title(self, hwnd, title):
        buffer = ctypes.create_unicode_buffer(title)
        self._message(hwnd, 0x000C, 0, ctypes.addressof(buffer))  # WM_SETTEXT

    def get_icon(self, hwnd, kind):
        return self._message(hwnd, 0x007F, kind)  # WM_GETICON

    def set_icon(self, hwnd, kind, icon):
        self._message(hwnd, 0x0080, kind, icon)  # WM_SETICON

    def get_identity(self, hwnd):
        with _WindowPropertyStore(self.shell, self.ole, hwnd) as properties:
            return properties.get(_APP_ID), properties.get(_PREVENT_PINNING)

    def set_identity(self, hwnd, app_id, prevent_pinning):
        with _WindowPropertyStore(self.shell, self.ole, hwnd) as properties:
            # Set pinning before replacing the AppID. Chrome relaunches must go through XAnty.
            properties.set(_PREVENT_PINNING, prevent_pinning)
            properties.set(_APP_ID, app_id)

    def close(self):
        if self.hook:
            self.unhook(self.hook)
        self.ole.CoUninitialize()

    def destroy_icons(self):
        for icon in self.icons.values():
            self.destroy_icon(icon)
        self.icons.clear()
