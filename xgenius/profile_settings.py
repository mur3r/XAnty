"""Validated, stable browser preferences for an individual Chrome profile."""

import re

from xgenius.browser_policy import BrowserPolicyError, policy_settings


class ProfileSettingsError(ValueError):
    pass


_LANGUAGE = re.compile(r'^[a-z]{2,3}(?:-[A-Z]{2})?$')
_TIMEZONE = re.compile(r'^(?:UTC|[A-Za-z][A-Za-z0-9_+-]*(?:/[A-Za-z0-9_+-]+)+)$')


def workspace_settings(data):
    try:
        policy = policy_settings(data)
    except BrowserPolicyError as exc:
        raise ProfileSettingsError(str(exc)) from exc
    restore = data.get('restore_tabs', True)
    extension = data.get('extension_set', '') or ''
    if type(restore) is not bool:
        raise ProfileSettingsError('restore_tabs must be a boolean')
    if not isinstance(extension,str) or (extension and not re.fullmatch(r'[a-f0-9]{32}',extension)):
        raise ProfileSettingsError('Invalid extension set')
    return {'restore_tabs':restore,'extension_set':extension, **policy}


def browser_settings(data: dict) -> dict:
    language = data.get('browser_language', '') or ''
    timezone = data.get('browser_timezone', '') or ''
    if not isinstance(language, str) or (language and not _LANGUAGE.fullmatch(language)):
        raise ProfileSettingsError('Language must look like en-US, uk-UA or en')
    if not isinstance(timezone, str) or (timezone and not _TIMEZONE.fullmatch(timezone)):
        raise ProfileSettingsError('Timezone must be an IANA name such as Europe/Kyiv or UTC')
    dimensions = []
    for key, minimum, maximum, default in (('window_width', 800, 3840, 1024),
                                           ('window_height', 600, 2160, 768)):
        value = data.get(key, default)
        if isinstance(value, bool) or not str(value).isdigit():
            raise ProfileSettingsError(f'{key} must be a number from {minimum} to {maximum}')
        number = int(value)
        if number < minimum or number > maximum:
            raise ProfileSettingsError(f'{key} must be from {minimum} to {maximum}')
        dimensions.append(number)
    return {'browser_language': language, 'browser_timezone': timezone,
            'window_width': dimensions[0], 'window_height': dimensions[1]}
