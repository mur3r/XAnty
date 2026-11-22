"""Logical folders remain available after restart and keep old group labels."""
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


path = Path(__file__).resolve().parents[1] / "xgenius" / "folders.py"
spec = importlib.util.spec_from_file_location("xanty_folders", path)
folders = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = folders
spec.loader.exec_module(folders)


class FolderTests(unittest.TestCase):
    def test_empty_folder_and_existing_groups_survive_restart(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "folders.json"
            store = folders.FolderStore(path)
            store.sync(["Old group", "Other group", "Old group"])
            store.create("Empty folder")
            self.assertEqual(folders.FolderStore(path).list(), ["Old group", "Other group", "Empty folder"])

    def test_rename_delete_and_duplicate_guards(self):
        with tempfile.TemporaryDirectory() as root:
            store = folders.FolderStore(Path(root) / "folders.json")
            store.create("Models")
            with self.assertRaises(folders.FolderError):
                store.create("models")
            store.rename("Models", "New models")
            self.assertEqual(store.get("NEW MODELS"), "New models")
            store.delete("New models")
            self.assertEqual(store.list(), [])

    def test_reject_invalid_folder_names(self):
        for name in ("", "  ", "__none__", "one/two", "one\\two", "a" * 65):
            with self.subTest(name=name), self.assertRaises(folders.FolderError):
                folders.folder_name(name)


if __name__ == "__main__":
    unittest.main()
