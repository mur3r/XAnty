"""Cookie exports stay within the selected X profile and remain restorable."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


module_path = Path(__file__).resolve().parents[1] / 'xgenius' / 'cookies.py'
spec = importlib.util.spec_from_file_location('session_cookies', module_path)
cookies = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cookies)


def sample(value='secret'):
    return {'name': 'auth_token', 'value': value, 'domain': '.x.com', 'path': '/',
            'secure': True, 'httpOnly': True, 'expiry': 1910000000}


class Browser:
    def __init__(self, current=None):
        self.current = current if current is not None else []
        self.added = []
        self.visited = []

    def get_cookies(self):
        return self.current

    def get(self, url):
        self.visited.append(url)

    def add_cookie(self, cookie):
        self.added.append(cookie)


class CookieTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.config = SimpleNamespace(base_dir=Path(directory.name))

    def test_import_export_and_restore_per_profile(self):
        source = {'cookies': [{**sample('alpha'), 'expirationDate': 1910000000},
                              {'name': 'tracking', 'value': 'skip', 'domain': 'x.com.evil.test'}]}
        self.assertEqual(cookies.store_cookies(self.config, 'alice', json.dumps(source)), 1)
        self.assertEqual(cookies.store_cookies(self.config, 'bob', [sample('beta')]), 1)
        self.assertEqual(cookies.read_cookies(self.config, 'alice')[0]['value'], 'alpha')
        self.assertEqual(cookies.read_cookies(self.config, 'bob')[0]['value'], 'beta')
        browser = Browser()
        cookies.load_cookies(browser, self.config, 'alice')
        self.assertEqual(browser.visited, ['https://x.com'])
        self.assertEqual(browser.added[0]['value'], 'alpha')
        self.assertEqual(len(browser.added), 1)

    def test_empty_or_unrelated_page_does_not_erase_saved_session(self):
        cookies.store_cookies(self.config, 'alice', [sample()])
        cookies.save_cookies(Browser([{'name': 'fake', 'value': 'x', 'domain': 'x.com.evil.test'}]),
                             self.config, 'alice')
        self.assertEqual(cookies.read_cookies(self.config, 'alice')[0]['value'], 'secret')
        cookies.save_cookies(Browser([sample('updated')]), self.config, 'alice')
        self.assertEqual(cookies.read_cookies(self.config, 'alice')[0]['value'], 'updated')

    def test_netscape_and_legacy_mapping(self):
        text = '# Netscape HTTP Cookie File\n.x.com\tTRUE\t/\tTRUE\t1910000000\tauth_token\tv\n'
        self.assertEqual(cookies.normalize_cookies(text)[0]['value'], 'v')
        self.assertEqual(cookies.normalize_cookies({'.x.com': [sample()]})[0]['value'], 'secret')

    def test_invalid_data_and_path_rejected(self):
        with self.assertRaises(cookies.CookieError):
            cookies.store_cookies(self.config, 'alice', [{'domain': '.x.com', 'name': 'x'}])
        with self.assertRaises(cookies.CookieError):
            cookies.store_cookies(self.config, '../other', [sample()])
        with self.assertRaises(cookies.CookieError):
            cookies.store_cookies(self.config, 'alice', [
                {'domain': 'x.com.evil.test', 'name': 'auth_token', 'value': 'evil'}])
        self.assertFalse((self.config.base_dir / 'kook' / '@alice' / 'cookies.json').exists())


if __name__ == '__main__':
    unittest.main()
