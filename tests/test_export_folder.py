import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from xgenius.config import Config
from xgenius.desktop import DesktopApi
from xgenius.profile_archive import ArchiveError, export_package
from xgenius.transfer_storage import export_directory, publish_export


class ExportFolderTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = Config(self.root / 'workspace')
        self.staged = self.root / 'staged.tmp'
        export_package(self.config, [{'username': 'alice'}], self.staged)
        self.destination = self.root / 'profiles.xanty'

    def test_destination_validation_and_verified_publication(self):
        self.assertIsNone(export_directory(''))
        self.assertEqual(export_directory(str(self.root)), self.root.resolve())
        self.assertEqual(publish_export(self.staged, self.destination), str(self.destination))
        self.assertFalse(self.staged.exists())
        self.assertTrue(self.destination.exists())

    def test_existing_files_are_never_overwritten(self):
        self.destination.write_bytes(b'Keep this file')
        with self.assertRaises(FileExistsError):
            publish_export(self.staged, self.destination)
        self.assertEqual(self.destination.read_bytes(), b'Keep this file')
        self.assertTrue(self.staged.exists())

    def test_cancelled_or_invalid_packages_never_become_final_exports(self):
        with self.assertRaises(ArchiveError):
            publish_export(self.staged, self.destination, cancelled=lambda: True)
        self.assertFalse(self.destination.exists())
        self.staged.write_bytes(b'Broken archive')
        with self.assertRaises(ArchiveError):
            publish_export(self.staged, self.destination)
        self.assertFalse(self.destination.exists())

    def test_native_picker_returns_selected_folder_or_cancel_without_changing_files(self):
        bridge = DesktopApi()
        bridge._window = Mock()
        bridge._window.create_file_dialog.return_value = (str(self.root),)
        module = SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=20))
        with patch.dict('sys.modules', {'webview': module}):
            self.assertEqual(bridge.choose_folder(str(self.root)), str(self.root))
            bridge._window.create_file_dialog.assert_called_once_with(20, directory=str(self.root), allow_multiple=False)
            bridge._window.create_file_dialog.return_value = None
            self.assertIsNone(bridge.choose_folder())
            bridge._closing.set()
            bridge._window.create_file_dialog.reset_mock()
            self.assertIsNone(bridge.choose_folder())
            bridge._window.create_file_dialog.assert_not_called()
