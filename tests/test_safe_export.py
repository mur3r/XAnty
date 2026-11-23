"""Privacy exports cannot copy credentials through alternate profile stores."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from xgenius.config import Config
from xgenius.portable_session import store_session
from xgenius.profile_archive import ArchiveError, export_package, inspect_package


class SafeExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(self.root / 'workspace')
        self.destination = self.root / 'safe.xanty'
        self.secret = 'SENTINEL_PRIVATE_CREDENTIAL_8192'
        self.account = {
            'username': 'alice', 'password': self.secret, 'auth_token': self.secret,
            'ct0_token': self.secret, 'proxy': 'http://user:' + self.secret + '@proxy.test:80',
            'proxy_rotation_url': 'https://provider.example/rotate?key=' + self.secret,
            'user_agent': 'https://example.com/?token=' + self.secret,
            'notes': self.secret, 'tags': [self.secret], 'group': self.secret,
            'profile_name': self.secret, 'auto_login': True,
            'dolphin_source': {'localStorage': {'session': self.secret}},
            'browser_language': 'uk-UA', 'window_width': 1280,
        }
        profile = self.config.get_profile_dir('alice')
        for relative in ('Default/Network/Cookies', 'Default/Login Data',
                         'Default/Local Storage/leveldb/a.ldb', 'Default/Session Storage/a.log',
                         'Default/IndexedDB/store/00001.ldb', 'Default/Local Extension Settings/id/a.log',
                         'Default/Service Worker/CacheStorage/cache', 'Default/Preferences',
                         'Default/Extensions/id/manifest.json', 'Local State'):
            path = profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'\x00binary\xff' + self.secret.encode())
        store_session(self.config, 'alice', [
            {'name': 'session', 'value': self.secret, 'domain': 'example.com'}])
        tabs = self.config.base_dir / 'kook' / '@alice' / 'tabs.json'
        tabs.write_text(json.dumps({'urls': ['https://example.com/?token=' + self.secret]}))

    def test_each_exclusion_removes_indirect_secrets_and_has_exact_checksums(self):
        original = copy.deepcopy(self.account)
        for flag in ('include_passwords', 'include_tokens', 'include_cookies',
                     'include_proxy_credentials', 'include_browser_data'):
            with self.subTest(flag=flag):
                result = export_package(self.config, [self.account], self.destination,
                                        folders=[self.secret], privacy={flag: False})
                with ZipFile(self.destination) as archive:
                    members = {name: archive.read(name) for name in archive.namelist()}
                self.assertNotIn(self.secret.encode(), b''.join(members.values()))
                self.assertNotIn(self.secret, json.dumps(result))
                self.assertEqual(set(members), {'manifest.json', 'checksums.json',
                                                'profiles/000000/cookies.json'})
                manifest = json.loads(members['manifest.json'])
                account = manifest['profiles'][0]['account']
                self.assertEqual(account['username'], 'alice')
                self.assertEqual(account['browser_language'], 'uk-UA')
                self.assertEqual(account['window_width'], 1280)
                self.assertFalse(account.get('auto_login', False))
                self.assertEqual(manifest['folders'], [])
                self.assertEqual(json.loads(members['profiles/000000/cookies.json']), [])
                checksums = json.loads(members['checksums.json'])['files']
                self.assertEqual(set(checksums), set(members) - {'checksums.json'})
                for name, digest in checksums.items():
                    self.assertEqual(digest, hashlib.sha256(members[name]).hexdigest())
                self.assertFalse(result['privacy']['include_browser_data'])
                self.assertTrue(any('settings-only' in warning.lower() for warning in result['warnings']))
                self.assertEqual(inspect_package(self.destination)['integrity'], 'verified')
        self.assertEqual(self.account, original)

    def test_default_and_all_true_preserve_full_transfer(self):
        for privacy in (None, {'include_passwords': True, 'include_tokens': True,
                               'include_cookies': True, 'include_proxy_credentials': True,
                               'include_browser_data': True}):
            with self.subTest(privacy=privacy):
                export_package(self.config, [self.account], self.destination, privacy=privacy)
                with ZipFile(self.destination) as archive:
                    self.assertEqual(json.loads(archive.read('manifest.json'))['profiles'][0]['account'],
                                     self.account)
                    self.assertIn('profiles/000000/browser/Default/Login Data', archive.namelist())
                    self.assertIn(self.secret, archive.read('profiles/000000/cookies.json').decode())

    def test_rejects_unknown_or_nonboolean_policy_without_creating_archive(self):
        for privacy in ([], 'safe', {'include_passwords': 0}, {'include_cookies': None},
                        {'include_browser_data': 'false'}, {'unknown': False}):
            with self.subTest(privacy=privacy):
                with self.assertRaises(ArchiveError):
                    export_package(self.config, [self.account], self.destination, privacy=privacy)
                self.assertFalse(self.destination.exists())


if __name__ == '__main__':
    unittest.main()
