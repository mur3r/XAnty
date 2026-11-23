"""Chrome profile names and the ephemeral Windows taskbar identity."""
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from xgenius.config import Config


class ProfileIdentityTests(unittest.TestCase):
    def test_icon_rows_keep_short_name_and_number_readable(self):
        from xgenius.profile_identity import _icon_rows
        self.assertEqual(_icon_rows('Раб12'),('Раб','12'))
        self.assertEqual(_icon_rows('Work 1'),('Work','1'))

    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        self.config = Config(Path(workspace.name))

    def test_profile_uses_a_stable_taskbar_group_and_keeps_its_full_name(self):
        from xgenius.profile_identity import prepare_identity

        name = 'Юлія «Work» 😀'
        original = prepare_identity(self.config, 'julia', name, 'stable-profile', 7)
        renamed = prepare_identity(self.config, 'changed_julia', 'Інша назва', 'stable-profile', 7)
        other = prepare_identity(self.config, 'other', name, 'other-profile', 8)

        self.assertEqual(original.name, name)
        self.assertEqual(original.icon_text, 'ЮW7')
        self.assertEqual(original.app_id, renamed.app_id)
        self.assertNotEqual(original.app_id, other.app_id)
        self.assertTrue(original.app_id.isascii())
        self.assertNotIn(' ', original.app_id)

    def test_profile_name_preserves_chrome_preferences_and_other_profiles(self):
        from xgenius.profile_identity import prepare_identity

        path = self.config.get_profile_dir('julia')
        (path / 'Default').mkdir()
        prefs = path / 'Default' / 'Preferences'
        prefs.write_text(json.dumps({'profile': {'name': 'Person 1', 'avatar_index': 7},
                                     'session': {'restore_on_startup': 1}}), encoding='utf-8')
        local_state = path / 'Local State'
        local_state.write_text(json.dumps({'profile': {'info_cache': {
            'Default': {'name': 'Person 1', 'avatar_icon': 'avatar'},
            'Profile 1': {'name': 'A second profile'},
        }}, 'os_crypt': {'encrypted_key': 'unchanged'}}), encoding='utf-8')

        prepare_identity(self.config, 'julia', 'Юлія "Work"')

        self.assertEqual(json.loads(prefs.read_text(encoding='utf-8')), {
            'profile': {'name': 'Юлія "Work"', 'avatar_index': 7, 'using_default_name': False},
            'session': {'restore_on_startup': 1},
        })
        self.assertEqual(json.loads(local_state.read_text(encoding='utf-8')), {
            'profile': {'info_cache': {
                'Default': {'name': 'Юлія "Work"', 'avatar_icon': 'avatar', 'is_using_default_name': False},
                'Profile 1': {'name': 'A second profile'},
            }}, 'os_crypt': {'encrypted_key': 'unchanged'},
        })

    def test_fresh_profile_is_named_without_a_partially_initialized_cache_entry(self):
        from xgenius.profile_identity import prepare_identity

        profile = prepare_identity(self.config, 'some_account', '', 'stable-profile', 7)
        path = self.config.get_profile_dir('some_account')

        self.assertEqual(profile.name, 'some_account')
        self.assertEqual(json.loads((path / 'Default' / 'Preferences').read_text(encoding='utf-8')), {
            'profile': {'name': 'some_account', 'using_default_name': False},
        })
        self.assertFalse((path / 'Local State').exists())

    def test_invalid_chrome_preferences_are_not_replaced(self):
        from xgenius.profile_identity import prepare_identity

        path = self.config.get_profile_dir('julia') / 'Default'
        path.mkdir()
        prefs = path / 'Preferences'
        prefs.write_bytes(b'Not valid JSON')

        with self.assertLogs('xgenius.profile_identity', level='WARNING'):
            prepare_identity(self.config, 'julia', 'Profile name')

        self.assertEqual(prefs.read_bytes(), b'Not valid JSON')

    def test_icon_keeps_short_names_and_accepts_custom_text(self):
        from xgenius.profile_identity import prepare_identity

        first = prepare_identity(self.config, 'first', 'Олена', 'first', 3)
        second = prepare_identity(self.config, 'second', 'Довга назва акаунта', 'second', 14, 'Робота')

        self.assertEqual(first.icon_text, 'Олена')
        self.assertEqual(second.icon_text, 'Робота')
        self.assertEqual(second.name, 'Довга назва акаунта')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows taskbar icon')
    def test_real_ico_contains_high_contrast_text_at_each_size(self):
        from xgenius.profile_identity import prepare_identity

        icon = prepare_identity(self.config, 'julia', 'Олена').icon_path.read_bytes()

        self.assertEqual(struct.unpack_from('<HHH', icon), (0, 1, 4))
        for index, size in enumerate((16, 32, 48, 256)):
            width, height, _, _, planes, bits, length, offset = struct.unpack_from(
                '<BBBBHHII', icon, 6 + 16 * index)
            self.assertEqual((width or 256, height or 256, planes, bits), (size, size, 1, 32))
            self.assertEqual(struct.unpack_from('<Iii', icon, offset), (40, size, size * 2))
            self.assertGreaterEqual(length, 40 + size * size * 4)
            colors = struct.unpack_from(f'<{size * size}I', icon, offset + 40)
            self.assertTrue(any(pixel & 0xffffff == 0xffffff for pixel in colors), size)
            self.assertTrue(any(pixel & 0xff000000 == 0 for pixel in colors), size)


class TaskbarWindowTests(unittest.TestCase):
    def test_only_owned_windows_keep_identity_across_site_title_changes(self):
        from xgenius.profile_identity import ProfileIdentity, _TaskbarWindows

        native = NativeWindows()
        identity = ProfileIdentity('Повна назва', 'XAnty.Browser.first', 'Назва', None)
        windows = _TaskbarWindows(native, 43, identity)
        windows.refresh(11)
        windows.refresh(12)
        windows.refresh(13)

        self.assertEqual(native.get_title(11), 'Повна назва | First page')
        self.assertEqual(native.get_identity(11), ('XAnty.Browser.first', True))
        self.assertEqual(native.get_icon(11, 0), 67)
        self.assertEqual(native.get_icon(11, 1), 68)
        self.assertEqual(native.get_title(12), 'Unrelated browser')
        self.assertEqual(native.get_title(13), 'Owned hidden utility')

        native.set_title(11, 'Second page')
        windows.refresh(11)
        windows.refresh(11)
        self.assertEqual(native.get_title(11), 'Повна назва | Second page')

        windows.restore()
        self.assertEqual(native.get_title(11), 'Second page')
        self.assertEqual(native.get_identity(11), ('Chrome.Original', None))
        self.assertEqual(native.get_icon(11, 0), 5)
        self.assertEqual(native.get_icon(11, 1), 6)

    def test_restore_preserves_chrome_changes_made_after_the_last_observed_event(self):
        from xgenius.profile_identity import ProfileIdentity, _TaskbarWindows

        native = NativeWindows()
        identity = ProfileIdentity('My profile', 'XAnty.Browser.first', 'M', None)
        windows = _TaskbarWindows(native, 43, identity)
        windows.refresh(11)
        native.set_title(11, 'Chrome changed the title')
        native.set_icon(11, 0, 22)

        windows.restore()

        self.assertEqual(native.get_title(11), 'Chrome changed the title')
        self.assertEqual(native.get_icon(11, 0), 22)


class NativeWindows:
    icons = {0: 67, 1: 68}

    def __init__(self):
        self.windows = {
            11: {'pid': 43, 'visible': True, 'title': 'First page', 'group': ('Chrome.Original', None),
                 'icons': {0: 5, 1: 6}},
            12: {'pid': 99, 'visible': True, 'title': 'Unrelated browser'},
            13: {'pid': 43, 'visible': False, 'title': 'Owned hidden utility'},
        }

    def owns_window(self, hwnd, pid, visible=True):
        window = self.windows.get(hwnd)
        return window and window['pid'] == pid and (not visible or window['visible'])

    def get_title(self, hwnd):
        return self.windows[hwnd]['title']

    def set_title(self, hwnd, title):
        self.windows[hwnd]['title'] = title

    def get_identity(self, hwnd):
        return self.windows[hwnd]['group']

    def set_identity(self, hwnd, app_id, prevent_pinning):
        self.windows[hwnd]['group'] = (app_id, prevent_pinning)

    def get_icon(self, hwnd, kind):
        return self.windows[hwnd]['icons'][kind]

    def set_icon(self, hwnd, kind, icon):
        self.windows[hwnd]['icons'][kind] = icon
