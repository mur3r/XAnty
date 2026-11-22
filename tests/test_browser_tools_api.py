import json
import unittest
import asyncio
import threading
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from tests.test_profile_management import ProfileApiTests
from xgenius.profile_leases import ProfileLease
from xgenius.portable_session import session_path
from xgenius.models import AccountState


class BrowserToolsApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ProfileApiTests.asyncSetUp
    asyncTearDown = ProfileApiTests.asyncTearDown

    async def test_profile_writes_are_rejected_after_shutdown_starts(self):
        self.app.actions._stopping=True
        response=await self.client.patch('/api/accounts/metadata',json={'usernames':['alice'],'metadata':{'notes':'late write'}})
        self.assertEqual(response.status,400)
        self.assertNotIn('notes',self.am.load_accounts()[0])

    async def test_all_site_cookies_import_view_and_manual_launch_policy(self):
        response=await self.client.post('/api/accounts/alice/tools/cookies_import',json={'cookies':json.dumps([
            {'name':'prepared','value':'session-value','domain':'.example.org','httpOnly':True}])})
        self.assertEqual(response.status,200,await response.text())
        response=await self.client.get('/api/accounts/alice/tools/cookies')
        self.assertEqual(response.status,200)
        data=await response.json()
        self.assertEqual(data['cookies'][0]['domain'],'.example.org')
        self.assertTrue(json.loads(session_path(self.engine.config,'alice').read_text())['pending'])

    async def test_cache_tool_rejects_get_and_external_lock_and_preserves_cookies(self):
        root=self.engine.config.get_profile_dir('alice')
        for name in ('Default/Cache/data','Default/Network/Cookies'):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('important')
        response=await self.client.get('/api/accounts/alice/tools/cache')
        self.assertEqual(response.status,405)
        lease=ProfileLease.acquire(self.engine.config,'alice',check_processes=False)
        try:
            response=await self.client.post('/api/accounts/alice/tools/cache',json={})
            self.assertEqual(response.status,400)
        finally:
            lease.release()
        response=await self.client.post('/api/accounts/alice/tools/cache',json={})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual((root/'Default/Network/Cookies').read_text(),'important')

    async def test_extension_set_can_be_selected_at_profile_creation(self):
        source=self.engine.config.base_dir/'source-extension';source.mkdir()
        (source/'manifest.json').write_text(json.dumps({'manifest_version':3,'name':'Demo','version':'1.0'}))
        response=await self.client.post('/api/extension-sets',json={'name':'Work set','directories':[str(source)]})
        self.assertEqual(response.status,200,await response.text())
        preset=(await response.json())['set']
        response=await self.client.post('/api/accounts',json={'username':'with_extensions','extension_set':preset['id'],
            'restore_tabs':False,'frame_color':'#33aa88'})
        self.assertEqual(response.status,200,await response.text())
        stored=next(a for a in self.am.load_accounts() if a['username']=='with_extensions')
        self.assertEqual(stored['extension_set'],preset['id'])
        self.assertFalse(stored['restore_tabs'])
        self.assertTrue(list((self.engine.config.get_profile_dir('with_extensions')/'XAntyExtensions').rglob('manifest.json')))

    async def test_preferences_validate_autosave_and_frame_switch(self):
        for payload in ({'window_frames':True,'session_autosave':True,'autosave_seconds':120},):
            response=await self.client.put('/api/preferences',json=payload)
            self.assertEqual(response.status,200)
        for payload in ({'window_frames':'yes'},{'autosave_seconds':1},{'autosave_seconds':True}):
            response=await self.client.put('/api/preferences',json=payload)
            self.assertEqual(response.status,400)

    async def test_save_session_reads_live_all_origin_cookies_and_writes_snapshot(self):
        def cdp(method,args):
            if method=='Storage.getCookies':
                return {'cookies':[{'name':'live','value':'v','domain':'other.example'}]}
            return {'targetInfos':[{'type':'page','targetId':'p','url':'https://other.example/'}]}
        browser=SimpleNamespace(execute_cdp_cmd=cdp,window_handles=['p'])
        self.am.accounts['alice']=AccountState('alice',browser=browser)
        response=await self.client.post('/api/accounts/alice/tools/save',json={})
        self.assertEqual(response.status,200,await response.text())
        self.assertEqual((await response.json())['cookies'],1)
        self.assertFalse(json.loads(session_path(self.engine.config,'alice').read_text())['pending'])
        self.assertEqual(json.loads((session_path(self.engine.config,'alice').parent/'tabs.json').read_text())['tabs'],['https://other.example/'])

    async def test_username_rename_respects_an_external_profile_lease(self):
        lease=ProfileLease.acquire(self.engine.config,'alice',False)
        try:
            response=await self.client.put('/api/accounts/alice',json={'username':'alice_renamed'})
            self.assertEqual(response.status,400)
            self.assertEqual(self.am.load_accounts()[0]['username'],'alice')
        finally:
            lease.release()

    async def test_shutdown_waits_for_pending_session_save_and_close(self):
        entered=threading.Event();release=threading.Event();closed=threading.Event()
        browser=SimpleNamespace()
        self.am.accounts['alice']=AccountState('alice',browser=browser)
        def save(*args):
            entered.set();release.wait(5)
        with patch('xgenius.web.actions.save_workspace',side_effect=save), \
                patch('xgenius.web.actions.save_cookies'),patch('xgenius.web.actions.hard_close_browser',side_effect=lambda b:closed.set()):
            self.app.actions.close(['alice'])
            await asyncio.to_thread(entered.wait,2)
            shutdown=asyncio.create_task(self.app.actions.shutdown())
            await asyncio.sleep(0.02)
            self.assertFalse(shutdown.done())
            release.set();await shutdown
            self.assertTrue(closed.is_set())
