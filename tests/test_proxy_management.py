"""Profile proxy assignments and shared exit warnings use completed observations."""
import json
import unittest
from xgenius.models import AccountState
from tests import test_profile_management as fixtures


class ProxyManagementApiTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.ProfileApiTests.asyncSetUp
    asyncTearDown = fixtures.ProfileApiTests.asyncTearDown

    async def set_proxies(self, proxies):
        rows = self.am.load_accounts()
        for row in rows:
            row['proxy'] = proxies[row['username']]
        self.am.save_accounts(rows)

    async def state(self):
        response = await self.client.get('/api/state')
        self.assertEqual(response.status, 200)
        return (await response.json())['accounts']

    async def test_protocol_and_profile_assignment_persist_without_exposing_credentials(self):
        proxies = {'alice': 'https://user:synthetic-tls-secret@proxy.example:443',
                   'bob': 'socks5://user:synthetic-socks-secret@proxy.example:1080'}
        await self.set_proxies(proxies)
        rows = await self.state()
        self.assertEqual([row['proxy_protocol'] for row in rows], ['https', 'socks5'])
        self.assertNotIn('synthetic-', json.dumps(rows))
        self.assertEqual({row['username']: row['proxy'] for row in self.am.load_accounts()}, proxies)
        await self.set_proxies({'alice': 'proxy.example:8080', 'bob': ''})
        self.assertEqual([row['proxy_protocol'] for row in await self.state()], ['auto', ''])

    async def test_duplicate_exit_is_reported_across_folders_and_disappears_after_recheck(self):
        await self.set_proxies({'alice': 'https://first.example:443', 'bob': 'socks5://second.example:1080'})
        self.am.accounts = {name: AccountState(name, proxy_status='ok', proxy_ip=ip)
                            for name, ip in (('alice', '8.8.8.8'), ('bob', '::ffff:8.8.8.8'))}
        self.assertEqual([row['proxy_ip_shared_count'] for row in await self.state()], [1, 1])
        self.am.accounts['bob'].proxy_ip = '8.8.4.4'
        self.assertEqual([row['proxy_ip_shared_count'] for row in await self.state()], [0, 0])

    async def test_failed_unchecked_or_rotating_profiles_do_not_produce_stale_warnings(self):
        await self.set_proxies({'alice': 'first.example:80', 'bob': 'second.example:80'})
        self.am.accounts = {name: AccountState(name, proxy_status='ok', proxy_ip='8.8.8.8')
                            for name in ('alice', 'bob')}
        for status, rotating in (('error', False), ('checking', False), ('', False), ('ok', True)):
            self.am.accounts['bob'].proxy_status = status
            self.am.accounts['bob'].proxy_rotating = rotating
            self.assertEqual([row['proxy_ip_shared_count'] for row in await self.state()], [0, 0])
        self.am.accounts['bob'].proxy_rotating = False
        self.am.accounts['bob'].proxy_status = 'ok'
        self.am.accounts['bob'].proxy_ip = 'invalid'
        self.assertEqual([row['proxy_ip_shared_count'] for row in await self.state()], [0, 0])
