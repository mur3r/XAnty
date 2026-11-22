"""Real portable archives detect changed data before touching destination profiles."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipExtFile, ZipFile

from xgenius.config import Config
from xgenius.folders import FolderStore
from xgenius.profile_archive import ArchiveError, export_package, import_package, inspect_package


class Accounts:
    def __init__(self, rows=()):
        self.rows = copy.deepcopy(list(rows))

    def load_accounts(self):
        return copy.deepcopy(self.rows)

    def save_accounts(self, rows):
        self.rows = copy.deepcopy(rows)


class ArchiveIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = Config(self.root / 'source')
        self.target = Config(self.root / 'target')
        self.folders = FolderStore(self.target.base_dir / 'folders.json')
        self.folders.create('Existing')
        self.accounts = Accounts([{'username': 'existing', 'group': 'Existing'}])
        self.path = self.root / 'profiles.xanty'

    def members(self, version=2):
        manifest = {'format': 'xanty-profile-package', 'version': version,
                    'profiles': [{'key': '000000', 'account': {'username': 'alice', 'notes': 'original'}}],
                    'folders': ['Imported']}
        result = {'manifest.json': json.dumps(manifest).encode(),
                  'profiles/000000/cookies.json': b'[]',
                  'profiles/000000/browser/Default/Preferences': b'{"original":true}'}
        if version == 2:
            result['profiles/000000/tabs.json'] = b'{"version":1,"urls":["https://example.com/"],"active":0}'
        return result

    def write_package(self, members, descriptor=None):
        if descriptor is None and json.loads(members['manifest.json'])['version'] == 2:
            descriptor = {'algorithm': 'sha256', 'files': {
                name: hashlib.sha256(data).hexdigest() for name, data in members.items()}}
        with ZipFile(self.path, 'w', ZIP_STORED) as archive:
            for name, data in members.items():
                archive.writestr(name, data)
            if descriptor is not None:
                archive.writestr('checksums.json', json.dumps(descriptor))

    def assert_unchanged(self):
        self.assertEqual(self.accounts.rows, [{'username': 'existing', 'group': 'Existing'}])
        self.assertEqual(self.folders.list(), ['Existing'])
        self.assertEqual(list(self.target.browser_profiles_dir.iterdir()), [])
        self.assertFalse((self.target.base_dir / 'kook').exists())
        self.assertFalse(any(self.target.base_dir.glob('.xanty-import-*')))

    def test_export_hashes_metadata_every_payload_and_tab_snapshot(self):
        profile = self.source.get_profile_dir('alice')
        (profile / 'Preferences').write_bytes(b'large browser state' * 200000)
        tabs = self.source.base_dir / 'kook' / '@alice' / 'tabs.json'
        tabs.parent.mkdir(parents=True)
        tabs.write_bytes(b'{"version":1,"urls":["https://example.com/"],"active":0}')
        result = export_package(self.source, [{'username': 'alice', 'notes': 'metadata'}], self.path)
        self.assertEqual(result.get('integrity'), 'verified')
        with ZipFile(self.path) as archive:
            self.assertEqual(json.loads(archive.read('manifest.json'))['version'], 2)
            descriptor = json.loads(archive.read('checksums.json'))
            self.assertEqual(descriptor['algorithm'], 'sha256')
            expected_names = {'manifest.json', 'profiles/000000/cookies.json',
                              'profiles/000000/browser/Preferences', 'profiles/000000/tabs.json'}
            self.assertEqual(set(descriptor['files']), expected_names)
            for name in expected_names:
                self.assertEqual(descriptor['files'][name], hashlib.sha256(archive.read(name)).hexdigest())
        inspection = inspect_package(self.path)
        self.assertEqual(inspection.get('integrity'), 'verified')
        self.assertEqual(inspection.get('verified_files'), 4)
        self.assertEqual(inspection.get('warnings'), [])

    def test_changed_payload_and_manifest_metadata_reject_before_commit(self):
        for changed in ('manifest.json', 'profiles/000000/cookies.json',
                        'profiles/000000/browser/Default/Preferences', 'profiles/000000/tabs.json'):
            with self.subTest(changed=changed):
                members = self.members()
                descriptor = {'algorithm': 'sha256', 'files': {
                    name: hashlib.sha256(data).hexdigest() for name, data in members.items()}}
                members[changed] = members[changed].replace(b'original', b'modified') if b'original' in members[changed] else members[changed] + b' '
                self.write_package(members, descriptor)
                with self.assertRaisesRegex(ArchiveError, '(?i)integrity|checksum'):
                    inspect_package(self.path)
                with self.assertRaisesRegex(ArchiveError, '(?i)integrity|checksum'):
                    import_package(self.target, self.accounts, self.folders, self.path)
                self.assert_unchanged()

    def test_descriptor_requires_exact_payload_set(self):
        for changed in ('missing descriptor', 'missing entry', 'extra entry', 'missing payload', 'extra payload'):
            with self.subTest(changed=changed):
                members = self.members()
                descriptor = {'algorithm': 'sha256', 'files': {
                    name: hashlib.sha256(data).hexdigest() for name, data in members.items()}}
                if changed == 'missing entry':
                    del descriptor['files']['profiles/000000/tabs.json']
                elif changed == 'extra entry':
                    descriptor['files']['profiles/000000/browser/absent'] = '0' * 64
                elif changed == 'missing payload':
                    del members['profiles/000000/tabs.json']
                elif changed == 'extra payload':
                    members['profiles/000000/browser/extra'] = b'unlisted'
                self.write_package(members, descriptor)
                if changed == 'missing descriptor':
                    with ZipFile(self.path) as archive:
                        kept = {name: archive.read(name) for name in archive.namelist() if name != 'checksums.json'}
                    with ZipFile(self.path, 'w') as archive:
                        for name, data in kept.items():
                            archive.writestr(name, data)
                with self.assertRaisesRegex(ArchiveError, '(?i)integrity|checksum'):
                    import_package(self.target, self.accounts, self.folders, self.path)
                self.assert_unchanged()

    def test_legacy_package_reports_integrity_unavailable_on_inspect_and_import(self):
        self.write_package(self.members(version=1))
        inspection = inspect_package(self.path)
        self.assertEqual(inspection.get('integrity'), 'unavailable')
        self.assertTrue(any('integrity' in warning.lower() for warning in inspection.get('warnings', [])))
        result = import_package(self.target, self.accounts, self.folders, self.path)
        self.assertEqual(result.get('integrity'), 'unavailable')
        self.assertTrue(any('integrity' in warning.lower() for warning in result.get('warnings', [])))
        self.assertEqual(result['report'][0].get('integrity'), 'unavailable')
        self.assertTrue(result['report'][0].get('warnings'))

    def test_verified_tabs_restore_without_cookies_and_os_locks_are_discarded(self):
        members = self.members()
        for name in ('SingletonLock', 'Default/LOCK', 'lockfile', 'SingletonSocket'):
            members['profiles/000000/browser/' + name] = b'old operating-system lock'
        self.write_package(members)
        result = import_package(self.target, self.accounts, self.folders, self.path)
        self.assertEqual(result.get('integrity'), 'verified')
        self.assertEqual(result['report'][0].get('integrity'), 'verified')
        self.assertEqual((self.target.base_dir / 'kook' / '@alice' / 'tabs.json').read_bytes(),
                         members['profiles/000000/tabs.json'])
        restored = self.target.browser_profiles_dir / 'profile_alice'
        self.assertTrue((restored / 'Default' / 'Preferences').is_file())
        for name in ('SingletonLock', 'Default/LOCK', 'lockfile', 'SingletonSocket'):
            self.assertFalse((restored / name).exists())

    def test_skipped_profiles_are_still_verified(self):
        members = self.members()
        descriptor = {'algorithm': 'sha256', 'files': {
            name: hashlib.sha256(data).hexdigest() for name, data in members.items()}}
        members['profiles/000000/browser/Default/Preferences'] = b'tampered'
        self.write_package(members, descriptor)
        store = Accounts([{'username': 'alice'}])
        with self.assertRaisesRegex(ArchiveError, '(?i)integrity|checksum'):
            import_package(self.target, store, self.folders, self.path, duplicates='skip')
        self.assertEqual(store.rows, [{'username': 'alice'}])
        self.assertEqual(self.folders.list(), ['Existing'])

    def test_legacy_zip_crc_failure_is_reported_even_for_skipped_payloads(self):
        members = self.members(version=1)
        marker = b'unique-browser-state-for-crc-check'
        members['profiles/000000/browser/Default/Preferences'] = marker
        self.write_package(members)
        raw = self.path.read_bytes()
        self.path.write_bytes(raw.replace(marker, b'X' + marker[1:], 1))
        with self.assertRaisesRegex(ArchiveError, '(?i)integrity|corrupt|CRC'):
            inspect_package(self.path)
        with self.assertRaisesRegex(ArchiveError, '(?i)integrity|corrupt|CRC'):
            import_package(self.target, Accounts([{'username': 'alice'}]), self.folders,
                           self.path, duplicates='skip')
        self.assert_unchanged()

    def test_inspection_streams_large_payload_in_bounded_chunks(self):
        members = self.members()
        members['profiles/000000/browser/large.bin'] = b'x' * (3 * 1024 * 1024)
        self.write_package(members)
        original = ZipExtFile.read

        def bounded_read(stream, size=-1):
            if stream.name.endswith('large.bin'):
                self.assertGreater(size, 0, 'Large payload was read without a chunk limit')
                self.assertLessEqual(size, 1024 * 1024)
            return original(stream, size)

        with patch.object(ZipExtFile, 'read', bounded_read):
            result = inspect_package(self.path)
        self.assertEqual(result.get('verified_files'), 5)

    def test_damaged_compressed_payload_becomes_a_readable_integrity_error(self):
        members = self.members()
        self.write_package(members)
        with ZipFile(self.path) as original:
            contents = {name: original.read(name) for name in original.namelist()}
        with ZipFile(self.path, 'w', ZIP_DEFLATED) as archive:
            for name, data in contents.items():
                archive.writestr(name, data)
        with ZipFile(self.path) as archive:
            info = archive.getinfo('profiles/000000/browser/Default/Preferences')
            offset = info.header_offset + 30 + len(info.filename.encode()) + len(info.extra)
        raw = bytearray(self.path.read_bytes())
        raw[offset] = 0xff  # Invalid DEFLATE block type; not just a changed CRC.
        self.path.write_bytes(raw)
        with self.assertRaisesRegex(ArchiveError, '(?i)integrity|corrupt|CRC'):
            inspect_package(self.path)
        with self.assertRaisesRegex(ArchiveError, '(?i)integrity|corrupt|CRC'):
            import_package(self.target, self.accounts, self.folders, self.path)
        self.assert_unchanged()

    def test_malformed_checksum_descriptors_are_rejected_before_commit(self):
        members = self.members()
        valid_files = {name: hashlib.sha256(data).hexdigest() for name, data in members.items()}
        for descriptor in ({'algorithm': 'md5', 'files': valid_files},
                           {'algorithm': 'sha256', 'files': []},
                           {'algorithm': 'sha256', 'files': {**valid_files, 'manifest.json': 'invalid'}},
                           {'algorithm': 'sha256', 'files': {**valid_files, 'manifest.json': None}}):
            with self.subTest(descriptor=descriptor):
                self.write_package(members, descriptor)
                with self.assertRaisesRegex(ArchiveError, '(?i)integrity|checksum'):
                    import_package(self.target, self.accounts, self.folders, self.path)
                self.assert_unchanged()

    def test_duplicate_checksum_entries_are_rejected_before_commit(self):
        members = self.members()
        descriptor = '{"algorithm":"sha256","files":{' + ','.join(
            json.dumps(name) + ':' + json.dumps(hashlib.sha256(data).hexdigest())
            for name, data in members.items()) + ',"manifest.json":"' + '0' * 64 + '"}}'
        with ZipFile(self.path, 'w') as archive:
            for name, data in members.items():
                archive.writestr(name, data)
            archive.writestr('checksums.json', descriptor)
        with self.assertRaisesRegex(ArchiveError, '(?i)integrity|checksum'):
            import_package(self.target, self.accounts, self.folders, self.path)
        self.assert_unchanged()


if __name__ == '__main__':
    unittest.main()
