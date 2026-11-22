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
