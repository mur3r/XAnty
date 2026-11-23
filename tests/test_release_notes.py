import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from aiohttp.test_utils import TestClient, TestServer

from xgenius import __version__
from xgenius.release_notes import ReleaseNotes, current_notes
from xgenius.web.server import WebApp


class ReleaseNotesTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.home = patch('xgenius.release_notes.application_home', return_value=Path(self.directory.name))
        self.home.start()
        self.addCleanup(self.home.stop)

    def test_closing_notes_persists_across_restarts_and_the_next_update_shows_again(self):
        notes = ReleaseNotes('example/XAnty')
        self.assertTrue(notes.snapshot()['pending'])
        self.assertEqual(notes.snapshot()['notes'], current_notes())
        notes.acknowledge(__version__)
        self.assertFalse(ReleaseNotes('example/XAnty').snapshot()['pending'])
        with patch('xgenius.release_notes.__version__', '2099.1.1.1'):
            self.assertTrue(ReleaseNotes('example/XAnty').snapshot()['pending'])

    def test_bad_or_missing_acknowledgement_never_hides_notes(self):
        notes = ReleaseNotes('')
        notes.acknowledgement.parent.mkdir(parents=True)
        for content in ('broken', 'null', '[]', '{}'):
            notes.acknowledgement.write_text(content, encoding='utf-8')
            self.assertTrue(notes.snapshot()['pending'])
        with self.assertRaises(ValueError):
            notes.acknowledge('2099.1.1.1')

    def test_failed_save_preserves_the_previous_acknowledgement(self):
        notes = ReleaseNotes('')
        notes.acknowledge(__version__)
        original = notes.acknowledgement.read_bytes()
        with patch('xgenius.release_notes.os.replace', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                notes.acknowledge(__version__)
        self.assertEqual(notes.acknowledgement.read_bytes(), original)
        self.assertEqual(list(notes.acknowledgement.parent.iterdir()), [notes.acknowledgement])


class ReleaseNotesApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.home = patch('xgenius.config.os.environ', {'LOCALAPPDATA': self.directory.name})
        self.home.start()
        self.app = WebApp(asyncio.get_running_loop())
        self.client = TestClient(TestServer(self.app.build()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.home.stop()
        self.directory.cleanup()

    async def test_reads_do_not_mark_notes_seen_and_close_endpoint_survives_a_new_server(self):
        for _ in range(2):
            response = await self.client.get('/api/updates')
            self.assertTrue((await response.json())['installed_release']['pending'])
        response = await self.client.post('/api/updates/notes/seen', json={'version': 'wrong'})
        self.assertEqual(response.status, 400)
        response = await self.client.post('/api/updates/notes/seen', json={'version': __version__})
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())['installed_release']['pending'])
        restarted = WebApp(asyncio.get_running_loop())
        self.assertFalse(restarted.updates.snapshot()['installed_release']['pending'])

    async def test_open_maximizes_only_the_desktop_and_keeps_notes_pending(self):
        window = Mock()
        with patch.dict('sys.modules', {'webview': SimpleNamespace(windows=[window])}):
            response = await self.client.post('/api/updates/notes/open', json={})
            self.assertEqual(response.status, 200)
            window.maximize.assert_not_called()
            self.app.desktop_mode = True
            response = await self.client.post('/api/updates/notes/open', json={})
            self.assertEqual(response.status, 200)
            window.maximize.assert_called_once()
        self.assertTrue(self.app.updates.snapshot()['installed_release']['pending'])

