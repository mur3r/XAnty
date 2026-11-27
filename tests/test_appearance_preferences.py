import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xgenius.preferences import read_preferences, save_preferences


class AppearancePreferencesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.home = patch('xgenius.preferences.application_home', return_value=self.root)
        self.home.start()
        self.addCleanup(self.home.stop)

    def test_colors_for_both_themes_and_panel_state_survive_restart_and_other_preference_changes(self):
        colors = {'dark': {'accent': '#12ab34', 'background': '#001122'}, 'light': {'accent': '#CDEF12'}}
        save_preferences({'custom_colors': colors, 'folders_collapsed': True, 'theme': 'light'})
        saved = read_preferences()
        self.assertEqual(saved['custom_colors'], colors)
        self.assertTrue(saved['folders_collapsed'])
        save_preferences({'language': 'uk'})
        self.assertEqual(read_preferences()['custom_colors'], colors)
        self.assertTrue(read_preferences()['folders_collapsed'])
        self.assertEqual(read_preferences()['theme'], 'light')
        save_preferences({'custom_colors': {'dark': colors['dark']}})
        self.assertEqual(read_preferences()['custom_colors'], {'dark': colors['dark']})

    def test_invalid_colors_or_panel_values_never_modify_saved_settings(self):
        save_preferences({'custom_colors': {'dark': {'accent': '#112233'}}})
        original = (self.root / 'preferences.json').read_bytes()
        for colors in ([], None, {'unknown': {}}, {'dark': []}, {'dark': {'unknown': '#112233'}},
                       {'dark': {'accent': 'red;display:none'}}, {'dark': {'accent': '#123'}},
                       {'light': {'accent': 123}}, {'dark': {'accent': '#123456;'}}):
            with self.subTest(colors=colors), self.assertRaises(ValueError):
                save_preferences({'custom_colors': colors})
            self.assertEqual((self.root / 'preferences.json').read_bytes(), original)
        for value in ('false', 0, None):
            with self.assertRaises(ValueError):
                save_preferences({'folders_collapsed': value})
            self.assertEqual((self.root / 'preferences.json').read_bytes(), original)

    def test_legacy_or_corrupt_preferences_keep_a_usable_default_palette_and_panel(self):
        for value in ({'language': 'uk'}, {'custom_colors': 'invalid', 'folders_collapsed': 'false'}, []):
            (self.root / 'preferences.json').write_text(json.dumps(value))
            prefs = read_preferences()
            self.assertEqual(prefs['custom_colors'], {})
            self.assertFalse(prefs['folders_collapsed'])

    def test_failed_atomic_save_retains_previous_colors(self):
        save_preferences({'custom_colors': {'dark': {'accent': '#112233'}}})
        original = (self.root / 'preferences.json').read_bytes()
        with patch('xgenius.preferences.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                save_preferences({'custom_colors': {'dark': {'accent': '#334455'}}})
        self.assertEqual((self.root / 'preferences.json').read_bytes(), original)
        self.assertEqual(list(self.root.iterdir()), [self.root / 'preferences.json'])
