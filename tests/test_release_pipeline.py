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


class ReleaseHistoryBuildTests(unittest.TestCase):
    def test_prepare_bundles_all_published_pages_with_the_new_version(self):
        import json
        import tempfile
        from unittest.mock import Mock, patch
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            static = root / 'xgenius/web/static'
            static.mkdir(parents=True)
            (root / 'xgenius/__init__.py').write_text('__version__ = "2026.11.27.4"\n', encoding='utf-8')
            session = Mock()
            session.__enter__ = Mock(return_value=session)
            session.__exit__ = Mock(return_value=False)
            session.headers = {}
            latest = {'tag_name': 'v2026.11.27.3'}
            first = [{'tag_name': f'v2026.1.1.{index}', 'body': f'Change {index}'} for index in range(100)]
            second = [{'tag_name': 'v2026.11.27.3', 'body': 'Last published change'}]
            def response(value):
                result = Mock()
                result.json.return_value = value
                return result
            session.get.side_effect = [response(latest), response(first), response(second)]
            with patch.object(release, 'ROOT', root), patch.object(release, '__version__', '2026.11.27.4'), \
                    patch('requests.Session', return_value=session), \
                    patch.dict('os.environ', {'GITHUB_REPOSITORY': 'example/XAnty', 'GITHUB_OUTPUT': str(root / 'output')}):
                release.prepare()
            history = json.loads((static / 'release-history.json').read_text(encoding='utf-8'))
            self.assertEqual(len(history), 101)
            self.assertEqual(history[0]['version'], '2026.11.27.3')
            self.assertEqual(session.get.call_args_list[1].kwargs['params']['page'], 1)
            self.assertEqual(session.get.call_args_list[2].kwargs['params']['page'], 2)
            self.assertIn('version=2026.11.27.4', (root / 'output').read_text())
