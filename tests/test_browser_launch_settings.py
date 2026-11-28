"""Launching Chrome uses its real identity and the selected profile settings."""
import asyncio
import importlib.util
import json
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
        return {}

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
        self.proxy = types.SimpleNamespace(host='proxy.example',port=8080,server='http://proxy.example:8080', username=None, password=None,scheme='http')
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
                       parse_proxy=lambda value: self.proxy, resolve_proxy=lambda value: value, check_proxy=lambda value: '203.0.113.7',
                       parse_ip_response=lambda value: value),
                   'xgenius.settings': types.SimpleNamespace(BLOCK_MEDIA_URLS=True)}
        from xgenius.browser_proxy import prepare_proxy_extension
        modules['xgenius.browser_proxy']=types.SimpleNamespace(prepare_proxy_extension=prepare_proxy_extension,
            verify_browser_proxy=lambda browser,proxy,expected_ip=None:'203.0.113.7')
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
        self.addCleanup(lambda: getattr(browser, '_xg_profile_lease', None) and browser._xg_profile_lease.release())
        self.addCleanup(lambda: getattr(browser, '_xg_proxy_extension', None) and browser._xg_proxy_extension.cleanup())
        self.addCleanup(lambda: getattr(browser, '_xg_proxy_bridge', None) and browser._xg_proxy_bridge.cleanup())
        return browser

    def test_socks_launch_uses_an_authenticated_local_adapter_and_releases_it_on_failure(self):
        self.proxy.scheme = 'socks5'
        local = types.SimpleNamespace(host='127.0.0.1', port=19990, server='http://127.0.0.1:19990',
                                      username='local-user', password='local-pass', scheme='http')
        class Bridge:
            def __init__(bridge, upstream):
                self.assertIs(upstream, self.proxy)
                bridge.proxy = local
                bridge.closed = False
                bridges.append(bridge)
            def cleanup(bridge):
                bridge.closed = True
        bridges = []
        with patch.dict(sys.modules, {'xgenius.socks_bridge': types.SimpleNamespace(SocksBridge=Bridge)}):
            browser = asyncio.run(self.manager.create_browser(self.models.AccountCredentials('socks', '', proxy='proxy')))
            self.assertIn('--proxy-server=http://127.0.0.1:19990', browser.options.arguments)
            self.assertIs(browser._xg_proxy_bridge, bridges[0])
            self.assertFalse(bridges[0].closed)
            browser._xg_proxy_bridge.cleanup()
            with patch.object(self.browser_module.webdriver, 'Chrome', side_effect=RuntimeError('driver failed')):
                with self.assertRaises(self.settings.ProfileSettingsError):
                    asyncio.run(self.manager.create_browser(self.models.AccountCredentials('socks_failure', '', proxy='proxy')))
            self.assertTrue(bridges[-1].closed)

    def test_driver_start_failure_keeps_actionable_reason_and_redacts_secrets(self):
        credentials=self.models.AccountCredentials('alice','private-account-password',proxy='proxy')
        with patch.object(self.browser_module.webdriver,'Chrome',side_effect=RuntimeError(
                'This version of ChromeDriver only supports Chrome version 128 private-account-password')):
            with self.assertRaisesRegex(ValueError,'only supports Chrome version 128') as raised:
                asyncio.run(self.manager.create_browser(credentials))
        self.assertNotIn('private-account-password',str(raised.exception))

    def test_authenticated_http_uses_a_private_adapter_and_reports_real_upstream_rejection(self):
        self.proxy.username, self.proxy.password = 'provider-user', 'provider-password'
        local = types.SimpleNamespace(host='127.0.0.1', port=19991, server='http://127.0.0.1:19991',
                                      username='local-user', password='local-password', scheme='http')
        bridges = []
        class Bridge:
            last_error = None
            def __init__(bridge, upstream):
                self.assertIs(upstream, self.proxy)
                bridge.proxy, bridge.closed = local, False
                bridges.append(bridge)
            def cleanup(bridge):
                bridge.closed = True
        with patch.dict(sys.modules, {'xgenius.http_bridge': types.SimpleNamespace(HttpBridge=Bridge)}):
            browser = asyncio.run(self.manager.create_browser(self.models.AccountCredentials('http', '', proxy='proxy')))
            self.assertIn('--proxy-server=http://127.0.0.1:19991', browser.options.arguments)
            self.assertIs(browser._xg_proxy_bridge, bridges[0])
            worker = (Path(browser._xg_proxy_extension.name) / 'background.js').read_text()
            self.assertNotIn('provider-password', worker)
            self.assertIn('local-password', worker)
            def reject(browser, proxy):
                bridges[-1].last_error = 'Proxy authentication failed (407). Check login and password.'
                raise ValueError('Chrome could not connect through the proxy.')
            with patch.object(self.browser_module, 'verify_browser_proxy', side_effect=reject):
                with self.assertRaisesRegex(ValueError, 'Proxy authentication failed \\(407\\)'):
                    asyncio.run(self.manager.create_browser(self.models.AccountCredentials('http_rejected', '', proxy='proxy')))
            self.assertTrue(bridges[-1].closed)

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

    def test_proxy_verification_does_not_navigate_a_user_tab(self):
        with patch.object(self.browser_module,'ensure_search_engine',return_value={'ok':True}):
            browser=asyncio.run(self.manager.create_browser(self.models.AccountCredentials('quiet','',proxy='proxy')))
        self.assertEqual(browser.visited,[])
        self.assertEqual(browser._xg_proxy_ip,'203.0.113.7')

    def test_failure_after_proxy_verification_keeps_its_actual_reason(self):
        with patch.object(self.browser_module, 'prepare_workspace', side_effect=RuntimeError('session snapshot failed')):
            with self.assertRaisesRegex(self.settings.ProfileSettingsError, 'session snapshot failed') as raised:
                asyncio.run(self.manager.create_browser(self.models.AccountCredentials('quiet', '', proxy='proxy')))
        self.assertNotIn('proxy IP verification', str(raised.exception))
        self.assertEqual(self.closed, self.created)

    def test_manual_browser_keeps_native_gpu_acceleration_available(self):
        browser=asyncio.run(self.manager.create_browser(self.models.AccountCredentials('desktop','',proxy='proxy')))
        self.assertNotIn('--disable-gpu',browser.options.arguments)
        self.assertFalse(any(arg.startswith(('--use-gl=swiftshader','--use-angle=swiftshader','--disable-gpu-compositing'))
                             for arg in browser.options.arguments))

    def test_mismatch_stops_launch_and_closes_browser(self):
        self.version = '161.0.0.0'
        with self.assertRaisesRegex(self.settings.ProfileSettingsError, 'does not match'):
            asyncio.run(self.manager.create_browser(self.models.AccountCredentials('one', '', proxy='proxy')))
        self.assertEqual(self.closed, self.created)

    def test_policy_blocks_only_selected_resources_and_keeps_native_protection(self):
        credentials = self.models.AccountCredentials('policy', '', proxy='proxy',
            block_images=True, block_fonts=True, block_media=False, phishing_protection=False)
        browser = asyncio.run(self.manager.create_browser(credentials))
        arguments = browser.options.arguments
        loaded = [value for value in arguments if value.startswith('--load-extension=')]
        self.assertEqual(len(loaded), 1)
        extension = next(Path(path) for path in loaded[0].split('=',1)[1].split(',') if path.endswith('.xgenius-policy'))
        rules = json.loads((extension / 'rules.json').read_text())
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]['condition']['resourceTypes'], ['image', 'font'])
        self.assertTrue(browser.options.experimental['prefs']['safebrowsing.enabled'])
        for disabled in ('disable-client-side-phishing-detection', 'disable-background-networking', 'disable-component-update'):
            self.assertNotIn('--' + disabled, arguments)
            self.assertIn(disabled, browser.options.experimental['excludeSwitches'])
        self.assertFalse(any(command == 'Network.setBlockedURLs' for command, _ in browser.cdp))

    def test_policy_presets_and_proxy_authentication_load_together(self):
        self.proxy.username, self.proxy.password = 'proxy-user', 'proxy-password'
        preset = Path(self.temp.name) / 'preset-extension'
        preset.mkdir()
        with patch.object(self.browser_module.ExtensionSetStore, 'materialize', return_value=[preset]):
            browser = asyncio.run(self.manager.create_browser(
                self.models.AccountCredentials('combined', '', proxy='proxy')))
        loaded = [value for value in browser.options.arguments if value.startswith('--load-extension=')]
        self.assertEqual(len(loaded), 1)
        paths = {Path(value) for value in loaded[0].split('=', 1)[1].split(',')}
        self.assertEqual(paths, {preset, Path(browser._xg_proxy_extension.name),
            Path(self.temp.name) / 'combined' / '.xgenius-policy',Path(self.temp.name)/'combined'/'.xanty-profile-label'})
        proxy_manifest = json.loads((Path(browser._xg_proxy_extension.name) / 'manifest.json').read_text())
        self.assertIn('webRequestAuthProvider', proxy_manifest['permissions'])

    def test_all_policy_controls_disabled_load_no_policy_extension(self):
        browser = asyncio.run(self.manager.create_browser(self.models.AccountCredentials(
            'disabled', '', proxy='proxy', phishing_protection=False)))
        paths=[path for value in browser.options.arguments if value.startswith('--load-extension=') for path in value.split('=',1)[1].split(',')]
        self.assertFalse(any(path.endswith('.xgenius-policy') for path in paths))
        self.assertTrue(browser.options.experimental['prefs']['safebrowsing.enabled'])

    def test_invalid_policy_is_rejected_before_starting_chrome(self):
        credentials = self.models.AccountCredentials('invalid', '', proxy='proxy', block_media='false')
        with self.assertRaisesRegex(self.settings.ProfileSettingsError, 'block_media'):
            asyncio.run(self.manager.create_browser(credentials))
        self.assertEqual(self.created, [])


if __name__ == '__main__':
    unittest.main()
