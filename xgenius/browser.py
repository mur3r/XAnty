"""Create Chrome with profile settings, local resource policy and proxy authentication."""

import asyncio
import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium_stealth import stealth

from xgenius.config import Config
from xgenius.models import AccountCredentials, BrowserConfig
from xgenius.process_utils import hard_close_browser
from xgenius.proxy_service import ProxyCheckError, parse_proxy
from xgenius.browser_proxy import prepare_proxy_extension, verify_browser_proxy
from xgenius.profile_settings import ProfileSettingsError, browser_settings, workspace_settings
from xgenius.browser_policy import BrowserPolicyError, prepare_policy_extension
from xgenius.error_messages import safe_launch_error
from xgenius.portable_session import apply_session
from xgenius.browser_search import SearchConfigurationError, ensure_search_engine
from xgenius.browser_lifecycle import track_browser_process
from xgenius.profile_leases import ProfileLease
from xgenius.browser_workspace import prepare_workspace, browser_lock
from xgenius.extension_sets import ExtensionSetStore
from xgenius.profile_identity import prepare_identity, attach_identity
from xgenius.profile_branding import prepare_branding


# Размер экрана нужен для позиционирования окон Chrome (без tkinter: WinAPI на Windows)
def _screen_size():
    try:
        import ctypes
        user32 = ctypes.windll.user32
        return int(user32.GetSystemMetrics(0)), int(user32.GetSystemMetrics(1))
    except Exception:
        return 1920, 1080


SCREEN_WIDTH, SCREEN_HEIGHT = _screen_size()

# --------------------- BrowserManager ---------------------
class BrowserManager:
    def __init__(self, config: Config, browser_config: BrowserConfig):
        self.config = config
        self.browser_config = browser_config
        self._launches = set()
        self._cleanups = set()
        self._stopping = False

    async def shutdown(self):
        self._stopping = True
        while self._launches or self._cleanups:
            await asyncio.gather(*list(self._launches | self._cleanups), return_exceptions=True)

    async def create_browser(self, credentials: AccountCredentials) -> webdriver.Chrome:
        if self._stopping:
            raise ValueError('Application is shutting down')
        profile = self.config.get_profile_dir(credentials.username)
        lease = ProfileLease.acquire_path(profile)
        task = asyncio.create_task(self._create_browser(credentials))
        self._launches.add(task)
        task.add_done_callback(self._launches.discard)
        try:
            browser = await asyncio.shield(task)
            browser._xg_profile_lease = lease
            if self._stopping:
                await asyncio.get_running_loop().run_in_executor(None,hard_close_browser,browser)
                raise ValueError('Application is shutting down')
            return browser
        except asyncio.CancelledError:
            async def cleanup_late_launch():
                try:
                    late = await task
                    late._xg_profile_lease = lease
                    await asyncio.get_running_loop().run_in_executor(None, hard_close_browser, late)
                except Exception:
                    pass
                finally:
                    lease.release()
            cleanup = asyncio.create_task(cleanup_late_launch())
            self._cleanups.add(cleanup)
            cleanup.add_done_callback(self._cleanups.discard)
            raise
        except BaseException:
            lease.release()
            raise

    async def _create_browser(self, credentials: AccountCredentials) -> webdriver.Chrome:
        # Fail before starting Chrome, including automatic recovery paths.
        workspace = workspace_settings(vars(credentials))
        proxy = parse_proxy(credentials.proxy)
        loop = asyncio.get_event_loop()
        extension_dir = None
        proxy_bridge = None
        browser = None
        proxy_verified = False
        try:
            from xgenius.proxy_service import resolve_proxy
            proxy = await loop.run_in_executor(None, resolve_proxy, proxy)
            if proxy.scheme == 'socks5':
                from xgenius.socks_bridge import SocksBridge
                proxy_bridge = SocksBridge(proxy)
                proxy = proxy_bridge.proxy
            chrome_bin = self.config.chrome_path
            driver_path = self.config.chromedriver_path
            options = Options()
            options.binary_location = str(chrome_bin)

            # 1. Возвращаем стандартную стратегию, чтобы React успевал отрендерить элементы
            options.page_load_strategy = "normal"

            # Let Chrome select supported GPU acceleration for interactive use.
            # Forcing software compositing makes scrolling/window activation slow.
            options.add_argument("--mute-audio")
            options.add_argument("--no-default-browser-check")
            options.add_argument("--no-first-run")
            options.add_argument("--disable-dev-shm-usage") # Обязательно для экономии RAM
            options.add_argument("--disable-background-mode")
            options.add_argument("--disable-search-engine-choice-screen")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-default-apps")
            options.add_argument("--metrics-recording-only")
            options.add_argument("--log-level=3")
            # Keep autoplay opt-in without disabling accelerated rendering.
            options.add_argument("--autoplay-policy=user-gesture-required")
            options.add_argument("--disable-features=Translate,MediaRouter,OptimizationHints,InterestFeedContentSuggestions,BackForwardCache")
            # ChromeDriver supplies these switches by default in some versions.
            # Background networking and component updates keep native Safe
            # Browsing lists/models current alongside our local address hints.
            options.add_experimental_option('excludeSwitches', [
                'disable-background-networking', 'disable-client-side-phishing-detection',
                'disable-component-update'])

            prefs = {
                "profile.default_content_setting_values.notifications": 2,
                "profile.default_content_setting_values.geolocation": 2,
                "profile.default_content_settings.popups": 0,
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "background_mode.enabled": False,
                "session.restore_on_startup": 1 if workspace['restore_tabs'] else 5,
                "safebrowsing.enabled": True,
            }
            settings = browser_settings(vars(credentials))
            if settings['browser_language']:
                language = settings['browser_language']
                options.add_argument(f'--lang={language}')
                prefs['intl.accept_languages'] = language
            options.add_experimental_option("prefs", prefs)

            # 3. Увеличиваем ширину окна до десктопного брейкпоинта (минимум 1024px)
            user_profile = str(self.config.get_profile_dir(credentials.username))
            identity = await loop.run_in_executor(None, prepare_identity, self.config,credentials.username,
                credentials.profile_name,credentials.profile_id,credentials.profile_number,credentials.icon_text)
            options.add_argument(f"--user-data-dir={user_profile}")
            if workspace['restore_tabs']:
                options.add_argument('--restore-last-session')
            extension_paths = ExtensionSetStore(self.config).materialize(workspace['extension_set'], Path(user_profile))
            extension_paths.append(await loop.run_in_executor(None,prepare_branding,Path(user_profile),identity))
            policy_extension = await loop.run_in_executor(
                None, prepare_policy_extension, Path(user_profile), workspace)
            if policy_extension is not None:
                extension_paths.append(policy_extension)

            if credentials.headless:
                options.add_argument("--headless=new")
                options.add_argument(f"--window-size={settings['window_width']},{settings['window_height']}")
            else:
                win_w, win_h = settings['window_width'], settings['window_height']
                x = max(0, SCREEN_WIDTH - win_w - 10)
                y = 10
                options.add_argument(f"--window-position={x},{y}")
                options.add_argument(f"--window-size={win_w},{win_h}")

            # Chrome supplies its own User-Agent and Client Hints at launch.
            
            # The proxy server is a Chrome flag, independent of the authentication worker.
            options.add_argument(f"--proxy-server={proxy.server}")
            options.add_argument('--proxy-bypass-list=<-loopback>')
            extension_dir = prepare_proxy_extension(proxy)
            extension_paths.append(Path(extension_dir.name))
            if extension_paths:
                for argument in list(options.arguments):
                    if argument.startswith('--load-extension='):
                        options.arguments.remove(argument)
                options.add_argument('--load-extension=' + ','.join(str(p) for p in extension_paths))
            
            driver_service = Service(str(driver_path))
            
            browser = await loop.run_in_executor(None, lambda: webdriver.Chrome(service=driver_service, options=options))
            browser._xg_proxy_extension = extension_dir
            browser._xg_proxy_bridge = proxy_bridge
            browser_lock(browser)
            track_browser_process(browser)
            if not credentials.headless:
                attach_identity(browser,identity)
            browser._xg_proxy_ip = await loop.run_in_executor(None,verify_browser_proxy,browser,proxy)
            proxy_verified = True
            await loop.run_in_executor(None, prepare_workspace, browser)
            browser.set_script_timeout(10)
            try:
                await loop.run_in_executor(None,ensure_search_engine,browser,Path(user_profile))
            except SearchConfigurationError:
                logging.getLogger(__name__).warning('Optional search-provider repair was unavailable; opening profile normally')

            # PID chromedriver — по нему hard_close_browser добивает дерево процессов chrome
            try:
                browser._xg_pid = driver_service.process.pid
            except Exception:
                browser._xg_pid = None

            # Keep compatibility scripts aligned with this Chrome process. When
            # WebGL details are unavailable, leave the native browser values alone.
            try:
                native = await loop.run_in_executor(None, lambda: browser.execute_script("""
                const canvas = document.createElement('canvas');
                const gl = canvas.getContext('webgl');
                const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
                return {
                    ua: navigator.userAgent, languages: navigator.languages,
                    vendor: navigator.vendor, platform: navigator.platform,
                    webglVendor: info ? gl.getParameter(info.UNMASKED_VENDOR_WEBGL) : null,
                    renderer: info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : null
                };
                """)) or {}
            except Exception:
                native = {}
            if native.get('webglVendor') and native.get('renderer'):
                await loop.run_in_executor(None, lambda: stealth(
                    browser, user_agent=native['ua'],
                    languages=native.get('languages') or ['en-US', 'en'],
                    vendor=native.get('vendor') or 'Google Inc.',
                    platform=native.get('platform'),
                    webgl_vendor=native['webglVendor'], renderer=native['renderer'],
                    fix_hairline=True, emulate_print_media=True, await_for_load=False))
            if settings['browser_timezone']:
                try:
                    await loop.run_in_executor(None, lambda: browser.execute_cdp_cmd(
                        'Emulation.setTimezoneOverride', {'timezoneId': settings['browser_timezone']}))
                except Exception as exc:
                    raise ProfileSettingsError(f"Chrome rejected timezone {settings['browser_timezone']}") from exc
            if settings['browser_language']:
                try:
                    await loop.run_in_executor(None, lambda: browser.execute_cdp_cmd(
                        'Emulation.setLocaleOverride', {'locale': settings['browser_language'].replace('-', '_')}))
                except Exception as exc:
                    raise ProfileSettingsError(f"Chrome rejected language {settings['browser_language']}") from exc
            
            browser.set_page_load_timeout(45)
            browser.set_script_timeout(30)
            browser._xg_browser_version = str(browser.capabilities.get('browserVersion', ''))
            browser._xg_user_agent = await loop.run_in_executor(
                None, lambda: browser.execute_script('return navigator.userAgent'))
            major = browser._xg_browser_version.split('.')[0]
            if major.isdigit() and f'Chrome/{major}.' not in browser._xg_user_agent:
                raise ProfileSettingsError('Browser User-Agent does not match the installed Chrome version')
            await loop.run_in_executor(None, apply_session, browser, self.config, credentials.username)
            return browser
            
        except Exception as exc:
            if browser is not None:
                await loop.run_in_executor(None, hard_close_browser, browser)
            elif extension_dir is not None:
                extension_dir.cleanup()
            if proxy_bridge is not None:
                proxy_bridge.cleanup()
            if isinstance(exc, (ProxyCheckError, ProfileSettingsError, BrowserPolicyError, SearchConfigurationError)):
                raise
            if browser is None or proxy_verified:
                detail = safe_launch_error(exc, vars(credentials))
                raise ProfileSettingsError('Chrome could not start: ' + detail) from None
            raise ProxyCheckError("Chrome could not complete proxy IP verification.") from None
