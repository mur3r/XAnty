"""Exercise the real streaming upload/download endpoints and persisted UI settings."""
import asyncio
import copy
import io
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zipfile import ZipFile

from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from xgenius.config import Config
from xgenius.folders import FolderStore
from xgenius.portable_session import store_session
from xgenius.web.actions import Actions
from xgenius.web.server import WebApp


class TransferApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = Config(self.root / 'data')
        self.accounts = [{'username': 'alice', 'profile_name': 'Alice profile', 'group': 'Work',
                          'proxy': 'http://u:private-proxy-password@proxy.test:80', 'auto_login': True,
                          'auth_token': 'private-x-token'}, {'username': 'bob', 'group': '', 'auto_login': False}]
        case = self

        class Manager:
            accounts = {}
            _data_lock = threading.RLock()

            def load_accounts(self):
                with self._data_lock:
                    return copy.deepcopy(case.accounts)

            def save_accounts(self, value):
                with self._data_lock:
                    case.accounts[:] = copy.deepcopy(value)

        async def shutdown():
            pass

        self.app = WebApp(asyncio.get_running_loop(), desktop_mode=True)
        self.app.engine = SimpleNamespace(config=self.config, account_manager=Manager(),
                                         folders=FolderStore(self.config.base_dir / 'folders.json'),
                                         loop=asyncio.get_running_loop(), notify=lambda: None, shutdown=shutdown,
                                         logger=SimpleNamespace(info=lambda *a: None, error=lambda *a: None),
                                         snapshot=lambda: {'phase': 'ready', 'accounts': [], 'version': 'qa'})
        self.app.actions = Actions(self.app.engine)
        store_session(self.config, 'alice', [{'name': 'auth_token', 'value': 'private-cookie', 'domain': '.x.com'}])
        self.preference_patch = patch('xgenius.preferences.application_home', return_value=self.root / 'prefs')
        self.preference_patch.start()
        self.client = TestClient(TestServer(self.app.build(), host='127.0.0.1'))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.app.shutdown()
        await self.client.close()
        self.preference_patch.stop()
        self.temp.cleanup()

    async def finish(self, job_id):
        for _ in range(300):
            response = await self.client.get('/api/jobs/' + job_id)
            job = await response.json()
            if job['status'] != 'running':
                self.assertEqual(job['status'], 'completed', job)
                return job
            await asyncio.sleep(0.01)
        self.fail('Transfer did not finish')

    async def test_selected_and_all_exports_stream_back_and_import_without_overwriting(self):
        response = await self.client.post('/api/profiles/export', json={'usernames': ['alice']})
        self.assertEqual(response.status, 202)
        job = await self.finish((await response.json())['id'])
        self.assertEqual(job['total'], 1)
        response = await self.client.get('/api/profiles/download/' + job['id'])
        self.assertIn('.xanty', response.headers['Content-Disposition'])
        package = await response.read()
        with ZipFile(io.BytesIO(package)) as archive:
            manifest = json.loads(archive.read('manifest.json'))
            self.assertEqual(len(manifest['profiles']), 1)
        payload = FormData()
        payload.add_field('duplicates', 'rename')
        payload.add_field('file', package, filename='profiles.xanty', content_type='application/octet-stream')
        response = await self.client.post('/api/profiles/import', data=payload)
        self.assertEqual(response.status, 202, await response.text())
        imported = await self.finish((await response.json())['id'])
        self.assertEqual(imported['imported'], 1)
        self.assertEqual([a['username'] for a in self.accounts], ['alice', 'bob', 'alice_2'])
        response = await self.client.get('/api/jobs/' + job['id'] + '/report')
        report = await response.text()
        self.assertNotIn('private-cookie', report)
        self.assertNotIn('private-proxy-password', report)
        self.assertNotIn('private-x-token', report)
        response = await self.client.post('/api/profiles/export', json={'all': True})
        all_job = await self.finish((await response.json())['id'])
        self.assertEqual(all_job['total'], 3)

    async def test_open_profiles_and_cross_origin_requests_cannot_export(self):
        self.app.engine.account_manager.accounts['alice'] = SimpleNamespace(browser=object())
        response = await self.client.post('/api/profiles/export', json={'all': True})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.app.jobs.snapshots(), [])
        response = await self.client.post('/api/profiles/export', json={'all': True},
                                          headers={'Origin': 'https://other.example'})
        self.assertEqual(response.status, 403)

    async def test_preferences_survive_a_new_app_and_reject_unsupported_values(self):
        response = await self.client.put('/api/preferences', json={'language': 'uk', 'theme': 'light'})
        self.assertEqual(response.status, 200)
        result = await response.json()
        self.assertEqual({k: result[k] for k in ('language', 'theme')}, {'language': 'uk', 'theme': 'light'})
        from xgenius.preferences import read_preferences
        self.assertEqual({k: read_preferences()[k] for k in ('language', 'theme')}, {'language': 'uk', 'theme': 'light'})
        response = await self.client.put('/api/preferences', json={'language': 'other'})
        self.assertEqual(response.status, 400)
        self.assertEqual(read_preferences()['language'], 'uk')

    async def test_updates_are_readable_without_a_repository_and_download_is_rejected(self):
        with patch.dict('os.environ', {'XANTY_UPDATE_REPOSITORY': ''}):
            from xgenius.updates import UpdateManager
            self.app.updates = UpdateManager()
        response = await self.client.get('/api/updates')
        self.assertEqual(response.status, 200)
        self.assertFalse((await response.json())['configured'])
        response = await self.client.post('/api/updates/check', json={'automatic': True})
        self.assertEqual((await response.json())['status'], 'unconfigured')
        response = await self.client.post('/api/updates/download', json={})
        self.assertEqual(response.status, 400)
        self.assertIn('Check for a new version', (await response.json())['error'])

    async def test_update_waits_for_an_upload_before_its_job_exists(self):
        from xgenius.updates import UpdateError
        release = asyncio.Event()
        async def body():
            yield b'--qa\r\nContent-Disposition: form-data; name="file"; filename="a.xanty"\r\n\r\nx'
            await release.wait()
            yield b'\r\n--qa--\r\n'
        async def upload():
            return await self.client.post('/api/profiles/import', data=body(),
                headers={'Content-Type':'multipart/form-data; boundary=qa'})
        task = asyncio.create_task(upload())
        try:
            await asyncio.sleep(0.1)
            self.assertEqual(self.app.jobs.snapshots(), [])
            with self.assertRaises(UpdateError):
                self.app.require_update_idle()
        finally:
            release.set()
            response = await task
            await response.read()

    async def test_invalid_package_is_rejected_before_starting_an_import(self):
        payload = FormData()
        payload.add_field('file', b'not a ZIP archive', filename='broken.xanty')
        response = await self.client.post('/api/profiles/import', data=payload)
        self.assertEqual(response.status, 400)
        self.assertEqual(len(self.accounts), 2)
        self.assertEqual(self.app.jobs.snapshots(), [])


if __name__ == '__main__':
    unittest.main()
