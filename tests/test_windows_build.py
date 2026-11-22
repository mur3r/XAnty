"""The Windows build includes UI assets and has no console window."""
import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch


path = Path(__file__).resolve().parents[1] / "tools" / "build_windows.py"
spec = importlib.util.spec_from_file_location("xanty_windows_build", path)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class WindowsBuildTests(unittest.TestCase):
    def test_build_command_packages_native_window_and_static_assets(self):
        with patch.object(builder.importlib.util, "find_spec", return_value=object()), \
             patch.object(builder.subprocess, "run") as launch:
            exe = builder.build()
        args = launch.call_args.args[0]
        self.assertIn("--windowed", args)
        self.assertIn("--add-data", args)
        self.assertIn("xgenius/web/static", args[args.index("--add-data") + 1])
        self.assertEqual(exe.name, "XAnty.exe")


if __name__ == "__main__":
    unittest.main()
