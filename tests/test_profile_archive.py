"""Profile packages preserve sessions and data without trusting archive paths."""
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZipFile

from xgenius.config import Config
from xgenius.cookies import read_cookies, store_cookies
from xgenius.folders import FolderStore
from xgenius.portable_session import apply_session, session_path, store_session
from xgenius.profile_archive import ArchiveError, export_package, import_package, inspect_package


class AccountStore:
    def __init__(self, data=None):
        self.data = copy.deepcopy(data or [])
        self._data_lock = threading.RLock()

    def load_accounts(self):
        with self._data_lock:
            return copy.deepcopy(self.data)

    def save_accounts(self, value):
        with self._data_lock:
            self.data = copy.deepcopy(value)


class ProfileArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = Config(self.root / 'source')
        self.target = Config(self.root / 'target')
        self.accounts = [
            {'username': 'alice', 'profile_name': 'Work profile', 'group': 'Campaign', 'proxy': 'http://u:p@proxy.test:80',
             'password': 'x-password', 'auth_token': 'x-token', 'ct0_token': 'csrf-token', 'notes': 'My note',
             'auto_login': True, 'browser_language': 'uk-UA', 'browser_timezone': 'Europe/Kyiv',
             'window_width': 1280, 'window_height': 800, 'dolphin_profile_id': 11},
            {'username': 'bob', 'group': 'Other', 'auto_login': False},
        ]
        self.profile = self.source.get_profile_dir('alice')
        for relative, content in [('Default/Preferences', '{"setting":"value"}'),
                                  ('Default/Local Storage/leveldb/data.ldb', 'local storage'),
                                  ('Default/Extensions/extension/version/manifest.json', '{"name":"sample"}'),
                                  ('Default/Cache/garbage', 'do not transfer'), ('SingletonLock', 'do not transfer')]:
            path = self.profile / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        (self.profile / 'Local State').write_text(json.dumps({'os_crypt': {'encrypted_key': 'old-machine'}, 'keep': 1}))
        self.cookies = [{'name': 'auth_token', 'value': 'x-session', 'domain': '.x.com', 'path': '/', 'httpOnly': True},
                        {'name': 'session', 'value': 'other-session', 'domain': 'example.com', 'path': '/', 'secure': True}]
        store_session(self.source, 'alice', self.cookies)
        store_cookies(self.source, 'alice', [self.cookies[0]])
        self.archive = self.root / 'profiles.xanty'
        self.folders = FolderStore(self.target.base_dir / 'folders.json')

    def export(self, accounts=None):
        return export_package(self.source, accounts or self.accounts, self.archive, folders=['Campaign', 'Empty folder'])

    def test_missing_session_data_is_explained_before_import_starts(self):
        with ZipFile(self.archive, 'w') as archive:
            archive.writestr('manifest.json', json.dumps({'format':'xanty-profile-package','version':1,
                'profiles':[{'key':'000000','account':{'username':'alice'}}]}))
        with self.assertRaisesRegex(ArchiveError, 'missing session files'):
            inspect_package(self.archive)

    def test_permission_failure_explains_workspace_access(self):
        self.export()
        with patch('xgenius.profile_archive.store_session', side_effect=PermissionError('denied')):
            with self.assertRaisesRegex(ArchiveError, 'write access'):
                import_package(self.target, AccountStore(), self.folders, self.archive)

    def test_round_trip_all_profiles_cookies_storage_extensions_and_metadata(self):
        result = self.export()
        self.assertEqual(result['total'], 2)
        self.assertEqual(inspect_package(self.archive)['total'], 2)
        with ZipFile(self.archive) as archive:
            self.assertFalse(any('Cache/' in name or 'Singleton' in name for name in archive.namelist()))
        store = AccountStore()
        result = import_package(self.target, store, self.folders, self.archive, commit_lock=store._data_lock)
        self.assertEqual([row['status'] for row in result['report']], ['imported', 'imported'])
        self.assertEqual(store.data, self.accounts)
        restored = self.target.get_profile_dir('alice')
        self.assertEqual((restored / 'Default/Local Storage/leveldb/data.ldb').read_text(), 'local storage')
        self.assertTrue((restored / 'Default/Extensions/extension/version/manifest.json').is_file())
        self.assertEqual(json.loads((restored / 'Local State').read_text()), {'keep': 1})
        snapshot = json.loads(session_path(self.target, 'alice').read_text())
        self.assertTrue(snapshot['pending'])
        self.assertEqual({c['domain'] for c in snapshot['cookies']}, {'.x.com', 'example.com'})
        self.assertEqual(read_cookies(self.target, 'alice')[0]['value'], 'x-session')
        self.assertIn('Empty folder', self.folders.list())

    def test_selected_export_and_collision_rename_leave_existing_profile_untouched(self):
        self.export([self.accounts[0]])
        existing = {'username': 'alice', 'group': 'Original', 'password': 'unchanged'}
        store = AccountStore([existing])
        marker = self.target.get_profile_dir('alice') / 'original.txt'
        marker.write_text('do not overwrite')
        result = import_package(self.target, store, self.folders, self.archive)
        self.assertEqual(result['total'], 1)
        self.assertEqual(store.data[0], existing)
        self.assertEqual(store.data[1]['username'], 'alice_2')
        self.assertEqual(marker.read_text(), 'do not overwrite')
        self.assertTrue(session_path(self.target, 'alice_2').is_file())

    def test_skip_existing_and_cancel_do_not_leave_partial_profiles(self):
        self.export()
        store = AccountStore([self.accounts[0]])
        result = import_package(self.target, store, self.folders, self.archive, duplicates='skip')
        self.assertEqual([r['status'] for r in result['report']], ['skipped', 'imported'])
        destination = Config(self.root / 'cancelled')
        cancelled = threading.Event()
        with self.assertRaisesRegex(ArchiveError, 'cancelled'):
            import_package(destination, AccountStore(), FolderStore(destination.base_dir / 'folders.json'),
                           self.archive, progress=lambda **kwargs: cancelled.set(), cancelled=cancelled.is_set)
        self.assertEqual(list(destination.browser_profiles_dir.iterdir()), [])
        self.assertFalse((destination.base_dir / 'kook').exists())

    def test_failed_metadata_save_rolls_back_files_and_folder_changes(self):
        self.export()
        store = AccountStore()
        self.folders.create('Original')
        with patch.object(store, 'save_accounts', side_effect=OSError('Disk full')):
            with self.assertRaises(ArchiveError):
                import_package(self.target, store, self.folders, self.archive)
        self.assertEqual(store.data, [])
        self.assertEqual(list(self.target.browser_profiles_dir.iterdir()), [])
        self.assertEqual(self.folders.list(), ['Original'])
        self.assertFalse(session_path(self.target, 'alice').exists())

    def test_unsafe_paths_and_unexpected_files_are_rejected_before_commit(self):
        self.export([self.accounts[0]])
        for unsafe in ['../escaped.txt', '/absolute.txt', 'C:/escaped.txt', 'profiles/000000/browser/file:stream',
                       'profiles\\000000\\browser\\file', 'profiles/000000/browser/CON.txt', 'extra.exe']:
            with self.subTest(path=unsafe):
                path = self.root / 'unsafe.xanty'
                with ZipFile(self.archive) as original, ZipFile(path, 'w', ZIP_DEFLATED) as output:
                    for item in original.infolist():
                        output.writestr(item, original.read(item))
                    output.writestr(unsafe, 'malicious')
                # ZipInfo normalizes Windows separators when constructing a ZIP;
                # emulate an incoming archive created on another OS instead.
                if '\\' in unsafe:
                    path.write_bytes(path.read_bytes().replace(unsafe.replace('\\', '/').encode(), unsafe.encode()))
                with self.assertRaises(ArchiveError):
                    import_package(self.target, AccountStore(), self.folders, path)
                self.assertEqual(list(self.target.browser_profiles_dir.iterdir()), [])
        self.assertFalse((self.root / 'escaped.txt').exists())

    def test_pending_session_is_restored_once_through_cdp_for_every_site(self):
        calls = []
        browser = SimpleNamespace(execute_cdp_cmd=lambda method, params: calls.append((method, params)))
        store_session(self.target, 'alice', self.cookies)
        apply_session(browser, self.target, 'alice')
        apply_session(browser, self.target, 'alice')
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], 'Storage.setCookies')
        self.assertEqual(len(calls[0][1]['cookies']), 2)
        self.assertFalse(json.loads(session_path(self.target, 'alice').read_text())['pending'])


if __name__ == '__main__':
    unittest.main()
