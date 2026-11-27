"""Generated and manually pinned UAs must match the installed browser, without suppressing CH."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

from tests import test_profile_management as fixtures
from xgenius.models import AccountState
from xgenius.user_agent import (apply_native_stealth, browser_identity, generate_user_agent,
                                profile_identity, user_agent_settings, validate_user_agent)
from xgenius.profile_settings import ProfileSettingsError

VERSION = '151.0.8090.1'
UA = generate_user_agent(VERSION)


class UserAgentTests(unittest.TestCase):
    def test_generation_uses_only_real_chromium_major_and_standard_windows_format(self):
        self.assertEqual(UA, 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36')
        for value in ('invented', '', None, '151.0', '151.0.0.0\n', '106.0.0.0'):
            with self.subTest(value=value), self.assertRaises(ProfileSettingsError):
                generate_user_agent(value)
        self.assertFalse(browser_identity(SimpleNamespace(chrome_path='missing-chromium.exe'))['available'])

    def test_mismatched_versions_os_and_arbitrary_patches_are_rejected(self):
        self.assertEqual(validate_user_agent(UA, VERSION), UA)
        for invalid in (UA.replace('151.', '150.'), UA.replace('Windows NT 10.0', 'Linux'),
                        UA.replace('151.0.0.0', VERSION), UA + '\r\nInjected: header'):
            with self.subTest(invalid=invalid), self.assertRaises(ProfileSettingsError):
                validate_user_agent(invalid, VERSION)
        self.assertEqual(user_agent_settings({'user_agent':'old-imported-ua'}, None)['user_agent_mode'], 'auto')
        preview = {'available':True,'user_agent':UA,'browser_version':VERSION,'source':'generated','error':''}
        mismatch = profile_identity({'user_agent_mode':'manual','user_agent':UA.replace('151.', '150.')}, preview)
        self.assertFalse(mismatch['available'])
        self.assertEqual(mismatch['user_agent'], '')

    def test_stealth_keeps_native_ua_and_client_hints_and_restores_the_driver_method(self):
        calls = []
        browser = SimpleNamespace(execute_cdp_cmd=lambda cmd,args:calls.append((cmd,args)))
        previous = browser.execute_cdp_cmd
        def compatibility(driver, **options):
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {'userAgent':'mismatching value'})
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source':'other compatibility setting'})
        apply_native_stealth(browser, compatibility)
        self.assertEqual([command for command,args in calls], ['Page.addScriptToEvaluateOnNewDocument'])
        self.assertIs(browser.execute_cdp_cmd, previous)
        with self.assertRaises(RuntimeError):
            apply_native_stealth(browser, lambda driver,**kw: (_ for _ in ()).throw(RuntimeError()))
        self.assertIs(browser.execute_cdp_cmd, previous)


class UserAgentApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProfileApiTests.asyncSetUp
    asyncTearDown = fixtures.ProfileApiTests.asyncTearDown

    def browser_version(self, version=VERSION):
        path = Path(self.engine.config.chrome_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'synthetic executable; version reader is mocked')
        return patch('xgenius.user_agent._binary_version', return_value=version)

    async def test_generation_and_closed_profile_copy_use_selected_core_not_imported_ua(self):
        rows = self.am.load_accounts();rows[0]['user_agent']='old-imported-user-agent';self.am.save_accounts(rows)
        with self.browser_version():
            generated = await (await self.client.get('/api/browser/user-agent')).json()
            info = await (await self.client.get('/api/accounts/alice/tools/user_agent')).json()
        self.assertTrue(generated['available'])
        self.assertEqual(info['user_agent'], UA)
        self.assertEqual(info['source'], 'generated')
        self.assertNotEqual(info['user_agent'], self.am.load_accounts()[0]['user_agent'])

    async def test_manual_ua_save_and_rejection_preserve_existing_profiles(self):
        with self.browser_version():
            response = await self.client.post('/api/accounts', json={'username':'manual','user_agent_mode':'manual','user_agent':UA})
            self.assertEqual(response.status, 200, await response.text())
            account = next(row for row in self.am.load_accounts() if row['username']=='manual')
            self.assertEqual(account['user_agent'], UA)
            self.assertEqual(account['user_agent_mode'], 'manual')
            response = await self.client.put('/api/accounts/manual', json={**account,'user_agent':UA.replace('151.', '152.')})
            self.assertEqual(response.status, 400, await response.text())
            self.assertEqual(next(row for row in self.am.load_accounts() if row['username']=='manual'), account)
        with self.browser_version('152.0.1.2'):
            info = await (await self.client.get('/api/accounts/manual/tools/user_agent')).json()
            self.assertFalse(info['available'])
            self.assertIn('does not match', info['error'])

    async def test_live_identity_reads_the_browser_without_navigating_user_tabs(self):
        browser = SimpleNamespace()
        self.am.accounts['alice'] = AccountState('alice', browser=browser)
        connection = Mock()
        connection.call.return_value = {'userAgent':UA, 'product':'Chrome/'+VERSION}
        @contextmanager
        def attached(browser, **kwargs):
            yield connection
        with patch('xgenius.browser_cdp.browser_connection', attached):
            response = await self.client.get('/api/accounts/alice/tools/user_agent')
            self.assertEqual(response.status, 200, await response.text())
            info = await response.json()
        self.assertEqual(info['user_agent'], UA)
        self.assertEqual(info['source'], 'live')
        connection.call.assert_called_once_with('Browser.getVersion')
        self.assertFalse(self.app.actions._profile_operations)
        self.am.accounts['alice'].browser = None


if __name__ == '__main__':
    unittest.main()
