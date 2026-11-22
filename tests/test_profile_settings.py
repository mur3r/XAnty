"""Browser settings reject unusable inputs and remain stable per profile."""
import importlib.util
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location('profile_preferences',
    Path(__file__).resolve().parents[1] / 'xgenius' / 'profile_settings.py')
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


class ProfileSettingsTests(unittest.TestCase):
    def test_defaults_and_explicit_preferences(self):
        self.assertEqual(settings.browser_settings({}), {
            'browser_language': '', 'browser_timezone': '',
            'window_width': 1024, 'window_height': 768})
        self.assertEqual(settings.browser_settings({
            'browser_language': 'uk-UA', 'browser_timezone': 'Europe/Kyiv',
            'window_width': '1280', 'window_height': '800'})['window_width'], 1280)

    def test_reject_flags_paths_and_bad_window_sizes(self):
        for bad in ({'browser_language': '--lang=bad'},
                    {'browser_timezone': '../Europe/Kyiv'},
                    {'browser_timezone': 'Europe/Kyiv\n--arg'},
                    {'window_width': 0}, {'window_height': True},
                    {'window_width': '99999999'}):
            with self.subTest(bad=bad), self.assertRaises(settings.ProfileSettingsError):
                settings.browser_settings(bad)


if __name__ == '__main__':
    unittest.main()
