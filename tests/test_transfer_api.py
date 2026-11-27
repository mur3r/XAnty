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
from xgenius.profile_leases import ProfileLease
from xgenius.web.actions import Actions
from xgenius.web.engine import Engine
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
        payload.add_field('file_size', str(len(package)))
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

    async def test_selected_and_all_profile_packages_save_in_the_chosen_folder_and_remember_it(self):
        from xgenius.profile_archive import inspect_package
        from xgenius.preferences import read_preferences
        folder = self.root / 'Chosen transfer folder'
        folder.mkdir()
        for body, total in (({'usernames': ['alice']}, 1), ({'all': True}, 2)):
            response = await self.client.post('/api/profiles/export', json={**body, 'export_directory': str(folder)})
            self.assertEqual(response.status, 202, await response.text())
            job = await self.finish((await response.json())['id'])
            saved = Path(job['saved_path'])
            self.assertEqual(saved.parent, folder.resolve())
            self.assertEqual(saved.suffix, '.xanty')
            self.assertTrue(saved.is_file())
            self.assertEqual(inspect_package(saved)['total'], total)
            self.assertEqual(read_preferences()['export_directory'], str(folder.resolve()))
            response = await self.client.get('/api/profiles/download/' + job['id'])
            self.assertEqual(await response.read(), saved.read_bytes())
        self.assertEqual(len(list(folder.glob('*.xanty'))), 2)
        self.assertEqual(list(folder.glob('*.tmp')), [])
        self.assertIsNone(self.app._transfer_storage, 'Chosen-folder exports should not need a second temporary package')
        await self.app.shutdown()
        self.assertEqual(len(list(folder.glob('*.xanty'))), 2, 'Closing the app must retain the saved packages')

    async def test_clearing_the_export_folder_restores_normal_downloads(self):
        from xgenius.preferences import save_preferences, read_preferences
        save_preferences({'export_directory': str(self.root)})
        response = await self.client.post('/api/profiles/export', json={'all': True, 'export_directory': ''})
        job = await self.finish((await response.json())['id'])
        self.assertNotIn('saved_path', job)
        self.assertTrue(job['download_ready'])
        self.assertEqual(read_preferences()['export_directory'], '')

    async def test_invalid_export_folders_are_rejected_before_starting(self):
        for directory in ('relative/path', str(self.root / 'missing'), [], 'bad\0path'):
            response = await self.client.post('/api/profiles/export', json={'all': True, 'export_directory': directory})
            self.assertEqual(response.status, 400, await response.text())
            self.assertEqual(self.app.jobs.snapshots(), [])

    async def test_cancelled_chosen_folder_export_never_publishes_a_partial_package(self):
        from xgenius.profile_archive import export_package
        folder = self.root / 'Cancelled transfer'
        folder.mkdir()
        entered, release = threading.Event(), threading.Event()
        def waiting_export(*args, **kwargs):
            result = export_package(*args, **kwargs)
            entered.set()
            release.wait(10)
            return result
        with patch('xgenius.web.server.export_package', side_effect=waiting_export):
            response = await self.client.post('/api/profiles/export', json={'all': True, 'export_directory': str(folder)})
            job_id = (await response.json())['id']
            try:
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                response = await self.client.post('/api/jobs/' + job_id + '/cancel', json={})
                self.assertEqual(response.status, 200)
            finally:
                release.set()
                await self.app.jobs.get(job_id).task
        self.assertEqual(self.app.jobs.get(job_id).status, 'cancelled')
        self.assertEqual(list(folder.iterdir()), [])
        self.assertFalse(self.app.actions._transferring)

    async def test_open_profiles_and_cross_origin_requests_cannot_export(self):
        self.app.engine.account_manager.accounts['alice'] = SimpleNamespace(browser=object())
        response = await self.client.post('/api/profiles/export', json={'all': True})
        self.assertEqual(response.status, 400)
        self.assertEqual(self.app.jobs.snapshots(), [])
        response = await self.client.post('/api/profiles/export', json={'all': True},
                                          headers={'Origin': 'https://other.example'})
        self.assertEqual(response.status, 403)

    async def test_all_145_profiles_export_during_startup_size_scan(self):
        self.accounts[:] = [{'username': f'profile_{index:03d}', 'auto_login': False}
                            for index in range(145)]
        for account in self.accounts:
            username = account['username']
            (self.config.get_profile_dir(username) / 'Preferences').write_text(username)
            store_session(self.config, username, [
                {'name': 'session', 'value': username, 'domain': '.example.test'}])
        entered, release = threading.Event(), threading.Event()
        self.app.engine._shutdown_event = threading.Event()

        def slow_size(config, username):
            entered.set()
            if not release.wait(30):
                raise TimeoutError('Size scan was not released')
            return {'bytes': 0}

        scan = None
        try:
            with patch('xgenius.web.engine.profile_size', side_effect=slow_size), \
                    patch('xgenius.profile_leases.psutil.process_iter', return_value=[]):
                scan = asyncio.create_task(asyncio.to_thread(
                    Engine._measure_profile_sizes, self.app.engine, ['profile_000']))
                self.assertTrue(await asyncio.to_thread(entered.wait, 5))
                response = await self.client.post('/api/profiles/export', json={'all': True})
                self.assertEqual(response.status, 202)
                job_id = (await response.json())['id']
                await asyncio.wait_for(asyncio.shield(self.app.jobs.get(job_id).task), 30)
                job = await self.finish(job_id)
                self.assertFalse(scan.done(), 'Export waited for the size scan to finish')
                self.assertEqual(job['total'], 145)
                self.assertEqual(job['exported'], 145)
                self.assertEqual(job['integrity'], 'verified')
                response = await self.client.get('/api/profiles/download/' + job_id)
                self.assertEqual(response.status, 200)
                with ZipFile(io.BytesIO(await response.read())) as archive:
                    manifest = json.loads(archive.read('manifest.json'))
                    self.assertEqual([p['account']['username'] for p in manifest['profiles']],
                                     [a['username'] for a in self.accounts])
                    for index, account in enumerate(self.accounts):
                        prefix = f'profiles/{index:06d}'
                        self.assertEqual(archive.read(prefix + '/browser/Preferences').decode(),
                                         account['username'])
                        cookies = json.loads(archive.read(prefix + '/cookies.json'))
                        self.assertEqual(cookies[0]['value'], account['username'])
        finally:
            release.set()
            if scan is not None:
                await scan

    async def test_all_145_profiles_roundtrip_to_a_fresh_workspace_with_every_setting_and_cookie(self):
        from xgenius.portable_session import session_path
        self.accounts[:] = [dict(
            username=f'dolphin_{index:03d}', profile_name=f'Робочий профіль {index:03d}',
            dolphin_name=f'Dolphin source {index}', dolphin_profile_id=index + 1000,
            group=f'Team {index % 3}', notes=f'Note {index}', tags=['work', f'tag{index}'],
            proxy=f'http://user{index}:password{index}@proxy.example:{10000 + index}',
            proxy_rotation_url=f'https://provider.example/rotate?key=synthetic-{index}',
            password=f'password{index}', auth_token=f'auth{index}', ct0_token=f'csrf{index}',
            user_agent=f'Synthetic User Agent {index}', auto_login=bool(index % 2),
            browser_language='uk-UA', browser_timezone='Europe/Kyiv',
            window_width=1280, window_height=800, restore_tabs=True, icon_text=str(index),
            block_images=True, block_media=False, block_fonts=True, phishing_protection=True,
            profile_status='active', favorite=bool(index % 2), important=False,
            reminder_at='2027-01-01T12:00:00Z', reminder_note=f'Reminder {index}',
            future_setting={'enabled': True, 'index': index}) for index in range(145)]
        expected = copy.deepcopy(self.accounts)
        expected_cookies = {}
        for account in expected:
            username = account['username']
            cookies = [{'name': 'auth_token', 'value': 'session-' + username, 'domain': '.x.com'},
                       {'name': 'other', 'value': 'other-' + username, 'domain': 'example.test'}]
            store_session(self.config, username, cookies)
            expected_cookies[username] = json.loads(session_path(self.config, username).read_text())['cookies']
            profile = self.config.get_profile_dir(username)
            (profile / 'Preferences').write_text(json.dumps({'synthetic': username}), encoding='utf-8')
            tabs = session_path(self.config, username).parent / 'tabs.json'
            tabs.write_text(json.dumps({'urls': ['https://example.test/' + username]}))
        with patch('xgenius.profile_leases.psutil.process_iter', return_value=[]):
            response = await self.client.post('/api/profiles/export', json={'all': True})
            self.assertEqual(response.status, 202, await response.text())
            exported = await self.finish((await response.json())['id'])
            response = await self.client.get('/api/profiles/download/' + exported['id'])
            package = await response.read()
            with ZipFile(io.BytesIO(package)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                self.assertEqual([item['account'] for item in manifest['profiles']], expected)
                self.assertTrue(all(manifest['privacy'].values()))
            self.accounts.clear()
            friend = Config(self.root / 'friend-workspace')
            self.app.engine.config = friend
            self.app.engine.folders = FolderStore(friend.base_dir / 'folders.json')
            self.app.actions = Actions(self.app.engine)
            payload = FormData()
            payload.add_field('file', package, filename='full-transfer.xanty', content_type='application/octet-stream')
            response = await self.client.post('/api/profiles/import', data=payload)
            self.assertEqual(response.status, 202, await response.text())
            imported = await self.finish((await response.json())['id'])
        self.assertEqual(imported['imported'], 145)
        self.assertEqual(self.accounts, expected)
        for account in expected:
            username = account['username']
            restored = json.loads(session_path(friend, username).read_text())
            self.assertTrue(restored['pending'])
            self.assertEqual(restored['cookies'], expected_cookies[username])
            self.assertEqual(json.loads((friend.get_profile_dir(username) / 'Preferences').read_text())['synthetic'], username)
            tabs = session_path(friend, username).parent / 'tabs.json'
            self.assertEqual(json.loads(tabs.read_text())['urls'], ['https://example.test/' + username])

    async def test_export_rejects_a_profile_leased_by_another_session_then_retries(self):
        with ProfileLease.acquire(self.config, 'alice', check_processes=False):
            response = await self.client.post('/api/profiles/export', json={'all': True})
            self.assertEqual(response.status, 202)
            job_id = (await response.json())['id']
            await self.app.jobs.get(job_id).task
            job = await (await self.client.get('/api/jobs/' + job_id)).json()
            self.assertEqual(job['status'], 'failed')
            self.assertIn('already open in another session', job['error'])
            self.assertFalse(job['download_ready'])
        self.assertFalse(self.app.actions._transferring)
        response = await self.client.post('/api/profiles/export', json={'all': True})
        job = await self.finish((await response.json())['id'])
        self.assertEqual(job['exported'], 2)

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

    async def test_multichunk_compressed_download_resume_and_upload_preserve_browser_bytes(self):
        import random
        data = random.Random(109).randbytes(3 * 1024 * 1024 + 117)
        (self.config.get_profile_dir('alice') / 'state.bin').write_bytes(data)
        response = await self.client.post('/api/profiles/export', json={'usernames': ['alice']})
        job = await self.finish((await response.json())['id'])
        url = '/api/profiles/download/' + job['id']
        response = await self.client.get(url)
        package = await response.read()
        self.assertEqual(int(response.headers['Content-Length']), len(package))
        split = 1024 * 1024 + 33
        first = await self.client.get(url, headers={'Range': f'bytes=0-{split - 1}'})
        second = await self.client.get(url, headers={'Range': f'bytes={split}-'})
        self.assertEqual(first.status, 206)
        self.assertEqual(second.status, 206)
        self.assertEqual(await first.read() + await second.read(), package)
        payload = FormData()
        payload.add_field('file_size', str(len(package)))
        payload.add_field('file', package, filename='multichunk.xanty')
        response = await self.client.post('/api/profiles/import', data=payload)
        self.assertEqual(response.status, 202, await response.text())
        imported = await self.finish((await response.json())['id'])
        self.assertEqual(imported['imported'], 1)
        self.assertEqual((self.config.get_profile_dir('alice_2') / 'state.bin').read_bytes(), data)

    async def test_incomplete_or_invalid_upload_size_is_rejected_before_import_and_cleaned(self):
        from xgenius.profile_archive import export_package
        path = self.root / 'valid.xanty'
        export_package(self.config, self.accounts, path)
        package = path.read_bytes()
        for size in (str(len(package) + 1), str(len(package) - 1), '0', '-1', 'no size',
                     '1.5', '9' * 100, str(64 * 1024 ** 3 + 1)):
            with self.subTest(size=size):
                payload = FormData()
                payload.add_field('file_size', size)
                payload.add_field('file', package, filename='profiles.xanty')
                response = await self.client.post('/api/profiles/import', data=payload)
                self.assertEqual(response.status, 400, await response.text())
                self.assertEqual(len(self.accounts), 2)
                self.assertEqual(self.app.jobs.snapshots(), [])
                self.assertEqual(list(self.app.transfer_directory().glob('upload-*')), [])

    async def test_failed_export_verification_never_offers_a_download_and_releases_profiles(self):
        from xgenius.profile_archive import ArchiveError
        with patch('xgenius.profile_archive.inspect_package', side_effect=ArchiveError(
                'Profile package integrity check failed: corrupt ZIP data')):
            response = await self.client.post('/api/profiles/export', json={'all': True})
            self.assertEqual(response.status, 202)
            job_id = (await response.json())['id']
            await self.app.jobs.get(job_id).task
        job = await (await self.client.get('/api/jobs/' + job_id)).json()
        self.assertEqual(job['status'], 'failed')
        self.assertFalse(job['download_ready'])
        self.assertIn('integrity', job['error'])
        response = await self.client.get('/api/profiles/download/' + job_id)
        self.assertEqual(response.status, 400)
        self.assertFalse(self.app.actions._transferring)
        self.assertEqual(list(self.app.transfer_directory().glob('*.xanty')), [])
        response = await self.client.post('/api/profiles/export', json={'all': True})
        self.assertEqual((await self.finish((await response.json())['id']))['exported'], 2)

    async def test_invalid_package_is_rejected_before_starting_an_import(self):
        payload = FormData()
        payload.add_field('file', b'not a ZIP archive', filename='broken.xanty')
        response = await self.client.post('/api/profiles/import', data=payload)
        self.assertEqual(response.status, 400)
        self.assertEqual(len(self.accounts), 2)
        self.assertEqual(self.app.jobs.snapshots(), [])


if __name__ == '__main__':
    unittest.main()
