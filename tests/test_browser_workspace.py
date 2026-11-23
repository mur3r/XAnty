import json
import tempfile
import asyncio
import subprocess
import sys
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
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

    def test_native_restored_tabs_keep_their_pages_and_selection(self):
        workspace.write_tabs(self.config, 'alice', ['https://saved.example/'])
        browser = WorkspaceBrowser('https://one.example/', 'https://selected.example/')
        browser.current_window_handle = '2'

        workspace.prepare_workspace(browser)
        self.assertEqual(workspace.restore_tabs(browser, self.config, 'alice'), 2)

        self.assertEqual(browser.pages, {'1': 'https://one.example/', '2': 'https://selected.example/'})
        self.assertEqual(browser.current_window_handle, '2')

    def test_restore_disabled_leaves_startup_page_untouched(self):
        workspace.write_tabs(self.config, 'alice', ['https://saved.example/'])
        browser = WorkspaceBrowser('about:blank')

        workspace.prepare_workspace(browser)
        self.assertEqual(workspace.restore_tabs(browser, self.config, 'alice', enabled=False), 0)

        self.assertEqual(browser.pages, {'1': 'about:blank'})
        self.assertEqual(browser.current_window_handle, '1')

    def test_saved_tabs_restore_once_with_saved_selection(self):
        workspace.write_tabs(self.config, 'alice', ['https://one.example/', 'https://selected.example/'], active=1)
        browser = WorkspaceBrowser('about:blank')

        workspace.prepare_workspace(browser)
        self.assertEqual(workspace.restore_tabs(browser, self.config, 'alice'), 2)
        self.assertEqual(workspace.restore_tabs(browser, self.config, 'alice'), 2)

        self.assertEqual(list(browser.pages.values()), ['https://one.example/', 'https://selected.example/'])
        self.assertEqual(browser.pages[browser.current_window_handle], 'https://selected.example/')

    def test_x_login_reuses_an_existing_x_tab(self):
        browser = WorkspaceBrowser('https://other.example/', 'https://x.com/home')

        workspace.select_x_login_tab(browser)

        self.assertEqual(browser.pages, {'1': 'https://other.example/', '2': 'https://x.com/home'})
        self.assertEqual(browser.current_window_handle, '2')

    def test_x_login_uses_a_new_tab_when_all_open_pages_are_unrelated(self):
        browser = WorkspaceBrowser('https://other.example/')

        workspace.select_x_login_tab(browser)

        self.assertEqual(browser.pages, {'1': 'https://other.example/', '2': 'about:blank'})
        self.assertEqual(browser.current_window_handle, '2')

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


class ManualLoginWorkspaceTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_login_leaves_selected_native_page_in_place(self):
        from xgenius.accounts.auth import AuthMixin
        from xgenius.models import AccountCredentials

        with tempfile.TemporaryDirectory() as directory:
            auth = AuthMixin()
            auth.config = Config(Path(directory))
            auth.accounts = {}
            auth.logger = SimpleNamespace(info=lambda *args: None)
            browser = WorkspaceBrowser('https://native.example/')
            browser._xg_browser_version = '128.0.0.0'
            browser._xg_user_agent = 'Chrome/128.0.0.0'
            browser._xg_proxy_ip = '203.0.113.24'
            auth.browser_manager = SimpleNamespace(create_browser=AsyncMock(return_value=browser))

            await auth.login_account(AccountCredentials('alice', '', auto_login=False, restore_tabs=True))

            self.assertEqual(browser.pages, {'1': 'https://native.example/'})
            self.assertEqual(auth.accounts['alice'].proxy_status, 'ok')


class WorkspaceBrowser:
    def __init__(self, *urls):
        self.pages = {str(index): url for index, url in enumerate(urls, 1)}
        self.next_id = len(urls) + 1
        self.current_window_handle = '1'
        self.switch_to = SimpleNamespace(window=self.select, new_window=lambda kind: self.create('about:blank'))

    @property
    def window_handles(self):
        return list(self.pages)

    def select(self, target):
        self.current_window_handle = target

    def create(self, url, background=False):
        target = str(self.next_id)
        self.next_id += 1
        self.pages[target] = url
        if not background:
            self.select(target)
        return target

    def close(self):
        self.pages.pop(self.current_window_handle)

    def get(self, url):
        self.pages[self.current_window_handle] = url

    def execute_cdp_cmd(self, command, params):
        if command == 'Target.getTargets':
            return {'targetInfos': [
                {'type': 'page', 'targetId': target, 'url': url} for target, url in self.pages.items()
            ]}
        if command == 'Target.createTarget':
            return {'targetId': self.create(params['url'], params.get('background', False))}
        if command == 'Target.closeTarget':
            self.pages.pop(params['targetId'])
            return {'success': True}
        if command == 'Target.activateTarget':
            self.select(params['targetId'])
            return {}
        raise AssertionError(command)
