"""Local backups publish verified archives without endangering existing copies."""
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile

from xgenius.backups import BackupError, BackupManager
from xgenius.config import Config
from xgenius.profile_archive import ArchiveError, inspect_package
from xgenius.profile_leases import ProfileInUseError, ProfileLease


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = Config(self.root / 'workspace')
        self.destination = self.root / 'chosen-local-folder'
        self.manager = BackupManager(self.config)
        self.accounts = [{'username': 'alice', 'password': 'full-transfer-password'}, {'username': 'bob'}]
        profile = self.config.get_profile_dir('alice') / 'Default'
        profile.mkdir()
        (profile / 'Preferences').write_text('{"persistent":true}')

    def configure(self, **kwargs):
        return self.manager.configure({'directory': str(self.destination), 'enabled': True, **kwargs})

    def test_disabled_until_explicit_local_destination_and_config_survives_reload(self):
        self.assertEqual(self.manager.settings(), {'enabled': False, 'directory': '', 'interval_hours': 24, 'keep': 7})
        self.assertFalse(self.manager.due())
        with self.assertRaises(BackupError):
            self.manager.configure({'enabled': True})
        self.assertFalse(self.manager.settings()['enabled'])
        settings = self.configure(interval_hours=6, keep=3)
        self.assertFalse(self.destination.exists(), 'Choosing a folder must not create backup artifacts')
        self.assertEqual(BackupManager(self.config).settings(), settings)
        self.assertTrue(self.manager.due())

    def test_rejects_network_relative_recursive_and_invalid_settings_atomically(self):
        self.configure()
        previous = self.manager.settings()
        for data in ({'directory': r'\\server\share\backups'}, {'directory': '//server/share'},
                     {'directory': 'relative'}, {'directory': str(self.config.browser_profiles_dir)},
                     {'directory': str(self.config.get_profile_dir('alice') / 'backup')},
                     {'directory': str(self.config.base_dir / 'kook' / '@alice' / 'backup')},
                     {'enabled': 1}, {'interval_hours': 0}, {'interval_hours': True},
                     {'keep': 0}, {'keep': 1.5}, {'unknown': True}):
            with self.subTest(data=data):
                with self.assertRaises(BackupError):
                    self.manager.configure(data)
                self.assertEqual(self.manager.settings(), previous)
                self.assertEqual(BackupManager(self.config).settings(), previous)

    def test_publishes_full_verified_backup_and_due_uses_last_success(self):
        self.configure(interval_hours=2)
        before = datetime.now(timezone.utc)
        result = self.manager.run(self.accounts, folders=['Empty folder'])
        after = datetime.now(timezone.utc)
        archive = Path(result['path'])
        self.assertEqual(result['status'], 'completed')
        self.assertTrue(archive.is_relative_to(self.destination))
        self.assertNotEqual(archive.parent, self.destination)
        self.assertEqual(archive.suffix, '.xanty')
        self.assertEqual(inspect_package(archive)['integrity'], 'verified')
        with ZipFile(archive) as z:
            manifest = json.loads(z.read('manifest.json'))
            self.assertEqual(manifest['profiles'][0]['account']['password'], 'full-transfer-password')
            self.assertEqual(manifest['folders'], ['Empty folder'])
            self.assertIn('profiles/000000/browser/Default/Preferences', z.namelist())
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot['last_status'], 'completed')
        self.assertFalse(snapshot['running'])
        self.assertEqual(snapshot['last_result']['path'], str(archive))
        success = datetime.fromisoformat(snapshot['last_success_at'])
        self.assertTrue(before <= success <= after)
        self.assertFalse(self.manager.due(success + timedelta(hours=1, minutes=59)))
        self.assertTrue(self.manager.due(success + timedelta(hours=2)))
        self.assertEqual(BackupManager(self.config).snapshot()['last_success_at'], snapshot['last_success_at'])

    def test_failed_verification_and_cancellation_preserve_previous_backup_and_remove_partial_files(self):
        self.configure(keep=1)
        previous = Path(self.manager.run(self.accounts)['path'])
        content = previous.read_bytes()
        with patch('xgenius.backups.inspect_package', side_effect=ArchiveError('checksum mismatch')):
            with self.assertRaises(BackupError):
                self.manager.run(self.accounts)
        self.assertEqual(previous.read_bytes(), content)
        self.assertEqual(list(previous.parent.glob('*.xanty')), [previous])
        self.assertFalse(any(previous.parent.glob('*.partial')))
        self.assertEqual(self.manager.snapshot()['last_status'], 'failed')
        with self.assertRaisesRegex(BackupError, '(?i)cancel'):
            self.manager.run(self.accounts, cancelled=lambda: True)
        self.assertEqual(previous.read_bytes(), content)
        self.assertEqual(list(previous.parent.glob('*.xanty')), [previous])
        self.assertEqual(self.manager.snapshot()['last_status'], 'cancelled')

    def test_status_write_failure_preserves_previous_copies_before_retention(self):
        self.configure(keep=1)
        previous = Path(self.manager.run(self.accounts)['path'])
        content = previous.read_bytes()
        original = self.manager._write_document

        def fail_completed_status(document):
            if document['state'].get('last_status') == 'completed':
                raise BackupError('Could not save backup status')
            original(document)

        with patch.object(self.manager, '_write_document', side_effect=fail_completed_status):
            with self.assertRaises(BackupError):
                self.manager.run(self.accounts)
        self.assertTrue(previous.exists(), 'Failed runs must not prune previous backup copies')
        self.assertEqual(previous.read_bytes(), content)
        self.assertFalse(self.manager.snapshot()['running'])
        with ProfileLease.acquire(self.config, 'alice'):
            pass

    def test_all_profiles_are_leased_before_export_and_released_afterwards(self):
        self.configure()
        observed = []

        def progress(**kwargs):
            for account in self.accounts:
                with self.assertRaises(ProfileInUseError):
                    with ProfileLease.acquire(self.config, account['username']):
                        pass
            observed.append(kwargs['processed'])

        self.manager.run(self.accounts, progress=progress)
        self.assertEqual(observed, [1, 2, 2, 2])
        for account in self.accounts:
            with ProfileLease.acquire(self.config, account['username']):
                pass

    def test_busy_profile_postpones_without_publishing_or_retaining_other_leases(self):
        self.configure()
        with ProfileLease.acquire(self.config, 'bob'):
            with self.assertRaisesRegex(BackupError, '(?i)profile|close'):
                self.manager.run(self.accounts)
        self.assertFalse(any(self.destination.rglob('*.xanty')))
        self.assertEqual(self.manager.snapshot()['last_status'], 'postponed')
        self.assertTrue(self.manager.due())
        with ProfileLease.acquire(self.config, 'alice'):
            pass

    def test_running_job_blocks_reentry_and_an_independent_manager(self):
        self.configure()
        independent = BackupManager(self.config)
        observed = []

        def progress(**kwargs):
            if observed:
                return
            observed.append(True)
            self.assertTrue(self.manager.snapshot()['running'])
            self.assertFalse(self.manager.due())
            for manager in (self.manager, independent):
                with self.assertRaisesRegex(BackupError, '(?i)already|running'):
                    manager.run(self.accounts)

        result = self.manager.run(self.accounts, progress=progress)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(list(Path(result['path']).parent.glob('*.xanty'))), 1)

    def test_retention_only_removes_own_backups_in_workspace_directory(self):
        self.configure(keep=2)
        first = Path(self.manager.run(self.accounts)['path'])
        unrelated = first.parent / 'unrelated.xanty'
        unrelated.write_bytes(b'user-owned')
        outside = self.destination / first.name
        outside.write_bytes(b'outside dedicated workspace directory')
        second = Path(self.manager.run(self.accounts)['path'])
        third = Path(self.manager.run(self.accounts)['path'])
        self.assertFalse(first.exists())
        self.assertTrue(second.is_file())
        self.assertTrue(third.is_file())
        self.assertEqual(unrelated.read_bytes(), b'user-owned')
        self.assertEqual(outside.read_bytes(), b'outside dedicated workspace directory')
        other = BackupManager(Config(self.root / 'other-workspace'))
        other.configure({'directory': str(self.destination), 'enabled': True, 'keep': 1})
        other.run([{'username': 'different'}])
        self.assertTrue(second.is_file())
        self.assertTrue(third.is_file())

    def test_retention_keeps_newly_published_backup_when_system_clock_moves_back(self):
        self.configure(keep=1)
        previous = Path(self.manager.run(self.accounts)['path'])
        with patch('xgenius.backups._now', return_value=datetime(2000, 1, 1, tzinfo=timezone.utc)):
            current = Path(self.manager.run(self.accounts)['path'])
        self.assertTrue(current.is_file(), 'The successful result must point to a retained archive')
        self.assertFalse(previous.exists())

    def test_backup_rejects_symlink_destination_and_profile_tree(self):
        linked = self.root / 'linked'
        target = self.root / 'target'
        target.mkdir()
        try:
            self.link_directory(target, linked)
        except OSError as exc:
            self.skipTest('Creating symlinks is unavailable: ' + str(exc))
        with self.assertRaises(BackupError):
            self.manager.configure({'directory': str(linked / 'nested'), 'enabled': True})
        self.configure()
        self.link_directory(target, self.config.get_profile_dir('alice') / 'outside')
        with self.assertRaises(BackupError):
            self.manager.run(self.accounts)
        self.assertFalse(any(self.destination.rglob('*.xanty')))

    @staticmethod
    def link_directory(target, linked):
        if os.name == 'nt':
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(linked), str(target)], check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            os.symlink(target, linked, target_is_directory=True)

    def test_refuses_to_adopt_an_unmarked_dedicated_directory(self):
        self.configure(keep=1)
        previous = Path(self.manager.run(self.accounts)['path'])
        (previous.parent / '.xanty-owner.json').unlink()
        with self.assertRaises(BackupError):
            self.manager.run(self.accounts)
        self.assertTrue(previous.is_file())

    @unittest.skipUnless(os.name == 'nt', 'Windows mapped network drive validation')
    def test_rejects_mapped_network_drive(self):
        with patch('xgenius.backups.ctypes.windll.kernel32.GetDriveTypeW', return_value=4):
            with self.assertRaises(BackupError):
                self.configure()
        self.assertFalse(self.destination.exists())

    def test_export_failure_releases_leases_and_does_not_expose_exception_secrets(self):
        self.configure()
        def fail_progress(**kwargs):
            raise RuntimeError('SENTINEL_CALLBACK_SECRET')
        with self.assertRaises(BackupError) as failure:
            self.manager.run(self.accounts, progress=fail_progress)
        self.assertNotIn('SENTINEL_CALLBACK_SECRET', str(failure.exception))
        self.assertNotIn('SENTINEL_CALLBACK_SECRET', json.dumps(self.manager.snapshot()))
        self.assertFalse(self.manager.snapshot()['running'])
        for account in self.accounts:
            with ProfileLease.acquire(self.config, account['username']):
                pass
        self.assertFalse(any(self.destination.rglob('*.xanty')))
        self.assertFalse(any(self.destination.rglob('*.partial')))

    def test_failed_settings_write_keeps_previous_configuration(self):
        self.configure()
        previous = self.manager.settings()
        with patch('xgenius.backups.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(BackupError):
                self.manager.configure({'keep': 2})
        self.assertEqual(self.manager.settings(), previous)
        self.assertEqual(BackupManager(self.config).settings(), previous)


if __name__ == '__main__':
    unittest.main()
