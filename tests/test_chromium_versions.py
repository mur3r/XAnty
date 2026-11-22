"""CfT management uses mock HTTP bytes and temporary files; never launches downloads."""
import io
import json
import os
import stat
import struct
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from xgenius import chromium_versions as cv
from xgenius.config import Config


VERSION = '130.0.6723.58'
OTHER = '131.0.6778.1'
BASE = 'https://googlechromelabs.github.io/chrome-for-testing/'


def asset_url(version, binary):
    return f'https://storage.googleapis.com/chrome-for-testing-public/{version}/win64/{binary}-win64.zip'


def record(version=VERSION):
    return {'version': version, 'revision': '12345', 'downloads': {
        binary: [{'platform': 'win64', 'url': asset_url(version, binary)}]
        for binary in ('chrome', 'chromedriver')}}


def executable(version=VERSION, machine=0x8664):
    data = bytearray(256)
    data[:2] = b'MZ'
    struct.pack_into('<I', data, 60, 128)
    data[128:132] = b'PE\0\0'
    struct.pack_into('<H', data, 132, machine)
    return bytes(data) + b'VERSION=' + version.encode('ascii')


def archive(binary, version=VERSION, extra=(), machine=0x8664):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(f'{binary}-win64/{binary}.exe', executable(version, machine))
        for name, content in extra:
            # ZipInfo normally normalizes Windows backslashes, hiding malformed input.
            info = zipfile.ZipInfo(name)
            info.filename = info.orig_filename = name
            zf.writestr(info, content)
    return stream.getvalue()


class Response:
    def __init__(self, url, content, status=200, headers=None):
        self.url, self.content, self.status_code = url, content, status
        self.headers = {'Content-Length': str(len(content)), **(headers or {})}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, chunk_size):
        for start in range(0, len(self.content), 73):
            yield self.content[start:start + 73]


class FakeSession:
    def __init__(self, responses, requested):
        self.responses, self.requested = responses, requested
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def get(self, url, **kwargs):
        self.requested.append(url)
        if url not in self.responses:
            raise AssertionError('Unexpected network URL: ' + url)
        value = self.responses[url]
        return value if isinstance(value, Response) else Response(url, value)


class ChromiumVersionsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.config = SimpleNamespace(base_dir=self.base)
        self.responses, self.requested = {}, []
        self.addCleanup(patch.stopall)
        patch('requests.Session', lambda: FakeSession(self.responses, self.requested)).start()
        # Fixture PEs are inert bytes. Only native version-resource access is substituted.
        patch.object(cv, '_file_version', lambda path: Path(path).read_bytes().split(b'VERSION=')[-1].decode()).start()
        patch.object(cv.psutil, 'process_iter', return_value=[]).start()
        self.manager = cv.ChromiumVersionManager(self.config)
        self.add_version(VERSION)

    def add_version(self, version):
        self.responses[BASE + version + '.json'] = json.dumps(record(version)).encode()
        for binary in ('chrome', 'chromedriver'):
            self.responses[asset_url(version, binary)] = archive(binary, version)
        channel = record(version)
        channel['channel'] = 'Stable'
        self.responses[BASE + 'last-known-good-versions-with-downloads.json'] = json.dumps(
            {'timestamp': '2026-11-22T12:00:00Z', 'channels': {'Stable': channel}}).encode()
        self.responses[BASE + 'known-good-versions-with-downloads.json'] = json.dumps(
            {'timestamp': '2026-11-22T12:00:00Z', 'versions': [record(version)]}).encode()

    def no_staging(self):
        self.assertEqual(list((self.base / 'chromium_versions').glob('.stage-*')), [])

    def test_fresh_manager_keeps_bundled_paths_and_does_not_contact_vendor(self):
        self.config.chrome_path = self.base / 'an-old-selection.exe'
        self.assertEqual(self.manager.active_paths(),
                         (self.base / 'Bro/chrome.exe', self.base / 'Drivers/chromedriver.exe'))
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot['selected'], 'bundled')
        self.assertEqual(snapshot['installed'][0]['version'], 'bundled')
        self.assertFalse(snapshot['installed'][0]['available'])
        self.assertEqual(self.requested, [])

    def test_available_lists_only_exact_complete_win64_pairs_in_numeric_order(self):
        incomplete = record('113.0.5672.1')
        del incomplete['downloads']['chromedriver']
        self.responses[BASE + 'known-good-versions-with-downloads.json'] = json.dumps({
            'timestamp': 'now', 'versions': [record('99.0.0.1'), incomplete, record(VERSION)]}).encode()
        result = self.manager.available()
        self.assertEqual(result['channels']['Stable']['version'], VERSION)
        self.assertEqual([row['version'] for row in result['versions']], [VERSION, '99.0.0.1'])
        self.assertEqual(result['platform'], 'win64')
        self.assertFalse(result['hash_verified'])

    def test_install_channel_validates_pair_and_keeps_selection_explicit(self):
        progress = []
        installed = self.manager.install('stable', progress=progress.append)
        self.assertEqual(installed['version'], VERSION)
        self.assertFalse(installed['selected'])
        self.assertFalse(installed['hash_verified'])
        self.assertTrue(Path(installed['chrome_path']).is_file())
        self.assertTrue(Path(installed['driver_path']).is_file())
        self.assertEqual(self.manager.snapshot()['selected'], 'bundled')
        self.assertEqual(progress[-1]['phase'], 'complete')
        self.assertTrue(any(row.get('downloaded', 0) > 0 for row in progress))
        self.no_staging()

    def test_selection_survives_restart_and_selected_install_cannot_be_deleted(self):
        installed = self.manager.install(VERSION)
        self.manager.select(VERSION)
        restarted = cv.ChromiumVersionManager(self.config)
        self.assertEqual(restarted.active_paths(), (Path(installed['chrome_path']), Path(installed['driver_path'])))
        with self.assertRaisesRegex(cv.ChromiumVersionError, 'selected'):
            restarted.delete(VERSION)
        restarted.select('bundled')
        restarted.delete(VERSION)
        self.assertEqual([item['version'] for item in restarted.snapshot()['installed']], ['bundled'])

    def test_config_initialization_and_refresh_use_the_selected_pair(self):
        installed = self.manager.install(VERSION)
        self.manager.select(VERSION)
        config = Config(self.base)
        self.assertEqual((config.chrome_path, config.chromedriver_path),
                         (Path(installed['chrome_path']), Path(installed['driver_path'])))
        self.manager.select('bundled')
        config.refresh_browser_paths()
        self.assertEqual((config.chrome_path, config.chromedriver_path),
                         (self.base / 'Bro/chrome.exe', self.base / 'Drivers/chromedriver.exe'))

    def test_config_defaults_and_corrupt_selected_pair_use_bundled_paths(self):
        config = Config(self.base)
        self.assertEqual(config.chrome_path, self.base / 'Bro/chrome.exe')
        installed = self.manager.install(VERSION)
        self.manager.select(VERSION)
        Path(installed['driver_path']).unlink()
        restarted = Config(self.base)
        self.assertEqual(restarted.chromedriver_path, self.base / 'Drivers/chromedriver.exe')
        self.assertTrue(cv.ChromiumVersionManager(restarted).snapshot()['selection_error'])

    def test_installed_version_is_idempotent_without_network(self):
        first = self.manager.install(VERSION)
        self.responses.clear()
        self.assertEqual(self.manager.install(VERSION)['chrome_path'], first['chrome_path'])

    def test_invalid_names_never_leave_the_version_store(self):
        for value in ('../outside', '130.0', 'Stable/../../', '', '130.0.1.2/..', 'bundled'):
            with self.subTest(value=value), self.assertRaises(cv.ChromiumVersionError):
                self.manager.install(value)
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.delete('bundled')
        self.assertEqual(self.requested, [])

    def test_untrusted_or_wrong_version_urls_are_rejected_before_downloading(self):
        for url in ('http://storage.googleapis.com/chrome-for-testing-public/a.zip',
                    'https://evil.test/browser.zip',
                    'https://storage.googleapis.com.evil.test/browser.zip',
                    'https://storage.googleapis.com:443/chrome-for-testing-public/a.zip',
                    'https://user@storage.googleapis.com/chrome-for-testing-public/a.zip',
                    asset_url(OTHER, 'chrome'),
                    asset_url(VERSION, 'chrome') + '?redirect=evil'):
            data = record()
            data['downloads']['chrome'][0]['url'] = url
            self.responses[BASE + VERSION + '.json'] = json.dumps(data).encode()
            with self.subTest(url=url), self.assertRaises(cv.ChromiumVersionError):
                self.manager.install(VERSION)
            self.no_staging()
        self.assertTrue(all(url.endswith('.json') for url in self.requested))

    def test_redirects_and_changed_response_urls_are_refused(self):
        url = BASE + VERSION + '.json'
        for response in (Response(url, b'', 302, {'Location': 'https://evil.test/'}),
                         Response('https://evil.test/m.json', json.dumps(record()).encode())):
            self.responses[url] = response
            with self.subTest(response=response), self.assertRaises(cv.ChromiumVersionError):
                self.manager.install(VERSION)
            self.no_staging()

    def test_partial_download_does_not_publish_version_or_change_selection(self):
        self.add_version(OTHER)
        self.manager.install(OTHER)
        self.manager.select(OTHER)
        url = asset_url(VERSION, 'chromedriver')
        self.responses[url] = Response(url, archive('chromedriver')[:-20], headers={'Content-Length': '9999'})
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.assertEqual(self.manager.snapshot()['selected'], OTHER)
        self.assertFalse((self.base / 'chromium_versions' / VERSION).exists())
        self.no_staging()

    def test_cancel_before_and_during_transfer_cleans_all_partial_files(self):
        for limit in (0, 5):
            calls = [0]
            def cancelled():
                calls[0] += 1
                return calls[0] > limit
            with self.subTest(limit=limit), self.assertRaisesRegex(cv.ChromiumVersionError, 'cancel'):
                self.manager.install(VERSION, cancelled=cancelled)
            self.assertFalse((self.base / 'chromium_versions' / VERSION).exists())
            self.no_staging()

    def test_zip_paths_cannot_escape_or_exploit_windows_path_aliases(self):
        for name in ('../escape.txt', '/absolute.txt', 'C:/outside.txt',
                     'chrome-win64/../escape.txt', 'chrome-win64\\escape.txt',
                     'chrome-win64/file:stream', 'chrome-win64/CON.txt',
                     'chrome-win64/trailing. /file', 'other-root/file.txt',
                     'chrome-win64/CHROME.EXE'):
            self.responses[asset_url(VERSION, 'chrome')] = archive('chrome', extra=[(name, b'bad')])
            with self.subTest(name=name), self.assertRaises(cv.ChromiumVersionError):
                self.manager.install(VERSION)
            self.no_staging()
            self.assertFalse((self.base / 'escape.txt').exists())

    def test_symlink_or_reparse_zip_entry_is_refused(self):
        for unix_mode, dos_flags in ((stat.S_IFLNK | 0o777, 0), (stat.S_IFREG | 0o644, 0x400)):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as zf:
                zf.writestr('chrome-win64/chrome.exe', executable())
                info = zipfile.ZipInfo('chrome-win64/link')
                info.create_system = 3
                info.external_attr = (unix_mode << 16) | dos_flags
                zf.writestr(info, '../outside')
            self.responses[asset_url(VERSION, 'chrome')] = stream.getvalue()
            with self.subTest(mode=unix_mode), self.assertRaises(cv.ChromiumVersionError):
                self.manager.install(VERSION)
            self.no_staging()

    def test_directory_payload_is_rejected_rather_than_skipping_its_crc_check(self):
        self.responses[asset_url(VERSION, 'chrome')] = archive('chrome', extra=[('chrome-win64/', b'unchecked')])
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()

    def test_zip_crc_corruption_is_detected_and_discarded(self):
        original = archive('chrome')
        damaged = original.replace(b'VERSION=' + VERSION.encode(), b'VERSION=' + (VERSION[:-1] + '9').encode(), 1)
        self.responses[asset_url(VERSION, 'chrome')] = damaged
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()
        self.assertFalse((self.base / 'chromium_versions' / VERSION).exists())

    def test_actual_executable_versions_must_match_exactly(self):
        self.responses[asset_url(VERSION, 'chromedriver')] = archive('chromedriver', OTHER)
        with self.assertRaisesRegex(cv.ChromiumVersionError, 'version'):
            self.manager.install(VERSION)
        self.no_staging()

    def test_non_win64_binary_and_download_size_limits_are_rejected(self):
        self.responses[asset_url(VERSION, 'chrome')] = archive('chrome', machine=0x14c)
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.responses[asset_url(VERSION, 'chrome')] = archive('chrome')
        with patch.object(cv, 'MAX_DOWNLOAD_BYTES', 100), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()

    def test_expanded_archive_and_member_count_limits_are_enforced(self):
        with patch.object(cv, 'MAX_EXTRACTED_BYTES', 100), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        with patch.object(cv, 'MAX_ZIP_MEMBERS', 0), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()

    def test_missing_content_length_still_enforces_actual_byte_limit(self):
        url = asset_url(VERSION, 'chrome')
        response = Response(url, archive('chrome'))
        response.headers.clear()
        self.responses[url] = response
        with patch.object(cv, 'MAX_DOWNLOAD_BYTES', 100), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()

    def test_transfer_deadline_and_cancel_during_extraction_discard_staging(self):
        # An always-expired total deadline must stop even a responsive server.
        with patch.object(cv, 'TRANSFER_SECONDS', -1), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        cancel = threading.Event()
        def progress(event):
            if event['phase'] == 'extract':
                cancel.set()
        with self.assertRaisesRegex(cv.ChromiumVersionError, 'cancel'):
            self.manager.install(VERSION, progress=progress, cancelled=cancel)
        self.assertFalse((self.base / 'chromium_versions' / VERSION).exists())
        self.no_staging()

    def test_failed_publication_rolls_back_staging_and_can_be_retried(self):
        with patch.object(cv.os, 'rename', side_effect=OSError('disk error')), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()
        self.assertFalse((self.base / 'chromium_versions' / VERSION).exists())
        self.assertEqual(self.manager.install(VERSION)['version'], VERSION)

    def test_a_second_manager_cannot_mutate_while_installation_is_in_progress(self):
        second = cv.ChromiumVersionManager(self.config)
        attempts = []
        def progress(event):
            if event['phase'] == 'download' and not attempts:
                try:
                    second.select('bundled')
                except Exception as error:
                    attempts.append(error)
                else:
                    attempts.append(None)
        self.manager.install(VERSION, progress=progress)
        self.assertEqual(len(attempts), 1)
        self.assertIsInstance(attempts[0], cv.ChromiumVersionError)
        self.assertIn('operation', str(attempts[0]))
        self.assertFalse((self.base / 'chromium_versions/selection.json').exists())

    def test_compressed_corrupt_data_is_reported_as_a_version_error(self):
        stream = io.BytesIO()
        name = 'chrome-win64/chrome.exe'
        with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(name, executable())
        data = bytearray(stream.getvalue())
        # A stored-block DEFLATE header with its deliberately wrong complement.
        data[30 + len(name):30 + len(name) + 5] = b'\x01\xff\xff\xff\xff'
        self.responses[asset_url(VERSION, 'chrome')] = bytes(data)
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.no_staging()

    def test_missing_selected_files_fall_back_to_bundled_and_report_error(self):
        installed = self.manager.install(VERSION)
        self.manager.select(VERSION)
        Path(installed['driver_path']).unlink()
        snapshot = self.manager.snapshot()
        self.assertEqual(snapshot['selected'], 'bundled')
        self.assertEqual(snapshot['requested_selected'], VERSION)
        self.assertTrue(snapshot['selection_error'])
        self.assertEqual(self.manager.active_paths()[0], self.base / 'Bro/chrome.exe')
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.select(VERSION)

    def test_invalid_selection_metadata_never_becomes_a_path(self):
        root = self.base / 'chromium_versions'
        root.mkdir()
        (root / 'selection.json').write_text('{"schema":1,"selected":"../../outside"}')
        self.assertEqual(self.manager.snapshot()['selected'], 'bundled')
        self.assertTrue(self.manager.snapshot()['selection_error'])

    def test_running_managed_browser_or_driver_blocks_switch_and_delete(self):
        installed = self.manager.install(VERSION)
        self.add_version(OTHER)
        self.manager.install(OTHER)
        for path in (installed['chrome_path'], installed['driver_path'], str(self.base / 'Bro/chrome.exe')):
            process = SimpleNamespace(info={'exe': path, 'name': Path(path).name})
            with patch.object(cv.psutil, 'process_iter', return_value=[process]):
                with self.subTest(path=path), self.assertRaisesRegex(cv.ChromiumVersionError, 'running'):
                    self.manager.select(OTHER)
        process = SimpleNamespace(info={'exe': installed['chrome_path'], 'name': 'chrome.exe'})
        with patch.object(cv.psutil, 'process_iter', return_value=[process]), \
                self.assertRaisesRegex(cv.ChromiumVersionError, 'running'):
            self.manager.delete(VERSION)
        self.assertTrue(Path(installed['chrome_path']).exists())

    def test_failed_atomic_selection_write_preserves_previous_selection(self):
        self.manager.install(VERSION)
        self.manager.select(VERSION)
        with patch.object(cv.os, 'replace', side_effect=OSError('disk full')), self.assertRaises(cv.ChromiumVersionError):
            self.manager.select('bundled')
        self.assertEqual(self.manager.snapshot()['selected'], VERSION)
        self.assertEqual(list((self.base / 'chromium_versions').glob('.selection-*')), [])

    def test_external_junction_or_symlink_is_not_used_as_version_store(self):
        outside = self.base / 'outside'
        outside.mkdir()
        root = self.base / 'chromium_versions'
        try:
            root.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest('Creating a directory symlink requires Windows developer mode or privilege')
        with self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.assertEqual(list(outside.iterdir()), [])

    def test_windows_reparse_attribute_blocks_store_without_symlink_privilege(self):
        root = self.base / 'chromium_versions'
        root.mkdir()
        original = Path.lstat
        def lstat(path, *args, **kwargs):
            result = original(path, *args, **kwargs)
            if path == root:
                return SimpleNamespace(st_mode=result.st_mode, st_file_attributes=0x400)
            return result
        with patch.object(Path, 'lstat', lstat), self.assertRaises(cv.ChromiumVersionError):
            self.manager.install(VERSION)
        self.assertEqual(list(root.iterdir()), [])


@unittest.skipUnless(os.name == 'nt', 'Windows version resources')
class NativeVersionResourceTests(unittest.TestCase):
    def test_reads_existing_python_version_without_executing_it(self):
        self.assertRegex(cv._file_version(Path(sys.executable)), r'^\d+\.\d+\.\d+\.\d+$')


if __name__ == '__main__':
    unittest.main()
