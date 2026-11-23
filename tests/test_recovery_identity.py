"""Recovery keeps the same profile presentation and browser options."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from xgenius.accounts.auth import AuthMixin
from xgenius.models import AccountState


class RecoveryIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_recovery_keeps_saved_identity_and_workspace_options(self):
        account = {'username': 'internal-id', 'profile_name': 'Рабочий профиль',
                   'profile_id': 'stable-identity', 'profile_number': 12, 'icon_text': 'Раб12',
                   'auto_login': False, 'restore_tabs': False, 'extension_set': 'a' * 32,
                   'block_images': True, 'phishing_protection': False}
        manager = SimpleNamespace(accounts={'internal-id': AccountState(username='internal-id')},
                                  load_accounts=lambda: [account], logger=Mock())

        async def opened(credentials, **kwargs):
            manager.accounts['internal-id'].browser = object()

        manager.login_account = AsyncMock(side_effect=opened)
        self.assertTrue(await AuthMixin.auto_relogin_if_needed(manager, 'internal-id', force=True))
        credentials = manager.login_account.call_args.args[0]
        for key in ('profile_name', 'profile_id', 'profile_number', 'icon_text', 'auto_login',
                    'restore_tabs', 'extension_set', 'block_images', 'phishing_protection'):
            self.assertEqual(getattr(credentials, key), account[key], key)
