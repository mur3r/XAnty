"""Repeated inline checks share one request and expose success or failure state."""
import asyncio
import copy
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xgenius.proxy_service import ProxyCheckError
from xgenius.web.actions import Actions


class ProxyButtonTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        account = {'username': 'test', 'proxy': 'http://user:secret@proxy.test:80'}
        manager = SimpleNamespace(accounts={}, load_accounts=lambda: [copy.deepcopy(account)])
        engine = SimpleNamespace(account_manager=manager, loop=asyncio.get_running_loop(), notify=Mock(),
                                 logger=SimpleNamespace(info=Mock(), error=Mock()))
        self.actions = Actions(engine)
        self.manager = manager
        self.location_patch = patch('xgenius.web.actions.lookup_proxy_location',
                                    return_value={'country_code': 'US', 'country': 'United States',
                                                  'region': 'Florida', 'city': 'Miami'}, create=True)
        self.location_patch.start()
        self.addCleanup(self.location_patch.stop)

    async def test_location_is_in_response_and_state_and_is_cleared_on_failure(self):
        with patch('xgenius.web.actions.check_proxy', return_value='8.8.8.8'):
            result = await self.actions.check_account_proxy('test')
        self.assertEqual(result['location']['region'], 'Florida')
        self.assertEqual(self.manager.accounts['test'].proxy_location['country_code'], 'US')
        with patch('xgenius.web.actions.check_proxy', side_effect=ProxyCheckError('Failed')):
            await self.actions.check_account_proxy('test')
        self.assertEqual(self.manager.accounts['test'].proxy_location, {})

    async def test_geography_failure_keeps_proxy_success(self):
        with patch('xgenius.web.actions.check_proxy', return_value='8.8.8.8'), \
                patch('xgenius.web.actions.lookup_proxy_location', side_effect=ProxyCheckError('Location unavailable'), create=True):
            result = await self.actions.check_account_proxy('test')
        self.assertTrue(result['ok'])
        self.assertEqual(result['ip'], '8.8.8.8')
        self.assertEqual(result['location'], {})
        self.assertTrue(result['location_error'])

    async def test_changed_proxy_discards_late_result(self):
        def check(proxy):
            self.manager.load_accounts = lambda: [{'username': 'test', 'proxy': 'new-host:80'}]
            return '8.8.8.8'
        with patch('xgenius.web.actions.check_proxy', side_effect=check):
            result = await self.actions.check_account_proxy('test')
        self.assertFalse(result['ok'])
        self.assertEqual(self.manager.accounts['test'].proxy_ip, '')

    async def test_simultaneous_clicks_share_a_request_and_a_later_click_rechecks(self):
        def success(proxy):
            time.sleep(0.04)
            return '203.0.113.1'

        with patch('xgenius.web.actions.check_proxy', side_effect=success) as check:
            one, two = await asyncio.gather(self.actions.check_account_proxy('test'),
                                            self.actions.check_account_proxy('test'))
            self.assertEqual(check.call_count, 1)
            self.assertEqual(one, two)
            self.assertEqual(one['ip'], '203.0.113.1')
            await self.actions.check_account_proxy('test')
            self.assertEqual(check.call_count, 2)
        self.assertEqual(self.manager.accounts['test'].proxy_status, 'ok')

    async def test_failed_check_has_no_stale_ip_and_a_success_clears_the_error(self):
        with patch('xgenius.web.actions.check_proxy', return_value='203.0.113.1'):
            await self.actions.check_account_proxy('test')
        with patch('xgenius.web.actions.check_proxy', side_effect=ProxyCheckError('Proxy authentication failed (407)')):
            failed = await self.actions.check_account_proxy('test')
        state = self.manager.accounts['test']
        self.assertFalse(failed['ok'])
        self.assertEqual(state.proxy_status, 'error')
        self.assertEqual(state.proxy_ip, '')
        self.assertNotIn('secret', failed['error'])
        with patch('xgenius.web.actions.check_proxy', return_value='203.0.113.2'):
            success = await self.actions.check_account_proxy('test')
        self.assertTrue(success['ok'])
        self.assertEqual(state.proxy_status, 'ok')
        self.assertEqual(state.proxy_error, '')
        self.assertEqual(state.status_reason, '')


if __name__ == '__main__':
    unittest.main()
