import asyncio
import json
import threading
import unittest
from pathlib import Path
from zipfile import ZipFile
from unittest.mock import AsyncMock, patch
from xgenius.models import AccountState
from xgenius.error_messages import launch_diagnostic
from xgenius.backups import BackupManager
from xgenius.profile_archive import inspect_package
from tests import test_profile_management as fixtures


class WorkspaceApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.ProfileApiTests.asyncSetUp
    asyncTearDown=fixtures.ProfileApiTests.asyncTearDown

    async def test_important_and_favorite_deletion_require_typed_confirmation(self):
        for key in ('important','favorite'):
            self.am.update_profile_metadata(['alice'],{key:True})
            response=await self.client.post('/api/accounts/delete',json={'usernames':['alice']})
            self.assertEqual(response.status,400,await response.text())
            self.assertEqual(len(self.am.load_accounts()),2)
            self.am.update_profile_metadata(['alice'],{key:False})
        self.am.update_profile_metadata(['alice'],{'important':True})
        response=await self.client.post('/api/accounts/delete',json={'usernames':['alice'],'confirmation':'DELETE'})
        self.assertEqual(response.status,200,await response.text())
        response=await self.client.post('/api/trash/purge',json={'usernames':['alice']})
        self.assertEqual(response.status,400,await response.text())
        response=await self.client.post('/api/trash/purge',json={'usernames':['alice'],'confirmation':'DELETE'})
        self.assertEqual(response.status,200,await response.text())

    async def test_editor_preserves_reminder_and_important_fields(self):
        response=await self.client.put('/api/accounts/alice',json={'username':'alice','important':True,
            'reminder_at':'2026-11-24T12:00:00+02:00','reminder_note':'Do work'})
        self.assertEqual(response.status,200,await response.text())
        a=self.am.load_accounts()[0]
        self.assertTrue(a['important']);self.assertEqual(a['reminder_at'],'2026-11-24T10:00:00+00:00')

    async def test_named_set_resolves_ids_and_exact_open_requires_close_confirmation(self):
        response=await self.client.post('/api/window-sets',json={'name':'Work','usernames':['alice']})
        self.assertEqual(response.status,200,await response.text());record=(await response.json())['set']
        self.am.accounts['bob']=AccountState('bob',browser=object())
        response=await self.client.post('/api/window-sets/'+record['id']+'/open',json={'exact':True})
        self.assertEqual(response.status,400,await response.text())
        self.assertIsNotNone(self.am.accounts['bob'].browser)
        events=[]
        def close(st):
            st.browser=None;events.append('closed');return asyncio.create_task(asyncio.sleep(0))
        def start(names):events.append(('start',names));return len(names)
        with patch.object(self.app.actions,'_close_state',side_effect=close),patch.object(self.app.actions,'start_login',side_effect=start):
            response=await self.client.post('/api/window-sets/'+record['id']+'/open',json={'exact':True,'confirm_close':True})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual(events,['closed',('start',['alice'])])

    async def test_storage_cache_retains_authorization_and_clears_only_selected_cache(self):
        root=self.engine.config.get_profile_dir('alice')/'Default';(root/'Cache').mkdir(parents=True)
        (root/'Cache'/'data').write_bytes(b'cached');(root/'Cookies').write_bytes(b'auth')
        response=await self.client.post('/api/workspace/storage',json={'operation':'cache','usernames':['alice']})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual((root/'Cookies').read_bytes(),b'auth');self.assertFalse((root/'Cache'/'data').exists())

    async def test_version_switch_refuses_running_profile(self):
        self.am.accounts['alice']=AccountState('alice',browser=object())
        response=await self.client.post('/api/workspace/chromium/select',json={'version':'bundled'})
        self.assertEqual(response.status,400,await response.text())

    async def test_chromium_install_job_receives_byte_progress(self):
        def install(version,progress,cancelled):
            progress({'phase':'download','downloaded':30,'total':100})
            return {'version':'128.0.1.2'}
        with patch('xgenius.web.workspace_api.ChromiumVersionManager.install',side_effect=install):
            response=await self.client.post('/api/workspace/chromium/install',json={'version':'Stable'})
            self.assertEqual(response.status,202,await response.text())
            job=self.app.jobs.get((await response.json())['id']);await job.task
        self.assertEqual((job.processed,job.total),(30,100));self.assertEqual(job.status,'completed')

    async def test_active_backup_blocks_profile_mutations(self):
        self.engine._backup_running=True
        response=await self.client.patch('/api/accounts/metadata',json={'usernames':['alice'],'metadata':{'profile_name':'changed'}})
        self.assertEqual(response.status,400,await response.text())
        self.assertEqual(self.am.load_accounts()[0]['profile_name'],'Alice')

    async def test_backup_routes_publish_a_verified_local_package(self):
        e=self.engine
        e._workspace_futures=set();e._backup_jobs=set();e._shutdown_event=threading.Event();e._backup_running=False
        e.backups=BackupManager(e.config)
        destination=e.config.base_dir/'local-backups'
        response=await self.client.put('/api/workspace/backups',json={'directory':str(destination),'enabled':False,'interval_hours':3,'keep':2})
        self.assertEqual(response.status,200,await response.text())
        response=await self.client.post('/api/workspace/backups/run',json={})
        self.assertEqual(response.status,202,await response.text())
        job=self.app.jobs.get((await response.json())['id']);await job.task
        self.assertEqual(job.status,'completed',job.error)
        result=e.backups.snapshot()
        self.assertEqual(result['last_status'],'completed')
        archive=Path(result['last_result']['path'])
        self.assertTrue(archive.is_relative_to(destination))
        self.assertEqual(inspect_package(archive)['integrity'],'verified')

    async def test_safe_export_route_does_not_include_secrets_or_opaque_storage(self):
        root=self.engine.config.get_profile_dir('alice')/'Default';root.mkdir()
        (root/'Login Data').write_bytes(b'opaque-secret')
        response=await self.client.post('/api/profiles/export',json={'usernames':['alice'],'privacy':{'include_tokens':False}})
        self.assertEqual(response.status,202,await response.text())
        job=self.app.jobs.get((await response.json())['id']);await job.task
        self.assertEqual(job.status,'completed',job.error)
        with ZipFile(job.file_path) as package:
            combined=b''.join(package.read(name) for name in package.namelist())
        for secret in (b'opaque-secret',b'secret-old',b'private:password'):self.assertNotIn(secret,combined)


class DiagnosticTests(unittest.TestCase):
    def test_classifies_redacted_proxy_version_and_timeout(self):
        a={'password':'secret-password','auth_token':'secret-token','proxy':'http://user:private-pass@proxy.test:80'}
        for message,category in [('Proxy connection failed secret-password private-pass','proxy'),
                                 ('This version of ChromeDriver only supports Chrome version 128','version'),
                                 ('Timeout waiting for session secret-token','timeout')]:
            result=launch_diagnostic(message,a)
            self.assertEqual(result['category'],category)
            for secret in ('secret-password','private-pass','secret-token'):self.assertNotIn(secret,result['detail'])
