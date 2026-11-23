"""Only trusted, complete, hash-verified release assets may replace the app."""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xgenius import updates


def release(version='v2026.11.22.10', digest=None, size=6):
    return {'tag_name': version, 'html_url': 'https://github.com/example/XAnty/releases/tag/' + version,
            'body': 'New version', 'draft': False, 'prerelease': False, 'assets': [{
                'name': 'XAnty.exe', 'size': size, 'digest': digest or 'sha256:' + hashlib.sha256(b'MZtest').hexdigest(),
                'browser_download_url': 'https://github.com/example/XAnty/releases/download/' + version + '/XAnty.exe'}]}


class UpdateTests(unittest.TestCase):
    def test_numeric_versions_prevent_lexicographic_downgrades(self):
        self.assertIsNotNone(updates.select_release(release(), 'example/XAnty', '2026.11.22.2'))
        self.assertIsNone(updates.select_release(release('v2026.11.22.1'), 'example/XAnty', '2026.11.22.2'))
        self.assertIsNone(updates.select_release(release('v2026.11.22.2'), 'example/XAnty', '2026.11.22.2'))
        with self.assertRaises(updates.UpdateError):
            updates.select_release(release('invalid-tag'), 'example/XAnty', '2026.11.22.2')

    def test_missing_digest_or_untrusted_download_cannot_be_installed(self):
        for field, value in [('digest', ''), ('browser_download_url', 'https://evil.test/XAnty.exe')]:
            data = release()
            data['assets'][0][field] = value
            with self.subTest(field=field), self.assertRaises(updates.UpdateError):
                updates.select_release(data, 'example/XAnty', '2026.11.22.2')

    def test_download_verifies_content_and_cleans_incomplete_files(self):
        class Response:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def iter_content(self, size): yield self.content
        class Session:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def get(self, *a, **kw): return response
        response = Response()
        selected = updates.select_release(release(), 'example/XAnty', '2026.11.22.2')
        with tempfile.TemporaryDirectory() as directory, patch('requests.Session', Session):
            destination = Path(directory) / 'XAnty.exe'
            response.content = b'MZbad!'
            with self.assertRaises(updates.UpdateError):
                updates.download_release(selected, destination)
            self.assertFalse(destination.exists())
            self.assertEqual(list(Path(directory).iterdir()), [])
            response.content = b'MZtest'
            updates.download_release(selected, destination)
            self.assertEqual(destination.read_bytes(), b'MZtest')

    def test_cancelled_download_is_discarded(self):
        import threading
        cancel = threading.Event()
        cancel.set()
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(updates.UpdateError, 'cancelled'):
                updates.download_release({}, Path(directory)/'XAnty.exe', cancel_event=cancel)
            self.assertEqual(list(Path(directory).iterdir()), [])


class UpdateGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_exit_during_installation_status_cannot_start_the_helper(self):
        import threading
        closing=threading.Event()
        selected=updates.select_release(release('v2099.1.1.1'),'example/XAnty','2026.11.22.2')
        def progress(message):
            if message.startswith('Устанавливаем обновление.'):closing.set()
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home',return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config',return_value={'repository':'example/XAnty'}), \
                patch('xgenius.updates.supports_install',return_value=True), \
                patch('xgenius.updates.fetch_release',return_value=selected), \
                patch('xgenius.updates.download_release'), \
                patch.object(updates.UpdateManager,'_launch_helper') as install:
            manager=updates.UpdateManager()
            self.assertFalse(await manager.update_on_startup(closing,progress))
            install.assert_not_called()

    async def test_exit_during_startup_progress_is_not_cleared_by_download(self):
        import threading
        closing=threading.Event()
        selected=updates.select_release(release('v2099.1.1.1'),'example/XAnty','2026.11.22.2')
        def progress(message):
            if message.startswith('Скачиваем обновление '):closing.set()
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home',return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config',return_value={'repository':'example/XAnty'}), \
                patch('xgenius.updates.supports_install',return_value=True), \
                patch('xgenius.updates.fetch_release',return_value=selected), \
                patch('xgenius.updates.download_release') as download, \
                patch.object(updates.UpdateManager,'_launch_helper') as install:
            manager=updates.UpdateManager()
            self.assertFalse(await manager.update_on_startup(closing,progress))
            self.assertTrue(closing.is_set())
            download.assert_not_called();install.assert_not_called()

    async def test_startup_checks_even_with_fresh_cache_and_installs_without_user_clicks(self):
        import threading
        import time
        selected = updates.select_release(release('v2099.1.1.1'), 'example/XAnty', '2026.11.22.2')
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home', return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config', return_value={'repository': 'example/XAnty'}), \
                patch('xgenius.updates.supports_install', return_value=True), \
                patch('xgenius.updates.fetch_release', return_value=selected) as fetch, \
                patch('xgenius.updates.download_release') as download, \
                patch.object(updates.UpdateManager, '_launch_helper') as install:
            manager = updates.UpdateManager()
            manager.last_checked = time.time()
            messages = []
            self.assertTrue(await manager.update_on_startup(threading.Event(), messages.append))
            fetch.assert_called_once()
            download.assert_called_once()
            install.assert_called_once()
            self.assertEqual(manager.status, 'installing')
            self.assertTrue(messages)

    async def test_failed_installation_is_not_retried_in_an_endless_restart_loop(self):
        import threading
        selected = updates.select_release(release('v2099.1.1.1'), 'example/XAnty', '2026.11.22.2')
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home', return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config', return_value={'repository': 'example/XAnty'}), \
                patch('xgenius.updates.supports_install', return_value=True), \
                patch('xgenius.updates.fetch_release', return_value=selected), \
                patch('xgenius.updates.download_release') as download:
            manager = updates.UpdateManager()
            manager.root.mkdir(parents=True)
            (manager.root / 'result.json').write_text(json.dumps({'ok': False, 'version': selected['version']}))
            self.assertFalse(await manager.update_on_startup(threading.Event(), lambda message: None))
            download.assert_not_called()

    async def test_offline_or_closing_startup_keeps_the_existing_application(self):
        import threading
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home', return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config', return_value={'repository': 'example/XAnty'}), \
                patch('xgenius.updates.supports_install', return_value=True), \
                patch('xgenius.updates.fetch_release', side_effect=updates.UpdateError('Offline')) as fetch, \
                patch.object(updates.UpdateManager, '_launch_helper') as install:
            manager = updates.UpdateManager()
            self.assertFalse(await manager.update_on_startup(threading.Event(), lambda message: None))
            self.assertEqual(manager.status, 'error')
            closing = threading.Event()
            closing.set()
            self.assertFalse(await manager.update_on_startup(closing, lambda message: None))
            self.assertEqual(fetch.call_count, 1)
            install.assert_not_called()

    async def test_closing_during_download_cannot_launch_installer(self):
        import threading
        closing = threading.Event()
        selected = updates.select_release(release('v2099.1.1.1'), 'example/XAnty', '2026.11.22.2')
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home', return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config', return_value={'repository': 'example/XAnty'}), \
                patch('xgenius.updates.supports_install', return_value=True), \
                patch('xgenius.updates.fetch_release', return_value=selected), \
                patch('xgenius.updates.download_release', side_effect=lambda *args: closing.set()), \
                patch.object(updates.UpdateManager, '_launch_helper') as install:
            manager = updates.UpdateManager()
            self.assertFalse(await manager.update_on_startup(closing, lambda message: None))
            install.assert_not_called()

    async def test_download_cannot_start_while_checking_a_newer_release(self):
        import asyncio
        import threading
        started, finish = threading.Event(), threading.Event()
        newer = updates.select_release(release('v2026.11.24.1'), 'example/XAnty', '2026.11.22.3')
        def fetch(*args):
            started.set()
            finish.wait(5)
            return newer
        with tempfile.TemporaryDirectory() as directory, \
                patch('xgenius.updates.application_home', return_value=Path(directory)), \
                patch('xgenius.updates.read_update_config', return_value={'repository':'example/XAnty'}), \
                patch('xgenius.updates.supports_install', return_value=True), \
                patch('xgenius.updates.fetch_release', side_effect=fetch):
            manager = updates.UpdateManager()
            manager.release = updates.select_release(release('v2026.11.23.1'), 'example/XAnty', '2026.11.22.3')
            manager.status = 'available'
            task = asyncio.create_task(manager.check())
            await asyncio.wait_for(asyncio.to_thread(started.wait), timeout=2)
            try:
                with self.assertRaisesRegex(updates.UpdateError, 'check'):
                    manager.start_download()
            finally:
                finish.set()
                await task
                if manager._download_task:
                    await manager.shutdown()

    async def test_running_profiles_or_transfers_block_installation(self):
        from xgenius.web.server import WebApp
        import asyncio
        app = WebApp(asyncio.get_running_loop(), desktop_mode=True)
        app.actions = SimpleNamespace(_busy=set(), _closing=set(), _transferring=set())
        app.engine = SimpleNamespace(account_manager=SimpleNamespace(accounts={'alice': SimpleNamespace(browser=object())}))
        with self.assertRaisesRegex(Exception, 'Close all profiles'):
            app.require_update_idle()
        app.engine.account_manager.accounts.clear()
        app.jobs.jobs['one'] = SimpleNamespace(status='running')
        with self.assertRaisesRegex(Exception, 'transfer'):
            app.require_update_idle()

    async def test_queued_launch_blocks_installation_between_profiles(self):
        from xgenius.web.server import WebApp
        import asyncio
        app = WebApp(asyncio.get_running_loop(), desktop_mode=True)
        pending = asyncio.create_task(asyncio.sleep(1))
        try:
            app.actions = SimpleNamespace(_busy=set(), _closing=set(), _transferring=set(), _launch_tasks={pending})
            with self.assertRaisesRegex(Exception, 'actions'):
                app.require_update_idle()
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)

    async def test_unconfigured_channel_does_not_make_network_requests(self):
        with patch('xgenius.updates.read_update_config', return_value={'repository':'', 'asset':'XAnty.exe'}):
            manager = updates.UpdateManager()
            with patch('xgenius.updates.fetch_release', side_effect=AssertionError('Unexpected network request')):
                result = await manager.check()
        self.assertFalse(result['configured'])
        self.assertEqual(result['status'], 'unconfigured')


@unittest.skipUnless(os.name == 'nt', 'Windows PowerShell helper')
class UpdateHelperTests(unittest.TestCase):
    def test_new_process_must_acknowledge_startup_or_the_helper_rolls_back(self):
        helper_source = Path(updates.__file__).with_name('update_helper.ps1')
        for healthy in (True, False):
            with self.subTest(healthy=healthy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target, source, health = root/'XAnty.exe', root/'new.exe', root/'health.json'
                target.write_bytes(b'MZold')
                source.write_bytes(b'MZnew')
                helper = root/'helper.ps1'
                shutil.copyfile(helper_source, helper)
                manifest = root/'plan.json'
                manifest.write_text(json.dumps({'pid': 987654321, 'target': str(target), 'source': str(source),
                    'sha256': hashlib.sha256(b'MZnew').hexdigest(), 'version': '99.0',
                    'health': str(health), 'result': str(root/'result.json')}))
                quote = lambda p: "'" + str(p).replace("'", "''") + "'"
                acknowledgement = ("'{\"version\":\"99.0\"}' | Set-Content -LiteralPath " + quote(health)) if healthy else ''
                wrapper = root/'run.ps1'
                wrapper.write_text(f'''function Start-Process {{
param($FilePath,$WorkingDirectory,$WindowStyle,[switch]$PassThru)
if ($PassThru) {{
  {acknowledgement}
  return [pscustomobject]@{{HasExited=$true}}
}}
}}
& {quote(helper)} -Manifest {quote(manifest)}
''')
                subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                                '-File',str(wrapper)],check=True,capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW)
                result = json.loads((root/'result.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(result['ok'], healthy, result)
                self.assertEqual(target.read_bytes(), b'MZnew' if healthy else b'MZold')
                self.assertFalse(health.exists())

    def test_atomic_replace_backup_and_rollback_use_only_test_files(self):
        helper_source = Path(updates.__file__).with_name('update_helper.ps1')
        for scenario in ('success', 'restart-failure', 'checksum-failure'):
            fail_restart = scenario == 'restart-failure'
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                target, source = root/'XAnty.exe', root/'new.exe'
                target.write_bytes(b'MZold')
                source.write_bytes(b'MZnew')
                helper = root/'helper.ps1'
                shutil.copyfile(helper_source, helper)
                manifest = root/'plan.json'
                manifest.write_text(json.dumps({'pid': 987654321, 'target':str(target), 'source':str(source),
                    'sha256':('0'*64 if scenario=='checksum-failure' else hashlib.sha256(b'MZnew').hexdigest()),
                    'version':'99.0', 'result':str(root/'result.json')}))
                # Stub process launch, but exercise real hashing, replacement, backup, rollback and cleanup.
                wrapper = root/'run.ps1'
                fail = '$true' if fail_restart else '$false'
                quote = lambda p: "'" + str(p).replace("'", "''") + "'"
                wrapper.write_text(f'''$script:attempts=0
function Start-Process {{
param($FilePath,$WorkingDirectory,$WindowStyle)
if ($WindowStyle -ne 'Hidden') {{ throw 'Helper window was not hidden' }}
$script:attempts++
if ({fail} -and $script:attempts -eq 1) {{ throw 'Test restart failure' }}
Add-Content -LiteralPath {quote(root/'restarted.txt')} -Value ('reset=' + $env:PYINSTALLER_RESET_ENVIRONMENT)
}}
& {quote(helper)} -Manifest {quote(manifest)}
''')
                subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
                                '-File',str(wrapper)], check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                result = json.loads((root/'result.json').read_text(encoding='utf-8-sig'))
                self.assertEqual(result['ok'], scenario=='success', result)
                self.assertEqual(target.read_bytes(), b'MZnew' if scenario=='success' else b'MZold')
                if scenario!='checksum-failure':
                    self.assertEqual((root/'XAnty.exe.previous').read_bytes(), b'MZold')
                self.assertTrue((root/'restarted.txt').exists(), 'Always restart the original app after a post-exit failure')
                self.assertEqual((root/'restarted.txt').read_text().strip(), 'reset=1',
                                 'Restart must unpack a fresh onefile runtime after the old process exits')
                self.assertFalse((root/'XAnty.exe.next').exists())
                self.assertFalse(source.exists())
