"""UI preferences persist across launches even when the local server port changes."""
import json
import os
import tempfile

from xgenius.config import application_home
from xgenius.profile_metadata import COLUMNS, DEFAULT_COLUMNS, retention_days


def valid_columns(value):
    return (isinstance(value, list) and all(isinstance(c, str) and c in COLUMNS for c in value)
            and len(set(value)) == len(value) and 'name' in value)


def read_preferences():
    result = {'language': 'ru', 'theme': 'dark', 'columns': list(DEFAULT_COLUMNS), 'trash_retention_days': 30,
              'window_frames': True, 'session_autosave': True, 'autosave_seconds': 60}
    try:
        data = json.loads((application_home() / 'preferences.json').read_text(encoding='utf-8'))
        if data.get('language') in ('ru', 'en', 'uk'):
            result['language'] = data['language']
        if data.get('theme') in ('dark', 'light'):
            result['theme'] = data['theme']
        if valid_columns(data.get('columns')):
            result['columns'] = data['columns']
        days = data.get('trash_retention_days')
        if type(days) is int and 0 <= days <= 3650:
            result['trash_retention_days'] = days
        for key in ('window_frames','session_autosave'):
            if type(data.get(key)) is bool:
                result[key] = data[key]
        if type(data.get('autosave_seconds')) is int and 30 <= data['autosave_seconds'] <= 3600:
            result['autosave_seconds'] = data['autosave_seconds']
    except (OSError, ValueError, AttributeError):
        pass
    return result


def save_preferences(data):
    if not isinstance(data, dict) or set(data) - {'language', 'theme', 'columns', 'trash_retention_days',
                                               'window_frames','session_autosave','autosave_seconds'}:
        raise ValueError('Invalid interface preferences')
    result = read_preferences()
    if 'language' in data and data['language'] not in ('ru', 'en', 'uk'):
        raise ValueError('Unsupported interface language')
    if 'theme' in data and data['theme'] not in ('dark', 'light'):
        raise ValueError('Unsupported interface theme')
    if 'columns' in data and not valid_columns(data['columns']):
        raise ValueError('Invalid table columns')
    if 'trash_retention_days' in data:
        retention_days(data['trash_retention_days'])
    for key in ('window_frames','session_autosave'):
        if key in data and type(data[key]) is not bool:
            raise ValueError('Invalid browser preference')
    if 'autosave_seconds' in data and (type(data['autosave_seconds']) is not int or not 30 <= data['autosave_seconds'] <= 3600):
        raise ValueError('Autosave interval must be 30 to 3600 seconds')
    result.update(data)
    root = application_home()
    root.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=root, delete=False) as stream:
            temporary = stream.name
            json.dump(result, stream)
        os.replace(temporary, root / 'preferences.json')
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
    return result
