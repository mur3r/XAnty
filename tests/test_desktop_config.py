"""The packaged app persists its selected data directory outside the EXE bundle."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "xgenius" / "config.py"
spec = importlib.util.spec_from_file_location("desktop_config", path)
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class DesktopConfigTests(unittest.TestCase):
    def test_installed_browser_is_used_without_overriding_workspace_binaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / 'application/XAnty.exe'
            runtime = app.parent / 'runtime'
            for relative in ('Bro/chrome.exe', 'Drivers/chromedriver.exe'):
                target = runtime / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'MZtest')
            workspace = root / 'workspace'
            with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', str(app)):
                self.assertEqual(config.get_paths_from_base(workspace), (runtime/'Bro/chrome.exe', runtime/'Drivers/chromedriver.exe'))
                local = workspace / 'Bro/chrome.exe'
                local.parent.mkdir(parents=True)
                local.write_bytes(b'MZexisting')
                self.assertEqual(config.get_paths_from_base(workspace)[0], local)

    def test_frozen_app_saves_selection_in_local_app_data(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(sys, "frozen", True, create=True), patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                selected = Path(directory) / "profiles"
                config.save_base_dir(selected)
                self.assertEqual(config.paths_file(), Path(directory) / "XAnty" / "paths.json")
                self.assertEqual(config.read_saved_base_dir(), selected)
                self.assertEqual(config.default_base_dir(), Path(directory) / "XAnty" / "data")


if __name__ == "__main__":
    unittest.main()
