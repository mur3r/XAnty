import copy
import json
import unittest

from xgenius.dolphin_import import map_profile
from xgenius.profile_metadata import migrate, replace_accounts
from xgenius.profile_notes import note_text


class ProfileNotesTests(unittest.TestCase):
    def test_empty_dolphin_note_and_previous_python_string_show_no_metadata(self):
        note = {'content': None, 'color': 'blue', 'icon': None, 'style': 'text'}
        for value in (None, '', note, str(note), json.dumps(note), {**note, 'content': '<p><br></p>'}):
            with self.subTest(value=value):
                self.assertEqual(note_text(value), '')

    def test_rich_note_keeps_its_text_and_line_breaks_without_styles(self):
        note = {'content': '<p>First &amp; second</p><p><b>Next line</b><br>Last</p>', 'color': 'blue'}
        for value in (note, str(note), json.dumps(note)):
            self.assertEqual(note_text(value), 'First & second\nNext line\nLast')
        self.assertEqual(note_text({'content': '<style>hidden</style>Note<script>hidden</script>'}), 'Note')

    def test_ordinary_notes_and_unrelated_json_remain_unchanged(self):
        for value in ('My note\n  preserve spaces', 'a < b', '{unfinished',
                      '{"content": "example", "meaning": "documentation"}', '<b>literal note</b>'):
            self.assertEqual(note_text(value), value)

    def test_dolphin_import_extracts_only_note_content(self):
        for value, expected in (({'content': None, 'color': 'blue'}, ''),
                                ({'content': '<p>Imported note</p>', 'style': 'text'}, 'Imported note')):
            account, _ = map_profile({'id': 16, 'name': 'example', 'notes': value})
            self.assertEqual(account['notes'], expected)

    def test_startup_migration_and_package_copies_repair_legacy_notes(self):
        legacy = str({'content': None, 'color': 'blue', 'icon': None, 'style': 'text'})
        document = {'accounts': [{'username': 'alice', 'notes': legacy}],
                    'trash': [{'username': 'bob', 'notes': "{'content': '<p>Keep me</p>', 'color': 'blue'}"}]}
        migrated = migrate(copy.deepcopy(document))
        self.assertEqual(migrated['accounts'][0]['notes'], '')
        self.assertEqual(migrated['trash'][0]['notes'], 'Keep me')
        copied = replace_accounts(migrated, [{'username': 'alice', 'notes': legacy},
                                            {'username': 'copied', 'notes': {'content': 'New note'}}])
        self.assertEqual([a['notes'] for a in copied['accounts']], ['', 'New note'])
