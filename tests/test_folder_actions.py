"""Folder operations must update only membership, never the account itself."""
import copy
import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "xgenius"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeAccountManager:
    def __init__(self):
        self.data = [
            {"username": "one", "group": "", "proxy": "proxy-one"},
            {"username": "two", "group": "", "proxy": "proxy-two"},
            {"username": "three", "group": "", "proxy": "proxy-three"},
        ]
        self.accounts = {}

    def load_accounts(self):
        return copy.deepcopy(self.data)

    def save_accounts(self, value):
        self.data = copy.deepcopy(value)


class FolderActionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        package = types.ModuleType("xgenius")
        package.__path__ = [str(ROOT)]
        modules = {"xgenius": package,
                   "xgenius.models": types.SimpleNamespace(AccountCredentials=object, AccountState=object),
                   "xgenius.auto_login_policy": types.SimpleNamespace(apply_auto_login=lambda *a: None,
                                                                        is_auto_login_enabled=lambda a: True),
                   "xgenius.process_utils": types.SimpleNamespace(hard_close_browser=lambda *a: None,
                                                                    kill_orphan_chrome=lambda *a: None),
                   "xgenius.proxy_service": types.SimpleNamespace(ProxyCheckError=Exception,
                                                                    check_proxy=lambda *a: None,
                                                                    lookup_proxy_location=lambda *a: {},
                                                                    parse_proxy=lambda *a: None),
                   "xgenius.settings": types.SimpleNamespace(LOGIN_DELAY_SECONDS=0)}
        self.modules_patch = patch.dict(sys.modules, modules)
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        folder_module = load_module("xgenius.folders", ROOT / "folders.py")
        action_module = load_module("xgenius.web.actions", ROOT / "web" / "actions.py")
        am = FakeAccountManager()
        engine = types.SimpleNamespace(account_manager=am,
                                       config=types.SimpleNamespace(base_dir=Path(self.temp.name),
                                                                    browser_profiles_dir=Path(self.temp.name) / 'browser_profiles'),
                                       loop=asyncio.new_event_loop(),
                                       proxy_label=lambda proxy: proxy.split('@')[-1],
                                       folders=folder_module.FolderStore(Path(self.temp.name) / "folders.json"),
                                       logger=types.SimpleNamespace(info=lambda *a: None),
                                       notify=lambda: None)
        self.engine = engine
        self.addCleanup(engine.loop.close)
        self.actions = action_module.Actions(engine)
        self.error = action_module.ActionError

    def test_create_move_rename_delete_preserves_accounts(self):
        self.actions.create_folder("Campaign", ["one", "two"])
        self.assertEqual([a["group"] for a in self.engine.account_manager.data],
                         ["Campaign", "Campaign", ""])
        self.actions.move_to_folder(["two"], "")
        self.actions.rename_folder("Campaign", "Campaign 2")
        self.assertEqual([a["group"] for a in self.engine.account_manager.data],
                         ["Campaign 2", "", ""])
        self.assertEqual(self.actions.delete_folder("Campaign 2"), 1)
        self.assertEqual([a["group"] for a in self.engine.account_manager.data], ["", "", ""])
        self.assertEqual([a["proxy"] for a in self.engine.account_manager.data],
                         ["proxy-one", "proxy-two", "proxy-three"])
        self.assertEqual(self.engine.folders.list(), [])

    def test_unknown_profile_does_not_create_folder(self):
        with self.assertRaises(self.error):
            self.actions.create_folder("New", ["missing"])
        self.assertEqual(self.engine.folders.list(), [])

    def test_cookie_import_export_targets_only_selected_closed_profile(self):
        data = [{'name': 'auth_token', 'value': 'alice-only', 'domain': '.x.com'}]
        self.assertEqual(self.actions.import_cookies('one', data), 1)
        self.assertEqual(asyncio.run(self.actions.export_cookies('one'))[0]['value'], 'alice-only')
        with self.assertRaises(self.error):
            asyncio.run(self.actions.export_cookies('two'))
        self.engine.account_manager.accounts['one'] = types.SimpleNamespace(browser=object())
        with self.assertRaisesRegex(self.error, 'Close this profile'):
            self.actions.import_cookies('one', data)
        with self.assertRaisesRegex(self.error, 'Account not found'):
            self.actions.import_cookies('missing', data)

    def test_renaming_profile_keeps_its_browser_and_cookie_session(self):
        self.actions.import_cookies('one', [{'name': 'auth_token', 'value': 'private', 'domain': '.x.com'}])
        profile = self.engine.config.browser_profiles_dir / 'profile_one'
        profile.mkdir(parents=True)
        (profile / 'Preferences').write_text('saved')
        self.actions.edit_account('one', {'username': 'renamed'})
        self.assertEqual(asyncio.run(self.actions.export_cookies('renamed'))[0]['value'], 'private')
        self.assertTrue((self.engine.config.browser_profiles_dir / 'profile_renamed' / 'Preferences').is_file())
        self.assertFalse(profile.exists())

    def test_browser_preferences_are_per_profile_and_invalid_edit_is_atomic(self):
        self.actions.edit_account('one', {'username': 'one', 'browser_language': 'uk-UA',
                                          'browser_timezone': 'Europe/Kyiv',
                                          'window_width': '1280', 'window_height': '800'})
        self.assertEqual(self.actions.get_account('one')['browser_language'], 'uk-UA')
        self.assertEqual(self.actions.get_account('two')['browser_language'], '')
        with self.assertRaises(self.error):
            self.actions.edit_account('one', {'username': 'one', 'browser_timezone': '--invalid'})
        self.assertEqual(self.actions.get_account('one')['browser_timezone'], 'Europe/Kyiv')

    def test_bulk_browser_settings_only_change_selected_profiles(self):
        self.assertEqual(self.actions.bulk_edit(['one', 'three'], None, None, settings={
            'browser_language': 'uk-UA', 'window_width': 1280}), 2)
        accounts = self.engine.account_manager.data
        self.assertEqual([a.get('browser_language', '') for a in accounts], ['uk-UA', '', 'uk-UA'])
        before = copy.deepcopy(accounts)
        with self.assertRaises(self.error):
            self.actions.bulk_edit(['one', 'two'], None, None, settings={'window_height': 5})
        self.assertEqual(self.engine.account_manager.data, before)

    def test_dolphin_pilot_then_mass_import_reports_duplicates_and_errors(self):
        def candidate(source_id):
            return ({'username': f'imported_{source_id}', 'group': 'Dolphin',
                     'dolphin_profile_id': source_id, 'dolphin_name': 'Pilot',
                     'proxy': '', 'browser_language': '', 'browser_timezone': '',
                     'window_width': 1024, 'window_height': 768, 'auto_login': False},
                    [{'name': 'auth_token', 'value': str(source_id), 'domain': '.x.com'}],
                    ['Check source fingerprint'])
        def fetch(token, source_id, password, username, folder):
            if source_id == 3:
                raise self.error('Source profile is unavailable')
            return candidate(source_id)
        self.actions._fetch_dolphin = fetch
        self.actions._dolphin_ids = lambda token, limit: [1, 2, 3]
        preview = self.engine.loop.run_until_complete(self.actions.preview_dolphin('token', 1))
        self.assertEqual(preview['x_cookies'], 1)
        self.assertNotIn('value', preview)
        pilot = self.engine.loop.run_until_complete(self.actions.import_dolphin_one('token', 1))
        self.assertEqual(pilot['status'], 'added')
        report = self.engine.loop.run_until_complete(self.actions.import_dolphin_many('token'))
        self.assertEqual([r['status'] for r in report['report']], ['skipped', 'added', 'error'])
        self.assertFalse(next(a for a in self.engine.account_manager.data if a['username'] == 'imported_1')['auto_login'])


if __name__ == "__main__":
    unittest.main()
