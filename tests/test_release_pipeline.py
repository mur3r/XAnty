"""Repeated source uploads must generate strictly newer release versions."""
import importlib.util
from pathlib import Path
import unittest
from xgenius.updates import UpdateError

path = Path(__file__).resolve().parents[1] / 'tools/prepare_release.py'
spec = importlib.util.spec_from_file_location('prepare_release', path)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseVersionTests(unittest.TestCase):
    def test_same_source_version_advances_after_every_published_build(self):
        self.assertEqual(release.next_version('2026.11.22.9', 'v2026.11.22.9'), '2026.11.22.10')
        self.assertEqual(release.next_version('2026.11.22.9', 'v2026.11.22.10'), '2026.11.22.11')

    def test_new_source_date_and_first_release_keep_the_source_version(self):
        self.assertEqual(release.next_version('2026.11.23.1', 'v2026.11.22.99'), '2026.11.23.1')
        self.assertEqual(release.next_version('2026.11.22.9'), '2026.11.22.9')

    def test_bad_release_tag_stops_publication(self):
        with self.assertRaises(UpdateError):
            release.next_version('2026.11.22.9', 'latest')
