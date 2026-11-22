"""Closing a Chrome window clears both manual and signed-in profile state."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from xgenius.accounts.health import HealthMixin
from xgenius.browser_lifecycle import browser_process_alive
from xgenius.models import AccountState


class Manager(HealthMixin):
    def __init__(self):
        self.accounts = {}
        self.logger = SimpleNamespace(info=Mock(), warning=Mock(), error=Mock())
        self.on_state_change = Mock()


class BrowserLivenessTests(unittest.TestCase):
    def test_exact_chrome_process_death_is_detected_with_driver_still_running(self):
        chrome = SimpleNamespace(is_running=lambda: False)
        browser = SimpleNamespace(_xg_browser_process=chrome,
                                  service=SimpleNamespace(process=SimpleNamespace(poll=lambda: None)))
        self.assertFalse(browser_process_alive(browser))

    def test_running_browser_and_dead_driver_are_distinguished(self):
        chrome = SimpleNamespace(is_running=lambda: True, status=lambda: 'running')
        browser = SimpleNamespace(_xg_browser_process=chrome,
                                  service=SimpleNamespace(process=SimpleNamespace(poll=lambda: None)))
        self.assertTrue(browser_process_alive(browser))
        browser.service.process.poll = lambda: 1
        self.assertFalse(browser_process_alive(browser))

    def test_manual_and_signed_in_profiles_are_reset_without_an_error_status(self):
        for active in (False, True):
            with self.subTest(active=active):
                manager = Manager()
                browser = SimpleNamespace(_xg_browser_process=SimpleNamespace(is_running=lambda: False))
                state = manager.accounts['test'] = AccountState('test', browser=browser, is_active=active,
                                                                need_relogin=True, status_reason='RELOGIN')
                manager.refresh_closed_browsers()
                self.assertIsNone(state.browser)
                self.assertFalse(state.is_active)
                self.assertFalse(state.need_relogin)
                self.assertEqual(state.status_reason, '')
                manager.on_state_change.assert_called_once()

    def test_a_late_probe_never_clears_a_replacement_browser(self):
        manager = Manager()
        replacement = object()
        state = AccountState('test', browser=replacement, is_active=True)
        self.assertFalse(manager.mark_browser_closed('test', state, object()))
        self.assertIs(state.browser, replacement)
        self.assertTrue(state.is_active)


class BrowserHealthTests(unittest.IsolatedAsyncioTestCase):
    async def test_other_open_windows_are_kept_even_when_the_old_tab_was_closed(self):
        manager = Manager()
        browser = SimpleNamespace(window_handles=['another-window'])
        self.assertEqual(await manager.check_browser_health_detailed(browser), 'OK')
        browser.window_handles = []
        self.assertEqual(await manager.check_browser_health_detailed(browser), 'CLOSED')

    async def test_tracked_live_process_does_not_execute_commands_on_user_pages(self):
        manager = Manager()
        chrome = SimpleNamespace(is_running=lambda: True, status=lambda: 'running')
        browser = SimpleNamespace(_xg_browser_process=chrome)
        self.assertEqual(await manager.check_browser_health_detailed(browser), 'OK')

    async def test_watchdog_checks_manual_profiles_and_preserves_slow_browsers(self):
        for health in ('CLOSED', 'TIMEOUT'):
            manager = Manager()
            browser = object()
            state = manager.accounts['test'] = AccountState('test', browser=browser, is_active=False)
            calls = 0

            async def sleep(seconds):
                nonlocal calls
                calls += 1
                if calls > 1:
                    raise asyncio.CancelledError()

            async def probe(value):
                self.assertIs(value, browser)
                return health

            manager.check_browser_health_detailed = probe
            with patch('xgenius.accounts.health.asyncio.sleep', side_effect=sleep), \
                 patch('xgenius.accounts.health.hard_close_browser'):
                await manager.idle_health_watchdog()
            if health == 'CLOSED':
                self.assertIsNone(state.browser)
            else:
                self.assertIs(state.browser, browser)
                self.assertEqual(state.status_reason, '')


if __name__ == '__main__':
    unittest.main()
