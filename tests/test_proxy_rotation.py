import asyncio
import copy
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import requests

from xgenius.models import AccountState
from xgenius.proxy_rotation import ProxyRotationError, request_rotation, rotation_url
from xgenius.web.actions import Actions
from tests import test_profile_management as fixtures


URL = 'https://provider.example/rotate?key=PRIVATE_ROTATION_TOKEN'


class RotationServiceTests(unittest.TestCase):
    def test_only_valid_optional_http_links_are_saved(self):
        self.assertEqual(rotation_url('  ' + URL + '  '), URL)
        self.assertEqual(rotation_url('http://192.168.1.1/rotate'), 'http://192.168.1.1/rotate')
        self.assertEqual(rotation_url(None), '')
        for invalid in ([], 8, 'javascript:alert(1)', 'file:///local', 'https://',
                        'https://example.com:99999', 'https://example.com/a\nb',
                        'https://example.com/#ignored', 'https://example.com/' + 'a' * 8192):
            with self.subTest(invalid=str(invalid)[:60]), self.assertRaises(ProxyRotationError):
                rotation_url(invalid)

    def test_one_direct_request_has_a_timeout_no_environment_proxy_and_no_redirect(self):
        session = Mock()
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        session.get.return_value = SimpleNamespace(status_code=200, json=lambda: {'success': True})
        with patch('requests.Session', return_value=session):
            request_rotation(URL)
        self.assertFalse(session.trust_env)
        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args, (URL,))
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(kwargs['timeout'], (6, 120))

    def test_provider_failures_and_timeouts_do_not_expose_the_url_or_retry(self):
        for status, body, error in ((429, {}, None), (403, {}, None), (302, {}, None),
                                    (200, {'success': False}, None),
                                    (200, {'result': 'failure'}, None),
                                    (200, {'status': 'error', 'error': URL}, None),
                                    (200, {}, requests.exceptions.Timeout(URL)),
                                    (200, {}, requests.exceptions.ConnectionError(URL))):
            session = Mock()
            session.__enter__ = Mock(return_value=session)
            session.__exit__ = Mock(return_value=False)
            session.get.return_value = SimpleNamespace(status_code=status, json=lambda: body)
            session.get.side_effect = error
            with patch('requests.Session', return_value=session), self.assertRaises(ProxyRotationError) as caught:
                request_rotation(URL)
            self.assertNotIn('PRIVATE_ROTATION_TOKEN', str(caught.exception))
            session.get.assert_called_once()


class RotationActionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.rows = [{'username': 'alice', 'proxy': 'proxy.example:8080', 'proxy_rotation_url': URL}]
        self.manager = SimpleNamespace(accounts={'alice': AccountState('alice', proxy_ip='8.8.8.8')},
                                       load_accounts=lambda: copy.deepcopy(self.rows))
        self.engine = SimpleNamespace(loop=asyncio.get_running_loop(), account_manager=self.manager,
                                      notify=Mock(), logger=SimpleNamespace(info=Mock(), error=Mock()))
        self.actions = Actions(self.engine)
        self.location = patch('xgenius.web.actions.lookup_proxy_location', return_value={'country_code': 'US'})
        self.location.start()
        self.addCleanup(self.location.stop)

    async def test_double_click_shares_one_rotation_and_checks_the_new_exit_ip(self):
        started, finish = threading.Event(), threading.Event()
        def rotate(url):
            started.set()
            finish.wait(3)
        with patch('xgenius.web.actions.request_rotation', side_effect=rotate) as request, \
                patch('xgenius.web.actions.check_proxy', side_effect=['8.8.8.8', '8.8.4.4']):
            first = asyncio.create_task(self.actions.rotate_account_proxy('alice'))
            await asyncio.to_thread(started.wait, 2)
            self.assertTrue(self.manager.accounts['alice'].proxy_rotating)
            second = asyncio.create_task(self.actions.rotate_account_proxy('alice'))
            await asyncio.sleep(0)
            finish.set()
            one, two = await asyncio.gather(first, second)
        request.assert_called_once_with(URL)
        self.assertEqual(one, two)
        self.assertTrue(one['changed'])
        self.assertEqual(one['previous_ip'], '8.8.8.8')
        self.assertEqual(self.manager.accounts['alice'].proxy_ip, '8.8.4.4')
        self.assertFalse(self.manager.accounts['alice'].proxy_rotating)
        self.assertFalse(self.actions._profile_operations)
        self.assertNotIn('PRIVATE_ROTATION_TOKEN', str(self.engine.logger.info.call_args_list))

    async def test_rechecking_a_still_unchanged_ip_never_repeats_the_rotation_request(self):
        with patch('xgenius.web.actions.request_rotation') as request, \
                patch('xgenius.web.actions.check_proxy', return_value='8.8.8.8') as check, \
                patch('xgenius.web.actions.asyncio.sleep', new=AsyncMock()):
            result = await self.actions.rotate_account_proxy('alice')
        self.assertTrue(result['requested'])
        self.assertFalse(result['changed'])
        request.assert_called_once()
        self.assertEqual(check.call_count, 6)

    async def test_mobile_reconnect_is_waited_for_without_repeating_the_rotation_request(self):
        from xgenius.proxy_service import ProxyCheckError
        with patch('xgenius.web.actions.request_rotation') as request, \
                patch('xgenius.web.actions.check_proxy', side_effect=['8.8.8.8', ProxyCheckError('reconnecting'),
                      ProxyCheckError('reconnecting'), ProxyCheckError('reconnecting'), '8.8.4.4']) as check, \
                patch('xgenius.web.actions.asyncio.sleep', new=AsyncMock()) as sleep:
            result = await self.actions.rotate_account_proxy('alice')
        self.assertTrue(result['changed'])
        self.assertEqual(check.call_count, 5)
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [3, 6, 10])
        request.assert_called_once()

    async def test_an_unavailable_ip_is_reported_separately_from_an_accepted_rotation(self):
        from xgenius.proxy_service import ProxyCheckError
        with patch('xgenius.web.actions.request_rotation') as request, \
                patch('xgenius.web.actions.check_proxy', side_effect=ProxyCheckError('Proxy timed out')), \
                patch('xgenius.web.actions.asyncio.sleep', new=AsyncMock()):
            result = await self.actions.rotate_account_proxy('alice')
        request.assert_called_once()
        self.assertTrue(result['ok'])
        self.assertEqual(result['ip'], '')
        self.assertTrue(result['check_error'])
        self.assertIsNone(result['changed'])

    async def test_an_edited_proxy_during_rotation_does_not_receive_an_old_result(self):
        def rotate(url):
            self.rows[0]['proxy'] = 'different.example:8080'
        with patch('xgenius.web.actions.request_rotation', side_effect=rotate), \
                patch('xgenius.web.actions.check_proxy', return_value='8.8.8.8') as check:
            with self.assertRaisesRegex(Exception, 'settings changed'):
                await self.actions.rotate_account_proxy('alice')
        check.assert_called_once()  # Only the fresh baseline preceded the edit.
        self.assertFalse(self.manager.accounts['alice'].proxy_rotating)

    async def test_other_profiles_cannot_rotate_the_same_link_concurrently(self):
        self.rows.append({**self.rows[0], 'username': 'bob'})
        self.actions._rotating_urls.add(URL)
        with patch('xgenius.web.actions.request_rotation') as request:
            with self.assertRaisesRegex(Exception, 'already in use'):
                await self.actions.rotate_account_proxy('bob')
        request.assert_not_called()

    async def test_a_failed_request_clears_busy_state_and_the_cached_ip_without_retrying(self):
        with patch('xgenius.web.actions.request_rotation', side_effect=ProxyRotationError('Provider unavailable')) as request, \
                patch('xgenius.web.actions.check_proxy', return_value='8.8.8.8'):
            result = await self.actions.rotate_account_proxy('alice')
        self.assertFalse(result['ok'])
        self.assertEqual(self.manager.accounts['alice'].proxy_ip, '')
        self.assertFalse(self.manager.accounts['alice'].proxy_rotating)
        self.assertFalse(self.actions._profile_operations)
        self.assertFalse(self.actions._rotating_urls)
        request.assert_called_once()

    async def test_stale_cached_ip_never_proves_that_rotation_changed_the_ip(self):
        with patch('xgenius.web.actions.request_rotation') as request, \
                patch('xgenius.web.actions.check_proxy', return_value='1.1.1.1'), \
                patch('xgenius.web.actions.asyncio.sleep', new=AsyncMock()):
            result = await self.actions.rotate_account_proxy('alice')
        self.assertEqual(result['previous_ip'], '1.1.1.1')
        self.assertEqual(result['ip'], '1.1.1.1')
        self.assertFalse(result['changed'])
        request.assert_called_once()

    async def test_unavailable_baseline_reports_the_measured_ip_without_claiming_a_change(self):
        from xgenius.proxy_service import ProxyCheckError
        with patch('xgenius.web.actions.request_rotation'), \
                patch('xgenius.web.actions.check_proxy', side_effect=[ProxyCheckError('Unavailable'), '8.8.4.4']):
            result = await self.actions.rotate_account_proxy('alice')
        self.assertEqual(result['previous_ip'], '')
        self.assertEqual(result['ip'], '8.8.4.4')
        self.assertIsNone(result['changed'])


class RotationApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProfileApiTests.asyncSetUp
    asyncTearDown = fixtures.ProfileApiTests.asyncTearDown

    async def test_link_roundtrip_removal_redacted_history_and_public_snapshot(self):
        response = await self.client.put('/api/accounts/alice', json={'username': 'alice',
            'proxy': 'proxy.example:8080', 'proxy_rotation_url': URL})
        self.assertEqual(response.status, 200, await response.text())
        stored = await (await self.client.get('/api/accounts/alice')).json()
        self.assertEqual(stored['proxy_rotation_url'], URL)
        state = await (await self.client.get('/api/state')).json()
        self.assertTrue(state['accounts'][0]['has_proxy_rotation'])
        self.assertNotIn('PRIVATE_ROTATION_TOKEN', json.dumps(state))
        history = await (await self.client.get('/api/history')).json()
        self.assertNotIn('PRIVATE_ROTATION_TOKEN', json.dumps(history))
        response = await self.client.put('/api/accounts/alice', json={'username': 'alice',
            'proxy': 'proxy.example:8080'})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.am.load_accounts()[0]['proxy_rotation_url'], URL)
        response = await self.client.put('/api/accounts/alice', json={'username': 'alice',
            'proxy': 'proxy.example:8080', 'proxy_rotation_url': ''})
        self.assertEqual(response.status, 200)
        self.assertEqual(self.am.load_accounts()[0]['proxy_rotation_url'], '')

    async def test_invalid_link_is_rejected_before_saving_and_missing_links_never_send_requests(self):
        response = await self.client.post('/api/accounts', json={'username': 'charlie',
            'proxy_rotation_url': 'javascript:alert(1)'})
        self.assertEqual(response.status, 400)
        self.assertEqual(len(self.am.load_accounts()), 2)
        with patch('xgenius.web.actions.request_rotation') as request:
            response = await self.client.post('/api/accounts/alice/proxy/rotate', json={})
            self.assertEqual(response.status, 400)
        request.assert_not_called()

    async def test_only_post_can_trigger_rotation_and_it_verifies_the_ip(self):
        rows = self.am.load_accounts()
        rows[0]['proxy_rotation_url'] = URL
        self.am.save_accounts(rows)
        with patch('xgenius.web.actions.request_rotation') as request, \
                patch('xgenius.web.actions.check_proxy', return_value='8.8.4.4'), \
                patch('xgenius.web.actions.lookup_proxy_location', return_value={'country_code': 'US'}), \
                patch('xgenius.web.actions.asyncio.sleep', new=AsyncMock()):
            response = await self.client.get('/api/accounts/alice/proxy/rotate')
            self.assertEqual(response.status, 405)
            request.assert_not_called()
            response = await self.client.post('/api/accounts/alice/proxy/rotate', json={})
            self.assertEqual(response.status, 200, await response.text())
            result = await response.json()
            self.assertEqual(result['ip'], '8.8.4.4')
        request.assert_called_once_with(URL)

