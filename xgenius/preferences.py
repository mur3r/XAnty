"""UI preferences persist across launches even when the local server port changes."""
import json
import os
import tempfile

from xgenius.config import application_home


def read_preferences():
    result = {'language': 'ru', 'theme': 'dark'}
    try:
        data = json.loads((application_home() / 'preferences.json').read_text(encoding='utf-8'))
        if data.get('language') in ('ru', 'en', 'uk'):
            result['language'] = data['language']
        if data.get('theme') in ('dark', 'light'):
            result['theme'] = data['theme']
    except (OSError, ValueError, AttributeError):
        pass
    return result


def save_preferences(data):
    if not isinstance(data, dict) or set(data) - {'language', 'theme'}:
        raise ValueError('Invalid interface preferences')
    result = read_preferences()
    if 'language' in data and data['language'] not in ('ru', 'en', 'uk'):
        raise ValueError('Unsupported interface language')
    if 'theme' in data and data['theme'] not in ('dark', 'light'):
        raise ValueError('Unsupported interface theme')
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
