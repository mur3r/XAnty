import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from xgenius.models import AccountState
from xgenius.web.actions import Actions


class LaunchErrors(unittest.IsolatedAsyncioTestCase):
    async def test_launch_failure_is_visible_and_does_not_expose_credentials(self):
        async def login(*args, **kwargs):
            raise RuntimeError('Cannot start http://u:private-password@host:80 private-token')
        state = AccountState(username='alice')
        manager = SimpleNamespace(accounts={'alice': state}, login_account=login,
                                  load_accounts=lambda: [{'username': 'alice', 'proxy': 'host:80:u:private-password',
                                                          'auth_token': 'private-token', 'auto_login': False}])
        actions = Actions(SimpleNamespace(account_manager=manager, loop=asyncio.get_running_loop(),
                                          notify=Mock(), logger=SimpleNamespace(info=Mock(), error=Mock())))
        self.assertFalse(await actions.login_one('alice'))
        self.assertTrue(state.launch_error)
        self.assertEqual(state.status_reason, 'BROWSER ERROR')
        self.assertNotIn('private-password', state.launch_error)
        self.assertNotIn('private-token', state.launch_error)
        first = state.launch_error_seq
        await actions.login_one('alice')
        self.assertGreater(state.launch_error_seq, first, 'repeated identical failures remain observable')
