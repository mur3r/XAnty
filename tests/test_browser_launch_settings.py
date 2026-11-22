"""Launching Chrome uses its real identity and the selected profile settings."""
import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / 'xgenius'


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class FakeOptions:
    def __init__(self):
        self.arguments = []
        self.experimental = {}

    def add_argument(self, value):
        self.arguments.append(value)

    def add_experimental_option(self, key, value):
        self.experimental[key] = value


class FakeChrome:
    def __init__(self, options, browser_version):
        self.options = options
        self.capabilities = {'browserVersion': browser_version}
        self.visited = []
        self.cdp = []

    def get(self, url):
        self.visited.append(url)

    def execute_script(self, source):
        if 'document.body' in source:
            return '203.0.113.7'
        if 'webglVendor' in source:
            return {'ua': 'Mozilla/5.0 Chrome/162.0.0.0 Safari/537.36',
                    'languages': ['uk-UA', 'uk'], 'vendor': 'Google Inc.', 'platform': 'Win32',
                    'webglVendor': 'Google Inc.', 'renderer': 'ANGLE (Native GPU)'}
        return 'Mozilla/5.0 Chrome/162.0.0.0 Safari/537.36'

    def execute_cdp_cmd(self, command, arguments):
        self.cdp.append((command, arguments))

    def execute_async_script(self, script):
        return {'ok': True, 'changed': False, 'url': 'https://www.google.com/search?q=%s'}

    def set_page_load_timeout(self, timeout):
        pass

    def set_script_timeout(self, timeout):
        pass


class BrowserLaunchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.created = []
        self.stealth_args = []
        self.closed = []
        self.version = '162.0.1234.55'
        chrome_webdriver = types.ModuleType('selenium.webdriver')
        chrome_webdriver.Chrome = lambda service, options: self._new_browser(options)
        options_module = types.ModuleType('selenium.webdriver.chrome.options')
        options_module.Options = FakeOptions
        service_module = types.ModuleType('selenium.webdriver.chrome.service')
        service_module.Service = lambda path: types.SimpleNamespace(process=types.SimpleNamespace(pid=123))
        selenium = types.ModuleType('selenium')
        selenium.webdriver = chrome_webdriver
        proxy = types.SimpleNamespace(server='http://proxy.example:8080', username=None)
        package = types.ModuleType('xgenius')
        package.__path__ = [str(ROOT)]
        modules = {'xgenius': package, 'selenium': selenium,
                   'selenium.webdriver': chrome_webdriver,
                   'selenium.webdriver.chrome': types.ModuleType('selenium.webdriver.chrome'),
                   'selenium.webdriver.chrome.options': options_module,
                   'selenium.webdriver.chrome.service': service_module,
                   'selenium_stealth': types.SimpleNamespace(stealth=lambda driver, **kw: self.stealth_args.append(kw)),
                   'xgenius.config': types.SimpleNamespace(Config=object),
                   'xgenius.process_utils': types.SimpleNamespace(hard_close_browser=lambda b: self.closed.append(b)),
                   'xgenius.proxy_service': types.SimpleNamespace(
                       IP_CHECK_URL='https://check.example/ip', ProxyCheckError=ValueError,
                       parse_proxy=lambda value: proxy, check_proxy=lambda value: '203.0.113.7',
                       parse_ip_response=lambda value: value),
                   'xgenius.settings': types.SimpleNamespace(BLOCK_MEDIA_URLS=False)}
        context = patch.dict(sys.modules, modules)
        context.start()
        self.addCleanup(context.stop)
        self.settings = load_module('xgenius.profile_settings', ROOT / 'profile_settings.py')
        self.models = load_module('xgenius.models', ROOT / 'models.py')
        self.browser_module = load_module('xgenius.browser', ROOT / 'browser.py')
        config = types.SimpleNamespace(base_dir=Path(self.temp.name), chrome_path='chrome.exe', chromedriver_path='chromedriver.exe',
            get_profile_dir=lambda username: Path(self.temp.name) / username)
        self.manager = self.browser_module.BrowserManager(config, self.models.BrowserConfig())

    def _new_browser(self, options):
        browser = FakeChrome(options, self.version)
        self.created.append(browser)
        return browser

    def test_real_chrome_version_native_ua_and_profile_preferences(self):
        credentials = self.models.AccountCredentials('alice', '', proxy='proxy',
            user_agent='Mozilla/5.0 Chrome/128.0.0.0', browser_language='uk-UA',
            browser_timezone='Europe/Kyiv', window_width=1280, window_height=800)
        browser = asyncio.run(self.manager.create_browser(credentials))
        self.assertEqual(browser._xg_browser_version, self.version)
        self.assertIn('Chrome/162.', browser._xg_user_agent)
        self.assertFalse(any('user-agent=' in arg for arg in browser.options.arguments))
        self.assertIn('--window-size=1280,800', browser.options.arguments)
        self.assertIn('--lang=uk-UA', browser.options.arguments)
        self.assertEqual(self.stealth_args[0]['renderer'], 'ANGLE (Native GPU)')
        self.assertEqual(self.stealth_args[0]['user_agent'], browser._xg_user_agent)
        self.assertIn(('Emulation.setTimezoneOverride', {'timezoneId': 'Europe/Kyiv'}), browser.cdp)

    def test_mismatch_stops_launch_and_closes_browser(self):
        self.version = '161.0.0.0'
        with self.assertRaisesRegex(self.settings.ProfileSettingsError, 'does not match'):
            asyncio.run(self.manager.create_browser(self.models.AccountCredentials('one', '', proxy='proxy')))
        self.assertEqual(self.closed, self.created)


if __name__ == '__main__':
    unittest.main()
