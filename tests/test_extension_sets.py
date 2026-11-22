"""Managed extension presets stay local, safe, and portable with their profile."""
import base64
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


module_path = Path(__file__).resolve().parents[1] / 'xgenius' / 'extension_sets.py'
spec = importlib.util.spec_from_file_location('xanty_extension_sets', module_path)
extensions = importlib.util.module_from_spec(spec)
spec.loader.exec_module(extensions)


class ExtensionSetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = SimpleNamespace(base_dir=self.root / 'data')
        self.config.base_dir.mkdir()
        self.store = extensions.ExtensionSetStore(self.config)
        self.profile = self.root / 'profile'

    def unpacked(self, folder='source', **manifest):
        root = self.root / folder
        root.mkdir(parents=True, exist_ok=True)
        data = {'manifest_version': 3, 'name': 'Local helper', 'version': '1.2.3',
                'background': {'service_worker': 'worker.js'}}
        data.update(manifest)
        (root / 'manifest.json').write_text(json.dumps(data), encoding='utf-8')
        (root / 'worker.js').write_text('globalThis.started = true;', encoding='utf-8')
        return root

    def save(self, source=None, **kwargs):
        return self.store.save('Work', [str(source or self.unpacked())], **kwargs)

    def test_save_copies_files_and_list_returns_only_public_metadata(self):
        source = self.unpacked()
        preset = self.save(source)
        self.assertEqual(set(preset), {'id', 'name', 'extensions'})
        self.assertEqual(preset['name'], 'Work')
        self.assertEqual(set(preset['extensions'][0]), {'name', 'version', 'id'})
        self.assertEqual(preset['extensions'][0]['name'], 'Local helper')
        self.assertRegex(preset['extensions'][0]['id'], '^[a-p]{32}$')
        shutil.rmtree(source)
        self.assertEqual(extensions.ExtensionSetStore(self.config).list(), [preset])
        loaded = self.store.materialize(preset['id'], self.profile)
        self.assertEqual(len(loaded), 1)
        self.assertEqual((loaded[0] / 'worker.js').read_text(), 'globalThis.started = true;')
        self.assertTrue(loaded[0].is_relative_to(self.profile / 'XAntyExtensions' / preset['id']))

    def test_generated_key_is_not_written_to_source_and_survives_update_and_transfer(self):
        source = self.unpacked()
        preset = self.save(source)
        original = self.store.materialize(preset['id'], self.profile)[0]
        key = json.loads((original / 'manifest.json').read_text())['key']
        self.assertNotIn('key', json.loads((source / 'manifest.json').read_text()))
        self.assertTrue(serialization.load_der_public_key(base64.b64decode(key)))
        (source / 'worker.js').write_text('updated')
        updated = self.store.save('Renamed', [str(source)], preset['id'])
        self.assertEqual(updated['extensions'][0]['id'], preset['extensions'][0]['id'])
        self.store.materialize(updated['id'], self.profile)
        moved = self.root / 'other-computer' / 'profile'
        shutil.copytree(self.profile, moved)
        self.store.delete(updated['id'])
        loaded = extensions.ExtensionSetStore(SimpleNamespace(base_dir=self.root / 'empty')).materialize(updated['id'], moved)
        self.assertEqual(len(loaded), 1)
        self.assertEqual((loaded[0] / 'worker.js').read_text(), 'updated')
        self.assertEqual(json.loads((loaded[0] / 'manifest.json').read_text())['key'], key)

    def test_existing_manifest_key_is_preserved(self):
        key = base64.b64encode(rsa.generate_private_key(public_exponent=65537, key_size=2048)
                               .public_key().public_bytes(serialization.Encoding.DER,
                                                          serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        preset = self.save(self.unpacked(key=key))
        loaded = self.store.materialize(preset['id'], self.profile)[0]
        self.assertEqual(json.loads((loaded / 'manifest.json').read_text())['key'], key)

    def test_duplicate_sources_and_extension_ids_are_rejected(self):
        source = self.unpacked()
        with self.assertRaises(extensions.ExtensionSetError):
            self.store.save('Work', [str(source), str(source)])
        first = self.save(source)
        key = json.loads((self.store.materialize(first['id'], self.profile)[0] / 'manifest.json').read_text())['key']
        one = self.unpacked('one', key=key)
        two = self.unpacked('two', key=key)
        with self.assertRaises(extensions.ExtensionSetError):
            self.store.save('Duplicate IDs', [str(one), str(two)])
        self.assertEqual(self.store.list(), [first])

    def test_invalid_names_ids_and_directory_arguments_cannot_escape_store(self):
        source = self.unpacked()
        for name in ('', ' ', 'x' * 129, 'line\nbreak'):
            with self.subTest(name=name), self.assertRaises(extensions.ExtensionSetError):
                self.store.save(name, [str(source)])
        for invalid in ('../outside', '/outside', 'x/y', 'x\\y', 'missing', ''):
            with self.subTest(preset=invalid), self.assertRaises(extensions.ExtensionSetError):
                self.store.delete(invalid)
        for paths in ([], 'source', [str(source), 1], [str(source / '..' / source.name)]):
            with self.subTest(paths=paths), self.assertRaises(extensions.ExtensionSetError):
                self.store.save('Work', paths)
        self.assertEqual(self.store.list(), [])

    def test_malformed_manifests_and_unsupported_manifest_v2_are_rejected(self):
        source = self.unpacked()
        invalid = [[], {}, {'manifest_version': True, 'name': 'Name', 'version': '1'},
                   {'manifest_version': 2, 'name': 'Old', 'version': '1'},
                   {'manifest_version': 3, 'name': '', 'version': '1'},
                   {'manifest_version': 3, 'name': 'Bad', 'version': '01.2'},
                   {'manifest_version': 3, 'name': 'Bad', 'version': '0'},
                   {'manifest_version': 3, 'name': 'Bad', 'version': '1', 'key': 'not-a-key'}]
        for data in invalid:
            (source / 'manifest.json').write_text(json.dumps(data))
            with self.subTest(manifest=data), self.assertRaises(extensions.ExtensionSetError):
                self.save(source)
        for text in ('{', '{"name":"one","name":"two","manifest_version":3,"version":"1"}'):
            (source / 'manifest.json').write_text(text)
            with self.assertRaises(extensions.ExtensionSetError):
                self.save(source)
        self.assertEqual(self.store.list(), [])

    def test_manifest_resource_traversal_and_missing_resources_are_rejected(self):
        for resource in ('../outside.js', '/outside.js', 'C:/outside.js', 'one\\two.js', 'missing.js'):
            source = self.unpacked(background={'service_worker': resource})
            with self.subTest(resource=resource), self.assertRaises(extensions.ExtensionSetError):
                self.save(source)
        self.assertEqual(self.store.list(), [])

    def test_nested_symlink_and_linked_source_are_rejected(self):
        source = self.unpacked()
        outside = self.root / 'outside'
        outside.mkdir()
        link = source / 'escape'
        try:
            link.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Symbolic link creation is unavailable')
        with self.assertRaises(extensions.ExtensionSetError):
            self.save(source)
        linked = self.root / 'linked'
        linked.symlink_to(source, target_is_directory=True)
        with self.assertRaises(extensions.ExtensionSetError):
            self.save(linked)
        self.assertEqual(self.store.list(), [])

    def test_windows_junction_source_is_rejected(self):
        if os.name != 'nt':
            self.skipTest('Windows junction test')
        import subprocess
        source = self.unpacked()
        junction = self.root / 'junction'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(source)], capture_output=True)
        if result.returncode:
            self.skipTest('Junction creation is unavailable')
        self.addCleanup(lambda: junction.rmdir() if junction.exists() else None)
        with self.assertRaises(extensions.ExtensionSetError):
            self.save(junction)

    def test_nested_junction_is_rejected_and_existing_profile_snapshot_is_unchanged(self):
        if os.name != 'nt':
            self.skipTest('Windows junction test')
        import subprocess
        preset = self.save()
        loaded = self.store.materialize(preset['id'], self.profile)
        outside = self.root / 'outside'
        outside.mkdir()
        marker = outside / 'keep.txt'
        marker.write_text('keep')
        junction = loaded[0] / 'escape'
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], capture_output=True)
        if result.returncode:
            self.skipTest('Junction creation is unavailable')
        # The production code must refuse this tree before moving or deleting it.
        with self.assertRaises(extensions.ExtensionSetError):
            self.store.materialize(preset['id'], self.profile)
        self.assertTrue(junction.exists())
        self.assertEqual(marker.read_text(), 'keep')
        junction.rmdir()
        self.store.delete(preset['id'])
        self.assertEqual(self.store.materialize(preset['id'], self.profile), loaded)

    def test_materialize_copy_failure_retains_previous_snapshot(self):
        first = self.save(self.unpacked('first'))
        second = self.store.save('Second', [str(self.unpacked('second'))])
        loaded = self.store.materialize(first['id'], self.profile)
        self.store.delete(first['id'])
        with patch.object(extensions.shutil, 'copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(extensions.ExtensionSetError):
                self.store.materialize(second['id'], self.profile)
        self.assertEqual(self.store.materialize(first['id'], self.profile), loaded)
        self.assertEqual([path.name for path in self.profile.iterdir()], ['XAntyExtensions'])

    def test_copy_failure_leaves_previous_preset_intact_and_cleans_staging(self):
        source = self.unpacked()
        preset = self.save(source)
        with patch.object(extensions.shutil, 'copyfileobj', side_effect=OSError('disk full')):
            with self.assertRaises(extensions.ExtensionSetError):
                self.store.save('Changed', [str(source)], preset['id'])
        self.assertEqual(self.store.list(), [preset])
        self.assertEqual([p.name for p in (self.config.base_dir / 'extension_sets').iterdir()], [preset['id']])

    def test_publication_failure_restores_previous_preset(self):
        source = self.unpacked()
        preset = self.save(source)
        real_replace = extensions.os.replace

        def fail_publication(source_path, target_path):
            if Path(source_path).name.startswith('.stage-'):
                raise OSError('publication failed')
            return real_replace(source_path, target_path)

        with patch.object(extensions.os, 'replace', side_effect=fail_publication):
            with self.assertRaises(extensions.ExtensionSetError):
                self.store.save('Changed', [str(source)], preset['id'])
        self.assertEqual(self.store.list(), [preset])
        self.assertEqual([p.name for p in (self.config.base_dir / 'extension_sets').iterdir()], [preset['id']])

    def test_selecting_another_set_replaces_profile_snapshot_without_touching_other_data(self):
        first = self.save(self.unpacked('first'))
        second = self.store.save('Second', [str(self.unpacked('second', name='Second helper'))])
        self.profile.mkdir()
        marker = self.profile / 'Preferences'
        marker.write_text('keep')
        self.store.materialize(first['id'], self.profile)
        loaded = self.store.materialize(second['id'], self.profile)
        self.store.delete(second['id'])
        self.assertEqual(self.store.materialize(second['id'], self.profile), loaded)
        self.assertFalse((self.profile / 'XAntyExtensions' / first['id']).exists())
        self.assertEqual(marker.read_text(), 'keep')

    def test_transferred_snapshot_rejects_tampered_metadata_and_missing_global_preset_falls_back(self):
        preset = self.save()
        loaded = self.store.materialize(preset['id'], self.profile)
        self.store.delete(preset['id'])
        self.assertEqual(self.store.materialize(preset['id'], self.profile), loaded)
        (loaded[0] / 'manifest.json').write_text('{}')
        with self.assertRaises(extensions.ExtensionSetError):
            self.store.materialize(preset['id'], self.profile)

    def test_deselect_disables_loading_and_preserves_portable_files_for_reselection(self):
        preset = self.save()
        loaded = self.store.materialize(preset['id'], self.profile)
        manifest = (loaded[0] / 'manifest.json').read_bytes()
        self.store.delete(preset['id'])
        self.assertEqual(self.store.materialize('', self.profile), [])
        self.assertEqual((loaded[0] / 'manifest.json').read_bytes(), manifest)
        self.assertEqual(self.store.materialize(preset['id'], self.profile), loaded)

    def test_delete_removes_only_global_preset_and_empty_profile_returns_no_extensions(self):
        preset = self.save()
        loaded = self.store.materialize(preset['id'], self.profile)
        self.store.delete(preset['id'])
        self.assertEqual(self.store.list(), [])
        self.assertTrue((loaded[0] / 'manifest.json').is_file())
        self.assertEqual(self.store.materialize('', self.root / 'new-profile'), [])


if __name__ == '__main__':
    unittest.main()
