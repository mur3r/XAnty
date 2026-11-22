"""Engine backup scheduling and footprint scans stay off the UI event loop."""
import asyncio
import copy
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xgenius.backups import BackupError, BackupManager
from xgenius.config import Config
from xgenius.folders import FolderStore
from xgenius.models import AccountState
from xgenius.profile_archive import inspect_package
from xgenius.profile_leases import ProfileInUseError, ProfileLease
from xgenius.web.actions import Actions
from xgenius.web.engine import Engine
from xgenius.workspace_operations import profile_size


class EngineWorkspaceTaskTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(self.root / 'workspace')
        self.records = [{'username': 'alice', 'important': True,
                         'reminder_at': '2026-11-23T10:00:00+00:00', 'reminder_note': 'Check campaign',
                         'password': 'private-password'}, {'username': 'bob'}]
        self.engine = Engine.__new__(Engine)
        e = self.engine
        e.loop = asyncio.get_running_loop()
        e.config = self.config
        e.account_manager = SimpleNamespace(accounts={}, load_accounts=lambda: copy.deepcopy(self.records),
                                             refresh_closed_browsers=lambda: None,
                                             shutdown_all_browsers=lambda: None)
        e.logger = SimpleNamespace(info=lambda *args: None, error=lambda *args: None, seq=0)
        e.folders = FolderStore(self.config.base_dir / 'folders.json')
        e.sysmon = SimpleNamespace(enabled=False)
        e._workspace_futures = set()
        e._backup_jobs = set()
        e._profile_sizes = {}
        e._shutdown_event = threading.Event()
        e._stopping = False
        e._backup_running = False
        e._tasks = []
        e.notify = lambda: None
        e.backups = BackupManager(self.config)
        e.actions = Actions(e)
        self.destination = self.root / 'backups'

    async def asyncTearDown(self):
        self.engine._shutdown_event.set()
        if self.engine._backup_jobs:
            await asyncio.gather(*list(self.engine._backup_jobs), return_exceptions=True)
        if self.engine._workspace_futures:
            await asyncio.gather(*list(self.engine._workspace_futures), return_exceptions=True)
        self.temp.cleanup()

    def configure(self, enabled=False):
        self.engine.backups.configure({'directory': str(self.destination), 'enabled': enabled})

    async def test_snapshot_uses_cached_sizes_and_includes_important_and_reminders(self):
        self.engine._profile_sizes['alice'] = {'bytes': 1073741824, 'gb': 1.0, 'files': 2}
        with patch('xgenius.web.engine.profile_size', side_effect=AssertionError('snapshot scanned the disk')):
            snapshot = self.engine.snapshot()
        alice, bob = snapshot['accounts']
        self.assertEqual(alice['profile_size']['bytes'], 1073741824)
        self.assertEqual(alice['profile_size']['gb'], 1.0)
        self.assertIsNone(bob['profile_size'])
        self.assertTrue(alice['important'])
        self.assertEqual(alice['reminder_at'], '2026-11-23T10:00:00+00:00')
        self.assertEqual(alice['reminder_note'], 'Check campaign')
        self.assertNotIn('password', alice)
        self.assertFalse(snapshot['backups']['enabled'])

    async def test_size_scan_runs_in_tracked_thread_and_does_not_block_snapshot(self):
        (self.config.get_profile_dir('alice') / 'payload').write_bytes(b'x' * 1000)
        cookies = self.config.base_dir / 'kook' / '@alice'
        cookies.mkdir(parents=True)
        (cookies / 'cookies.json').write_bytes(b'y' * 150)
        self.engine.account_manager.accounts['bob'] = AccountState('bob', browser=object())
        entered, release = threading.Event(), threading.Event()
        thread_ids = []

        def slow_measure(config, username):
            thread_ids.append(threading.get_ident())
            entered.set()
            release.wait(5)
            return profile_size(config, username)

        try:
            with patch('xgenius.web.engine.profile_size', side_effect=slow_measure):
                task = asyncio.create_task(self.engine._refresh_profile_sizes())
                self.assertTrue(await asyncio.to_thread(entered.wait, 2))
                self.assertTrue(self.engine._workspace_futures)
                self.assertIsNone(self.engine.snapshot()['accounts'][0]['profile_size'])
                release.set()
                await task
        finally:
            release.set()
        self.assertEqual(self.engine._profile_sizes['alice']['bytes'], 1150)
        self.assertNotIn('bob', self.engine._profile_sizes)
        self.assertTrue(all(value != threading.get_ident() for value in thread_ids))

    async def test_manual_backup_reserves_all_accounts_and_releases_after_verified_worker(self):
        self.configure()
        entered, release = threading.Event(), threading.Event()

        def progress(**kwargs):
            entered.set()
            release.wait(5)

        try:
            task = asyncio.create_task(self.engine.run_backup(progress=progress))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            self.assertEqual(self.engine.actions._transferring, {'alice', 'bob'})
            self.assertTrue(self.engine._workspace_futures)
            with self.assertRaises(BackupError):
                await self.engine.run_backup()
            release.set()
            result = await task
        finally:
            release.set()
        self.assertEqual(inspect_package(Path(result['path']))['integrity'], 'verified')
        self.assertFalse(self.engine.actions._transferring)
        self.assertFalse(self.engine._backup_running)
        self.assertEqual(self.records[0]['password'], 'private-password')

    async def test_manual_backup_rejects_open_profiles_and_all_pending_action_states(self):
        self.configure()
        self.engine.account_manager.accounts['bob'] = AccountState('bob', browser=object())
        with self.assertRaises(BackupError):
            await self.engine.run_backup()
        self.engine.account_manager.accounts.clear()
        for field in ('_busy', '_closing', '_transferring', '_profile_operations'):
            values = getattr(self.engine.actions, field)
            values.add('alice')
            try:
                with self.assertRaises(BackupError):
                    await self.engine.run_backup()
            finally:
                values.clear()
        pending = self.engine.loop.create_future()
        self.engine.actions._launch_tasks.add(pending)
        try:
            with self.assertRaises(BackupError):
                await self.engine.run_backup()
        finally:
            self.engine.actions._launch_tasks.clear()
            pending.cancel()
        self.assertFalse(self.destination.exists())

    async def test_request_cancellation_keeps_transfers_reserved_until_thread_exits(self):
        self.configure()
        entered, release = threading.Event(), threading.Event()

        def progress(**kwargs):
            entered.set()
            release.wait(5)

        try:
            task = asyncio.create_task(self.engine.run_backup(progress=progress))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            task.cancel()
            await asyncio.sleep(0.02)
            self.assertEqual(self.engine.actions._transferring, {'alice', 'bob'})
            self.assertTrue(self.engine._workspace_futures)
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await task
        finally:
            release.set()
        self.assertFalse(self.engine.actions._transferring)
        self.assertFalse(any(self.destination.rglob('*.xanty')))
        with ProfileLease.acquire(self.config, 'alice'):
            pass

    async def test_scheduler_waits_for_enabled_due_and_idle_profiles(self):
        await self.engine._workspace_maintenance_once()
        self.assertFalse(self.destination.exists())
        self.configure(enabled=True)
        self.engine.account_manager.accounts['bob'] = AccountState('bob', browser=object())
        await self.engine._workspace_maintenance_once()
        self.assertFalse(self.destination.exists())
        self.engine.account_manager.accounts.clear()
        self.engine.actions._busy.add('alice')
        await self.engine._workspace_maintenance_once()
        self.assertFalse(self.destination.exists())
        self.engine.actions._busy.clear()
        await self.engine._workspace_maintenance_once()
        self.assertEqual(len(list(self.destination.rglob('*.xanty'))), 1)
        await self.engine._workspace_maintenance_once()
        self.assertEqual(len(list(self.destination.rglob('*.xanty'))), 1)

    async def test_shutdown_signals_cancel_before_actions_and_drains_backup_before_workspace_release(self):
        self.configure()
        lease = ProfileLease.acquire_workspace(self.config)
        self.engine.account_manager.workspace_lease = lease
        entered, release = threading.Event(), threading.Event()
        original = self.engine.actions.shutdown

        async def shutdown_actions():
            self.assertTrue(self.engine._shutdown_event.is_set())
            await original()

        def progress(**kwargs):
            entered.set()
            release.wait(5)

        self.engine.actions.shutdown = shutdown_actions
        try:
            backup = asyncio.create_task(self.engine.run_backup(progress=progress))
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            shutdown = asyncio.create_task(self.engine.shutdown())
            await asyncio.sleep(0.02)
            self.assertFalse(shutdown.done())
            with self.assertRaises(ProfileInUseError):
                ProfileLease.acquire_workspace(self.config)
            release.set()
            await shutdown
            with self.assertRaises(BackupError):
                await backup
            self.assertFalse(self.engine.actions._transferring)
            fresh = ProfileLease.acquire_workspace(self.config)
            fresh.release()
            with self.assertRaises(BackupError):
                await self.engine.run_backup()
        finally:
            release.set()
            lease.release()


if __name__ == '__main__':
    unittest.main()
