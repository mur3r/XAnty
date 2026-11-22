import json
import tempfile
import asyncio
import subprocess
import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from xgenius.config import Config
from xgenius import browser_workspace as workspace
from xgenius.profile_leases import ProfileLease, ProfileInUseError


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Config(Path(self.temp.name))

    def test_tabs_capture_ignores_internal_and_diagnostic_targets(self):
        browser = SimpleNamespace(execute_cdp_cmd=lambda method,args: {'targetInfos': [
            {'type':'page','targetId':'one','url':'https://example.com/a'},
            {'type':'page','targetId':'two','url':'https://example.org/b#part'},
            {'type':'page','targetId':'internal','url':'chrome://settings'},
            {'type':'page','targetId':'diagnostic','url':'https://dnsleak.dev/'},
            {'type':'service_worker','url':'https://worker.example/'}]}, _xg_ignored_targets={'diagnostic'})
        self.assertEqual(workspace.capture_tabs(browser,self.config,'alice'),2)
        self.assertEqual(workspace.read_tabs(self.config,'alice')['tabs'], ['https://example.com/a','https://example.org/b#part'])

    def test_restore_pages_does_not_replace_native_restored_tabs(self):
        workspace.write_tabs(self.config,'alice', ['https://saved.example/'])
        created=[]
        browser=SimpleNamespace(_xg_native_tabs=['https://native.example/'], execute_cdp_cmd=lambda m,a: created.append(a))
        self.assertEqual(workspace.restore_tabs(browser,self.config,'alice'),1)
        self.assertEqual(created,[])
        browser._xg_native_tabs=[]
        self.assertEqual(workspace.restore_tabs(browser,self.config,'alice'),1)
        self.assertEqual(created,[{'url':'https://saved.example/'}])

    def test_first_launch_bootstrap_becomes_a_normal_user_tab(self):
        browser=SimpleNamespace(_xg_native_tabs=[],_xg_bootstrap_handle='one',_xg_ignored_targets={'one'})
        self.assertEqual(workspace.restore_tabs(browser,self.config,'alice'),0)
        self.assertEqual(browser._xg_ignored_targets,set())

    def test_cookie_parser_accepts_all_sites_and_netscape_and_rejects_invalid_input(self):
        data='# Netscape HTTP Cookie File\n.example.org\tTRUE\t/\tTRUE\t0\tsession\tprepared-value\n'
        parsed=workspace.parse_cookie_input(data)
        self.assertEqual(parsed[0]['domain'],'.example.org')
        self.assertEqual(parsed[0]['value'],'prepared-value')
        self.assertEqual(workspace.parse_cookie_input(json.dumps({'example.org':parsed})),parsed)
        with self.assertRaises(ValueError):
            workspace.parse_cookie_input('[{"name":"n","value":"v","domain":"evil/../path"}]')

    def test_clear_cache_preserves_authorization_and_other_profile_data(self):
        root=self.config.get_profile_dir('alice')
        for name in ('Default/Cache/data','Default/Code Cache/js/data','GPUCache/data','Default/Network/Cookies',
                     'Default/Local Storage/keep','Default/Sessions/keep','Default/Extensions/abc/keep'):
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('keep')
        result=workspace.clear_cache(self.config,'alice')
        self.assertEqual(result['files'],3)
        self.assertFalse((root/'Default/Cache').exists())
        for name in ('Default/Network/Cookies','Default/Local Storage/keep','Default/Sessions/keep','Default/Extensions/abc/keep'):
            self.assertEqual((root/name).read_text(),'keep')

    def test_cache_cleanup_refuses_a_locked_profile(self):
        lease=ProfileLease.acquire(self.config,'alice',check_processes=False)
        self.addCleanup(lease.release)
        with self.assertRaises(ProfileInUseError):
            workspace.clear_cache(self.config,'alice')

    def test_lease_blocks_second_instance_and_releases_after_failure(self):
        lease=ProfileLease.acquire(self.config,'alice',check_processes=False)
        with self.assertRaises(ProfileInUseError):
            ProfileLease.acquire(self.config,'Alice',check_processes=False)
        lease.release()
        next_lease=ProfileLease.acquire(self.config,'alice',check_processes=False)
        next_lease.release()

    def test_paths_cannot_escape_profile_root(self):
        with self.assertRaises(ValueError):
            workspace.profile_directory(self.config,'../../outside')

    def test_lease_is_shared_with_a_second_python_process(self):
        profile=self.config.get_profile_dir('alice')
        lease=ProfileLease.acquire_path(profile,check_processes=False)
        script="from xgenius.profile_leases import ProfileLease,ProfileInUseError; import sys\ntry:\n p=ProfileLease.acquire_path(sys.argv[1],False); print('acquired'); p.release()\nexcept ProfileInUseError:\n print('blocked')"
        try:
            result=subprocess.run([sys.executable,'-c',script,str(profile)],capture_output=True,text=True,
                                  creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,check=True)
            self.assertEqual(result.stdout.strip(),'blocked')
        finally:
            lease.release()

    def test_second_writable_manager_cannot_reset_another_sessions_metadata(self):
        from xgenius.accounts.manager import AccountManager
        with patch('threading.Thread.start'):
            first=AccountManager(self.config,SimpleNamespace(error=lambda *a:None))
            try:
                first.save_accounts([{'username':'alice'}])
                first.start_profile_session('alice')
                before=first.load_accounts()[0]['runtime_checkpoint']
                with self.assertRaises(ProfileInUseError):
                    AccountManager(self.config,SimpleNamespace(error=lambda *a:None))
                self.assertEqual(first.load_accounts()[0]['runtime_checkpoint'],before)
            finally:
                first.stop_worker=True
                getattr(first,'workspace_lease',SimpleNamespace(release=lambda:None)).release()


class LaunchCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_launch_keeps_lease_until_late_browser_is_closed(self):
        from xgenius.browser import BrowserManager
        from xgenius.models import AccountCredentials, BrowserConfig
        with tempfile.TemporaryDirectory() as directory:
            config=Config(Path(directory));manager=BrowserManager(config,BrowserConfig())
            gate=asyncio.Event();entered=asyncio.Event()
            async def late(credentials):
                entered.set();await gate.wait();return SimpleNamespace()
            manager._create_browser=late
            with patch('xgenius.browser.hard_close_browser'):
                task=asyncio.create_task(manager.create_browser(AccountCredentials('alice','')))
                await entered.wait();task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                with self.assertRaises(ProfileInUseError):
                    ProfileLease.acquire(config,'alice',False)
                gate.set();await asyncio.sleep(0.05)
                lease=ProfileLease.acquire(config,'alice',False);lease.release()
