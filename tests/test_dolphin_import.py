"""Dolphin migration keeps credentials out of previews and reports unsupported data."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / 'xgenius'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = types.ModuleType('xgenius')
package.__path__ = [str(ROOT)]
with patch.dict(sys.modules, {'xgenius': package}):
    load_module('xgenius.cookies', ROOT / 'cookies.py')
    load_module('xgenius.profile_settings', ROOT / 'profile_settings.py')
    load_module('xgenius.proxy_service', ROOT / 'proxy_service.py')
    dolphin = load_module('xgenius.dolphin_import', ROOT / 'dolphin_import.py')
API_BASE, COOKIE_BASE = dolphin.API_BASE, dolphin.COOKIE_BASE
DolphinClient, DolphinError = dolphin.DolphinClient, dolphin.DolphinError
map_profile, suggested_username = dolphin.map_profile, dolphin.suggested_username


class Response:
    def __init__(self, data, status=200):
        self.data, self.status_code = data, status

    def json(self):
        return self.data


class Session:
    def __init__(self, replies):
        self.headers = {}
        self.replies = replies
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.replies.pop(0)

    def close(self):
        pass


PROFILE = {'id': 123, 'name': '@alice', 'platform': 'windows',
           'proxy': {'type': 'http', 'host': 'proxy.example', 'port': 8080,
                     'login': 'me', 'password': 'private'},
           'locale': {'mode': 'manual', 'value': 'en_US'},
           'timezone': {'mode': 'manual', 'value': 'Europe/Kyiv'},
           'screen': {'resolution': '1280x800'}}


class DolphinImportTests(unittest.TestCase):
    def test_single_profile_settings_proxy_and_x_cookies(self):
        session = Session([Response({'data': PROFILE}), Response({'success': True, 'cookies': [
            {'name': 'auth_token', 'value': 'secret', 'domain': '.x.com', 'path': '/', 'sameSite': 'strict'},
            {'name': 'other', 'value': 'skip', 'domain': '.unrelated.example'}]})])
        client = DolphinClient('jwt-token', session)
        account, cookies, warnings = client.inspect(123, folder='Imported')
        self.assertEqual(account['username'], 'alice')
        self.assertEqual(account['group'], 'Imported')
        self.assertEqual(account['browser_language'], 'en-US')
        self.assertEqual(account['browser_timezone'], 'Europe/Kyiv')
        self.assertEqual(account['window_width'], 1280)
        self.assertEqual(account['proxy'], 'http://me:private@proxy.example:8080')
        self.assertEqual(cookies[0]['value'], 'secret')
        self.assertEqual(cookies[0]['sameSite'], 'Strict')
        self.assertEqual(len(cookies), 1)
        self.assertTrue(any('fingerprint' in item for item in warnings))
        self.assertEqual(session.calls[0][1], f'{API_BASE}/browser_profiles/123')
        self.assertEqual(session.calls[1][1], f'{COOKIE_BASE}/cookies/export')
        self.assertEqual(session.headers['Authorization'], 'Bearer jwt-token')

    def test_cookie_export_unavailable_keeps_profile_and_no_secrets_in_message(self):
        session = Session([Response({'data': PROFILE}), Response({}, 402)])
        account, cookies, warnings = DolphinClient('jwt-token', session).inspect(123)
        self.assertEqual(account['username'], 'alice')
        self.assertEqual(cookies, [])
        self.assertTrue(any('paid plan' in item for item in warnings))
        self.assertNotIn('private', '\n'.join(warnings))

    def test_cursor_pages_and_untrusted_next_link(self):
        next_page = f'{API_BASE}/browser_profiles/list-cursor?cursor=next'
        session = Session([Response({'data': [{'id': 1}], 'next_page_url': next_page}),
                           Response({'data': [{'id': 2}], 'next_page_url': None})])
        self.assertEqual(DolphinClient('jwt-token', session).profile_ids(), [1, 2])
        hostile = Session([Response({'data': [{'id': 1}],
                                     'next_page_url': 'https://evil.example/browser_profiles/list-cursor?cursor=x'})])
        with self.assertRaisesRegex(DolphinError, 'unexpected next page'):
            DolphinClient('jwt-token', hostile).profile_ids()
        self.assertEqual(len(hostile.calls), 1)

    def test_unknown_source_name_and_socks_proxy_are_reported(self):
        raw = {**PROFILE, 'name': 'My workspace', 'proxy': {'type': 'socks5', 'host': 'a', 'port': 10}}
        self.assertEqual(suggested_username(raw), 'dolphin_123')
        account, warnings = map_profile(raw)
        self.assertEqual(account['proxy'], '')
        self.assertTrue(any('Unsupported proxy' in item for item in warnings))
        with self.assertRaises(DolphinError):
            DolphinClient('not-a-token', Session([])).get_profile('../profile')

    def test_invalid_locale_does_not_discard_valid_timezone_and_size(self):
        raw = {**PROFILE, 'locale': {'mode': 'manual', 'value': 'invalid locale'}}
        account, warnings = map_profile(raw)
        self.assertEqual(account['browser_language'], '')
        self.assertEqual(account['browser_timezone'], 'Europe/Kyiv')
        self.assertEqual(account['window_width'], 1280)
        self.assertTrue(any('browser_language' in item for item in warnings))


if __name__ == '__main__':
    unittest.main()
