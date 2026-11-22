import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from xgenius.config import Config
from xgenius.workspace_operations import profile_size, obsolete_files, clean_obsolete_files
from tests import test_profile_management as fixtures


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=Config(Path(self.temp.name)/'data');self.updates=Path(self.temp.name)/'updates';self.updates.mkdir()

    def test_size_includes_snapshots_and_excludes_shared_core(self):
        root=self.config.get_profile_dir('alice');(root/'payload').write_bytes(b'x'*1000)
        cookies=self.config.base_dir/'kook'/'@alice';cookies.mkdir(parents=True);(cookies/'cookies.json').write_bytes(b'y'*250)
        core=self.config.base_dir/'Bro';core.mkdir();(core/'chrome.exe').write_bytes(b'z'*9000)
        result=profile_size(self.config,'alice')
        self.assertEqual(result['bytes'],1250);self.assertEqual(result['files'],2)

    def test_cleanup_only_aged_recognized_artifacts_and_keeps_active_and_rollback(self):
        old=time.time()-10*86400
        paths=[self.updates/'XAnty-2026.11.20.exe',self.updates/'XAnty-2026.11.21.exe.part',self.updates/'XAnty.exe.previous',self.updates/'personal.txt']
        for path in paths:path.write_text('keep');os.utime(path,(old,old))
        active=self.updates/'XAnty-2026.11.22.exe.part';active.write_text('active');os.utime(active,(old,old))
        preview=obsolete_files(self.config,self.updates,protected=[active])
        self.assertEqual({Path(p['path']).name for p in preview['files']},{'XAnty-2026.11.20.exe','XAnty-2026.11.21.exe.part'})
        result=clean_obsolete_files(self.config,self.updates,protected=[active])
        self.assertEqual(result['count'],2)
        self.assertTrue(active.exists());self.assertTrue(paths[2].exists());self.assertTrue(paths[3].exists())


class MetadataOperationTests(unittest.TestCase):
    setUp=fixtures.ProfileManagementTests.setUp
    def test_window_sets_follow_identity_after_rename_and_reject_missing_members(self):
        self.manager.initialize_profile_metadata()
        saved=self.manager.save_window_set('Work 1',['alice','bob'])
        rows=self.manager.load_accounts();rows[0]['username']='alice_renamed';self.manager.save_accounts(rows)
        self.assertEqual(self.manager.resolve_window_set(saved['id']),['alice_renamed','bob'])
        self.manager.trash_profiles(['bob'],0)
        with self.assertRaises(ValueError):self.manager.resolve_window_set(saved['id'])

    def test_reminder_normalizes_timezone_and_can_be_completed(self):
        self.manager.initialize_profile_metadata()
        self.manager.update_profile_metadata(['alice'],{'reminder_at':'2026-11-23T12:00:00+02:00','reminder_note':'Check campaign','important':True})
        a=self.manager.load_accounts()[0]
        self.assertEqual(a['reminder_at'],'2026-11-23T10:00:00+00:00')
        self.assertTrue(a['important'])
        self.manager.update_profile_metadata(['alice'],{'reminder_at':None,'reminder_note':''})
        self.assertIsNone(self.manager.load_accounts()[0]['reminder_at'])

    def test_reminder_rejects_naive_or_invalid_dates_without_saving(self):
        self.manager.initialize_profile_metadata()
        for stamp in ('tomorrow','2026-11-23T10:00:00'):
            with self.assertRaises(ValueError):self.manager.update_profile_metadata(['alice'],{'reminder_at':stamp})
