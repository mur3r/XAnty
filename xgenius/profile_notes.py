"""Read Dolphin note objects and legacy stringified objects as plain text."""
import ast
import json
from html.parser import HTMLParser


_FIELDS = {'content', 'color', 'icon', 'style'}


class _NoteText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        elif not self.hidden and tag in ('br', 'p', 'div', 'li'):
            self.parts.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        elif not self.hidden and tag in ('p', 'div', 'li'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def note_text(value):
    if isinstance(value, str):
        candidate = value.strip()
        if not (candidate.startswith('{') and candidate.endswith('}') and len(candidate) <= 65536):
            return value
        parsed = None
        for parse in (json.loads, ast.literal_eval):
            try:
                parsed = parse(candidate)
                break
            except (ValueError, SyntaxError, RecursionError):
                continue
        if not isinstance(parsed, dict) or 'content' not in parsed or not parsed.keys() <= _FIELDS:
            return value
        value = parsed
    if not isinstance(value, dict):
        return '' if value is None else str(value)
    content = value.get('content')
    if not isinstance(content, str):
        return ''
    parser = _NoteText()
    parser.feed(content)
    parser.close()
    return '\n'.join(line.strip() for line in ''.join(parser.parts).splitlines() if line.strip()).strip()
