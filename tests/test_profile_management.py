"""Persistence and lifecycle contracts for profile management, using real JSON files."""
import json
import asyncio
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xgenius.accounts.manager import AccountManager
from xgenius.config import Config
from xgenius.models import AccountState
from xgenius.folders import FolderStore
from xgenius.web.actions import Actions
from xgenius.web.engine import Engine
from xgenius.web.server import WebApp
from aiohttp.test_utils import TestClient, TestServer


class ProfileManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config(Path(self.temp.name))
        self.manager = AccountManager.__new__(AccountManager)
        self.manager.config = self.config
        self.manager.logger = SimpleNamespace(error=lambda *a: None)
        self.manager._data_lock = threading.RLock()
        self.manager.accounts = {}
        self.config.accounts_file.write_text(json.dumps({'accounts': [
            {'username': 'alice', 'profile_name': 'Alice', 'password': 'secret-old',
             'proxy': 'http://private:password@proxy.test:8080', 'group': 'Work'},
            {'username': 'bob'}]}), encoding='utf-8')

    def saved(self):
        return json.loads(self.config.accounts_file.read_text(encoding='utf-8'))

    def test_legacy_migration_preserves_data_and_stable_numbers(self):
        self.manager.initialize_profile_metadata()
        a, b = self.manager.load_accounts()
        self.assertEqual((a['profile_number'], b['profile_number']), (1, 2))
        self.assertEqual(a['profile_status'], 'new')
        self.assertEqual(a['password'], 'secret-old')
        self.manager.trash_profiles(['alice'], 0)
        self.manager.save_accounts(self.manager.load_accounts() + [{'username': 'charlie'}])
        self.manager.restore_profiles(['alice'])
        rows = {a['username']: a for a in self.manager.load_accounts()}
        self.assertEqual(rows['alice']['profile_id'], a['profile_id'])
        self.assertEqual(rows['alice']['profile_number'], 1)
        self.assertEqual(rows['charlie']['profile_number'], 3)

    def test_metadata_and_all_save_paths_record_actor_changes_without_secrets(self):
        self.manager.initialize_profile_metadata()
        self.manager.update_profile_metadata(['alice', 'bob'], {'profile_status': 'review', 'favorite': True, 'tags': 'urgent, team'})
        rows = self.manager.load_accounts()
        self.assertEqual(rows[0]['tags'], ['urgent', 'team'])
        rows[0].update(password='secret-new', proxy='http://different:new-secret@other.test:80', group='Other')
        with patch('xgenius.profile_metadata.getpass.getuser', return_value='test-operator'):
            self.manager.save_accounts(rows)
        event = self.manager.profile_history('alice')[0]
        self.assertEqual(event['actor'], 'test-operator')
        self.assertEqual(event['changes']['group'], {'before': 'Work', 'after': 'Other'})
        self.assertIn('password', event['changes'])
        history = json.dumps(self.manager.profile_history())
        for secret in ('secret-old', 'secret-new', 'new-secret', 'private:password', 'different:'):
            self.assertNotIn(secret, history)
        self.assertIn('other.test:80', history)

    def test_invalid_metadata_is_atomic_and_name_changes_do_not_move_browser(self):
        self.manager.initialize_profile_metadata()
        profile = self.config.get_profile_dir('alice')
        with self.assertRaises(ValueError):
            self.manager.update_profile_metadata(['alice'], {'profile_status': 'unknown'})
        with self.assertRaises(ValueError):
            self.manager.update_profile_metadata(['alice', 'missing'], {'favorite': True})
        self.manager.update_profile_metadata(['alice'], {'profile_name': 'Другое имя'})
        self.assertTrue(profile.is_dir())
        self.assertEqual(self.manager.load_accounts()[0]['username'], 'alice')
        self.assertFalse(self.manager.load_accounts()[0]['favorite'])

    def test_trash_survives_restart_restores_files_and_reserves_names(self):
        self.manager.initialize_profile_metadata()
        data = self.config.get_profile_dir('alice') / 'important.txt'
        data.write_text('session')
        self.manager.trash_profiles(['alice'], 0)
        self.assertEqual([a['username'] for a in self.manager.load_accounts()], ['bob'])
        self.assertIsNone(self.manager.trash_rows()[0]['delete_after'])
        with self.assertRaises(ValueError):
            self.manager.save_accounts(self.manager.load_accounts() + [{'username': 'alice'}])
        self.manager.initialize_profile_metadata()
        self.manager.restore_profiles(['alice'])
        self.assertEqual(data.read_text(), 'session')
        self.assertEqual(self.manager.trash_rows(), [])
        self.assertEqual(self.manager.profile_history('alice')[0]['action'], 'restored')

    def test_expiry_and_retention_clean_only_the_trashed_profile(self):
        self.manager.initialize_profile_metadata()
        first = self.config.get_profile_dir('alice')
        other = self.config.get_profile_dir('bob')
        cookie = self.config.base_dir / 'kook' / '@alice'
        cookie.mkdir(parents=True)
        (cookie / 'cookies.json').write_text('[]')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-01T12:00:00+00:00'):
            self.manager.trash_profiles(['alice'], 30)
        self.manager.set_trash_retention(['alice'], 1)
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-03T12:00:00+00:00'):
            self.assertEqual(self.manager.purge_trash(), 1)
        self.assertFalse(first.exists())
        self.assertFalse(cookie.exists())
        self.assertTrue(other.exists())
        self.assertEqual(self.manager.profile_history()[0]['action'], 'purged')

    def test_invalid_retention_and_escaping_paths_never_remove_other_files(self):
        self.manager.initialize_profile_metadata()
        for days in (-1, True, 3651, '1'):
            with self.assertRaises(ValueError):
                self.manager.trash_profiles(['alice'], days)
        rows = self.manager.load_accounts()
        rows[0]['username'] = '../../outside'
        self.manager.save_accounts(rows)
        self.manager.trash_profiles(['../../outside'], 0)
        with self.assertRaises(ValueError):
            self.manager.purge_trash(['../../outside'])
        self.assertEqual(len(self.manager.trash_rows()), 1)

    def test_runtime_checkpoints_close_once_and_restart_does_not_count_downtime(self):
        self.manager.initialize_profile_metadata()
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:00+00:00'):
            self.manager.start_profile_session('alice')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T11:30:00+00:00'):
            self.manager.checkpoint_sessions()
            self.manager.finish_profile_session('alice')
            self.manager.finish_profile_session('alice')
        a = self.manager.load_accounts()[0]
        self.assertEqual(a['runtime_seconds'], 5400)
        self.assertEqual(a['last_launch'], '2026-11-22T10:00:00+00:00')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T12:00:00+00:00'):
            self.manager.start_profile_session('alice')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T12:01:00+00:00'):
            self.manager.checkpoint_sessions()
        self.manager.initialize_profile_metadata()
        a = self.manager.load_accounts()[0]
        self.assertEqual(a['runtime_seconds'], 5460)
        self.assertIsNone(a['runtime_checkpoint'])
        self.assertEqual(self.manager.profile_history('alice'), [])

    def test_imported_copies_get_their_own_identity_and_number(self):
        self.manager.initialize_profile_metadata()
        rows = self.manager.load_accounts()
        imported = dict(rows[0], username='alice_copy')
        self.manager.save_accounts(rows + [imported])
        rows = self.manager.load_accounts()
        self.assertNotEqual(rows[0]['profile_id'], rows[2]['profile_id'])
        self.assertEqual(rows[2]['profile_number'], 3)

    def test_rename_username_keeps_history_identity(self):
        self.manager.initialize_profile_metadata()
        rows = self.manager.load_accounts()
        identity = rows[0]['profile_id']
        rows[0]['username'] = 'alice_renamed'
        self.manager.save_accounts(rows)
        self.assertEqual(self.manager.load_accounts()[0]['profile_id'], identity)
        self.assertEqual(self.manager.profile_history('alice_renamed')[0]['changes']['username']['before'], 'alice')

    def test_trash_reserves_case_insensitive_windows_names(self):
        self.manager.initialize_profile_metadata()
        marker = self.config.get_profile_dir('alice') / 'keep.txt'
        marker.write_text('session')
        self.manager.trash_profiles(['alice'], 0)
        for name in ('Alice', 'alice.', 'alice '):
            with self.assertRaises(ValueError):
                self.manager.save_accounts(self.manager.load_accounts() + [{'username': name}])
        self.assertEqual(marker.read_text(), 'session')

    def test_active_case_variant_blocks_purge_even_in_legacy_document(self):
        self.manager.initialize_profile_metadata()
        marker = self.config.get_profile_dir('alice') / 'keep.txt'
        marker.write_text('session')
        self.manager.trash_profiles(['alice'], 0)
        doc = self.saved()
        doc['accounts'].append({'username': 'Alice'})
        self.config.accounts_file.write_text(json.dumps(doc), encoding='utf-8')
        with self.assertRaises(ValueError):
            self.manager.purge_trash(['alice'])
        self.assertTrue(marker.exists())

    def test_edit_from_old_snapshot_keeps_latest_runtime_checkpoint(self):
        self.manager.initialize_profile_metadata()
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:00+00:00'):
            self.manager.start_profile_session('alice')
        stale = self.manager.load_accounts()
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:30+00:00'):
            self.manager.checkpoint_sessions()
        stale[0]['notes'] = 'edited'
        self.manager.save_accounts(stale)
        self.assertEqual(self.manager.load_accounts()[0]['runtime_seconds'], 30)
        self.manager.initialize_profile_metadata()
        self.assertEqual(self.manager.load_accounts()[0]['runtime_seconds'], 30)

    def test_reused_username_does_not_inherit_purged_profile_history(self):
        self.manager.initialize_profile_metadata()
        self.manager.update_profile_metadata(['alice'], {'notes': 'old identity'})
        self.manager.trash_profiles(['alice'], 0)
        self.manager.purge_trash(['alice'])
        self.manager.save_accounts(self.manager.load_accounts() + [{'username': 'alice'}])
        history = self.manager.profile_history('alice')
        self.assertEqual([e['action'] for e in history], ['created'])

    def test_package_collision_policy_respects_trash_without_browser_files(self):
        from xgenius.profile_archive import export_package, import_package
        self.manager.initialize_profile_metadata()
        archive = self.config.base_dir / 'profile.xanty'
        export_package(self.config, [self.manager.load_accounts()[0]], archive)
        self.manager.trash_profiles(['alice'], 0)
        folders = FolderStore(self.config.base_dir / 'folders.json')
        result = import_package(self.config, self.manager, folders, archive, duplicates='skip')
        self.assertEqual(result['report'][0]['status'], 'skipped')
        result = import_package(self.config, self.manager, folders, archive, duplicates='rename')
        self.assertEqual(result['report'][0]['status'], 'imported')
        self.assertEqual(self.manager.load_accounts()[-1]['username'], 'alice_2')

    def test_failed_close_write_retries_the_actual_end_not_later_checkpoint(self):
        from xgenius.profile_metadata import record_session_time
        self.manager.initialize_profile_metadata()
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:00+00:00'):
            self.manager.start_profile_session('alice')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:01:00+00:00'), \
                patch.object(self.manager, '_write_document', side_effect=OSError('disk full')):
            record_session_time(self.manager, 'alice')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T11:00:00+00:00'):
            self.manager.checkpoint_sessions()
        a = self.manager.load_accounts()[0]
        self.assertEqual(a['runtime_seconds'], 60)
        self.assertIsNone(a['runtime_checkpoint'])

    def test_failed_open_write_preserves_original_start_for_retry(self):
        from xgenius.profile_metadata import record_session_time
        self.manager.initialize_profile_metadata()
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:00+00:00'), \
                patch.object(self.manager, '_write_document', side_effect=OSError('disk full')):
            record_session_time(self.manager, 'alice', opened=True)
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:02:00+00:00'):
            self.manager.checkpoint_sessions()
        a = self.manager.load_accounts()[0]
        self.assertEqual(a['runtime_seconds'], 120)
        self.assertEqual(a['last_launch'], '2026-11-22T10:00:00+00:00')

    def test_pending_finish_follows_trash_and_username_rename(self):
        from xgenius.profile_metadata import record_session_time
        for operation in ('trash', 'rename'):
            with self.subTest(operation=operation):
                self.manager.initialize_profile_metadata()
                with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:00+00:00'):
                    self.manager.start_profile_session('alice')
                with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:01:00+00:00'), \
                        patch.object(self.manager, '_write_document', side_effect=OSError('disk full')):
                    record_session_time(self.manager, 'alice')
                if operation == 'trash':
                    self.manager.trash_profiles(['alice'], 0)
                else:
                    rows = self.manager.load_accounts()
                    rows[0]['username'] = 'alice_renamed'
                    self.manager.save_accounts(rows)
                with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T11:00:00+00:00'):
                    self.manager.checkpoint_sessions()
                if operation == 'trash':
                    self.manager.restore_profiles(['alice'])
                account = self.manager.load_accounts()[-1] if operation == 'trash' else self.manager.load_accounts()[0]
                self.assertEqual(account['runtime_seconds'], 60)
                self.assertIsNone(account['runtime_checkpoint'])
                # Reset fixture data for the other operation.
                self.config.accounts_file.write_text(json.dumps({'accounts': [{'username': 'alice'}, {'username': 'bob'}]}), encoding='utf-8')


class ProfileApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = ProfileManagementTests()
        self.fixture.setUp()
        self.am = self.fixture.manager
        self.am.initialize_profile_metadata()
        self.am.refresh_closed_browsers = lambda: None
        self.engine = Engine.__new__(Engine)
        self.engine.loop = asyncio.get_running_loop()
        self.engine.config = self.fixture.config
        self.engine.account_manager = self.am
        self.engine.logger = SimpleNamespace(info=lambda *a: None, error=lambda *a: None, warning=lambda *a: None, seq=0)
        self.engine.folders = FolderStore(self.engine.config.base_dir / 'folders.json')
        self.engine.sysmon = SimpleNamespace(enabled=False)
        self.engine.notify = lambda: None
        async def shutdown():
            pass
        self.engine.shutdown = shutdown
        self.app = WebApp(self.engine.loop)
        self.app.engine = self.engine
        self.app.actions = Actions(self.engine)
        self.client = TestClient(TestServer(self.app.build(), host='127.0.0.1'))
        await self.client.start_server()
        self.pref_patch = patch('xgenius.preferences.application_home', return_value=self.fixture.config.base_dir / 'prefs')
        self.pref_patch.start()

    async def asyncTearDown(self):
        await self.client.close()
        await self.app.shutdown()
        self.pref_patch.stop()
        self.fixture.doCleanups()

    async def test_metadata_snapshot_and_validation(self):
        response = await self.client.patch('/api/accounts/metadata', json={
            'usernames': ['alice'], 'metadata': {'profile_name': 'Quick rename', 'favorite': True, 'profile_status': 'active', 'tags': 'hello'}})
        self.assertEqual(response.status, 200, await response.text())
        data = await (await self.client.get('/api/state')).json()
        row = data['accounts'][0]
        self.assertEqual((row['favorite'], row['profile_status'], row['tags']), (True, 'active', ['hello']))
        self.assertEqual(row['profile_name'], 'Quick rename')
        response = await self.client.patch('/api/accounts/metadata', json={
            'usernames': ['alice'], 'metadata': {'profile_status': 'bad'}})
        self.assertEqual(response.status, 400)

    async def test_delete_restore_retention_and_history_endpoints(self):
        response = await self.client.post('/api/accounts/delete', json={'usernames': ['alice'], 'retention_days': 0})
        self.assertEqual(response.status, 200, await response.text())
        trash = await (await self.client.get('/api/trash')).json()
        self.assertEqual(trash['profiles'][0]['retention_days'], 0)
        self.assertNotIn('password', json.dumps(trash))
        response = await self.client.post('/api/trash/retention', json={'usernames': ['alice'], 'retention_days': 14})
        self.assertEqual(response.status, 200)
        response = await self.client.post('/api/trash/restore', json={'usernames': ['alice']})
        self.assertEqual(response.status, 200)
        history = await (await self.client.get('/api/history?username=alice')).json()
        self.assertEqual([e['action'] for e in history['events']], ['restored', 'retention_changed', 'trashed'])

    async def test_opening_and_open_profiles_cannot_be_trashed(self):
        for mode in ('busy', 'browser'):
            if mode == 'busy':
                self.app.actions._busy.add('alice')
            else:
                self.app.actions._busy.clear()
                self.am.accounts['alice'] = AccountState('alice', browser=object())
            response = await self.client.post('/api/accounts/delete', json={'usernames': ['alice']})
            self.assertEqual(response.status, 400)
        self.assertEqual(len(self.am.load_accounts()), 2)

    async def test_column_preferences_persist_and_reject_duplicates(self):
        response = await self.client.put('/api/preferences', json={'columns': ['name', 'runtime', 'number'], 'trash_retention_days': 7})
        self.assertEqual(response.status, 200, await response.text())
        data = await (await self.client.get('/api/preferences')).json()
        self.assertEqual(data['columns'], ['name', 'runtime', 'number'])
        self.assertEqual(data['trash_retention_days'], 7)
        response = await self.client.put('/api/preferences', json={'columns': ['name', 'name']})
        self.assertEqual(response.status, 400)

    async def test_manual_browser_close_persists_elapsed_time(self):
        from xgenius.accounts.health import HealthMixin
        browser = object()
        state = AccountState('alice', browser=browser)
        self.am.accounts['alice'] = state
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:00:00+00:00'):
            self.am.start_profile_session('alice')
        with patch('xgenius.profile_metadata.now_iso', return_value='2026-11-22T10:01:00+00:00'), patch('xgenius.accounts.health.hard_close_browser'):
            self.am.logger = self.engine.logger
            HealthMixin.mark_browser_closed(self.am, 'alice', state, browser)
            await asyncio.sleep(0.02)
        self.assertEqual(self.am.load_accounts()[0]['runtime_seconds'], 60)

    async def test_bulk_metadata_changes_are_audited_for_each_profile(self):
        response = await self.client.post('/api/accounts/bulk_edit', json={
            'usernames': ['alice', 'bob'], 'metadata': {'profile_status': 'unused', 'tags': 'one, two'}})
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual([a['profile_status'] for a in self.am.load_accounts()], ['unused', 'unused'])
        self.assertEqual(len(self.am.profile_history()), 2)

    async def test_disk_failure_does_not_prevent_browser_close(self):
        browser = SimpleNamespace(execute_cdp_cmd=lambda m,a:{'cookies':[],'targetInfos':[]},window_handles=[])
        state = AccountState('alice', browser=browser)
        self.am.accounts['alice'] = state
        self.am.start_profile_session('alice')
        with patch.object(self.am, '_write_document', side_effect=OSError('disk full')), \
                patch('xgenius.web.actions.save_cookies'), patch('xgenius.web.actions.hard_close_browser') as close:
            self.app.actions.close(['alice'])
            await asyncio.sleep(0.05)
            self.assertIsNone(state.browser)
            close.assert_called_once_with(browser)
