"""Native Windows Chromium User-Agent previews without inventing browser versions."""
from functools import lru_cache
from pathlib import Path
import re

from xgenius.profile_settings import ProfileSettingsError

_PATTERN = re.compile(r'^Mozilla/5\.0 \(Windows NT 10\.0; Win64; x64\) AppleWebKit/537\.36 \(KHTML, like Gecko\) Chrome/(\d+)\.0\.0\.0 Safari/537\.36$')


def generate_user_agent(version):
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+\.\d+', version):
        raise ProfileSettingsError('The Chromium version is unavailable. Install or select a compatible browser first.')
    major = int(version.split('.')[0])
    if major < 107:
        raise ProfileSettingsError('User-Agent generation requires Chromium 107 or newer.')
    return f'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36'


@lru_cache(maxsize=32)
def _binary_version(path, size, modified):
    from xgenius.chromium_versions import _file_version
    return _file_version(Path(path))


def browser_identity(config):
    try:
        path = Path(config.chrome_path).resolve()
        info = path.stat()
        version = _binary_version(str(path), info.st_size, info.st_mtime_ns)
        return {'available': True, 'user_agent': generate_user_agent(version),
                'browser_version': version, 'source': 'generated', 'error': ''}
    except (AttributeError, OSError, TypeError, ValueError):
        return {'available': False, 'user_agent': '', 'browser_version': '', 'source': 'generated',
                'error': 'The Chromium version is unavailable. Install or select a compatible browser first.'}


def validate_user_agent(value, version):
    if not isinstance(value, str) or not _PATTERN.fullmatch(value.strip()):
        raise ProfileSettingsError('Use a standard Windows Chromium User-Agent generated for the selected browser.')
    value = value.strip()
    if value != generate_user_agent(version):
        raise ProfileSettingsError('User-Agent does not match the selected Chromium. Generate it again or select the matching browser version.')
    return value


def user_agent_settings(data, config):
    mode = data.get('user_agent_mode', 'auto')
    if mode not in ('auto', 'manual'):
        raise ProfileSettingsError('Choose automatic or manual User-Agent mode.')
    value = data.get('user_agent') or ''
    if not isinstance(value, str) or len(value) > 2048 or any(ord(c) < 32 for c in value):
        raise ProfileSettingsError('Use a standard Windows Chromium User-Agent generated for the selected browser.')
    if mode == 'manual':
        identity = browser_identity(config)
        if not identity['available']:
            raise ProfileSettingsError(identity['error'])
        value = validate_user_agent(value, identity['browser_version'])
    return {'user_agent_mode': mode, 'user_agent': value.strip()}


def profile_identity(account, generated):
    result = dict(generated)
    result['mode'] = account.get('user_agent_mode', 'auto')
    if result['mode'] == 'manual' and result['available']:
        try:
            result['user_agent'] = validate_user_agent(account.get('user_agent'), result['browser_version'])
        except ProfileSettingsError as exc:
            result.update(available=False, user_agent='', error=str(exc))
    return result


def apply_native_stealth(browser, stealth, **options):
    # selenium-stealth otherwise overrides the UA without User-Agent metadata,
    # suppressing native high-entropy Client Hints. Preserve Chromium's identity.
    original = browser.execute_cdp_cmd
    def command(cmd, cmd_args):
        if cmd in ('Network.setUserAgentOverride', 'Emulation.setUserAgentOverride'):
            return {}
        return original(cmd, cmd_args)
    browser.execute_cdp_cmd = command
    try:
        return stealth(browser, **options)
    finally:
        browser.execute_cdp_cmd = original
