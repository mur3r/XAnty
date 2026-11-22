"""Persistent logical folders for grouping browser profiles in the UI."""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path


class FolderError(ValueError):
    pass


def folder_name(value: str) -> str:
    if not isinstance(value, str):
        raise FolderError("Folder name must be text.")
    name = (value or "").strip()
    if not name or len(name) > 64 or name == "__none__" or any(ord(c) < 32 or c in "/\\" for c in name):
        raise FolderError("Folder name must be 1–64 characters and contain no slashes or control characters.")
    return name


class FolderStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.RLock()

    def list(self) -> list[str]:
        with self._lock:
            if not self.path.exists():
                return []
            with self.path.open("r", encoding="utf-8") as f:
                names = json.load(f).get("folders", [])
            if not isinstance(names, list) or any(not isinstance(n, str) for n in names):
                raise FolderError("Invalid folders.json file.")
            return names

    def _save(self, names: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent,
                                             prefix="folders_", suffix=".tmp", delete=False) as f:
                temporary = f.name
                json.dump({"folders": names}, f, ensure_ascii=False, indent=2)
            os.replace(temporary, self.path)
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, value: str) -> str:
        name = folder_name(value)
        return next((n for n in self.list() if n.casefold() == name.casefold()), "")

    def create(self, value: str) -> str:
        name = folder_name(value)
        with self._lock:
            names = self.list()
            if any(n.casefold() == name.casefold() for n in names):
                raise FolderError("A folder with this name already exists.")
            self._save([*names, name])
        return name

    def sync(self, groups) -> None:
        """Preserve group labels from older account files as folders."""
        with self._lock:
            names = self.list()
            seen = {n.casefold() for n in names}
            for group in groups:
                if not group:
                    continue
                try:
                    name = folder_name(group)
                except FolderError:
                    continue
                if name.casefold() not in seen:
                    names.append(name)
                    seen.add(name.casefold())
            if not self.path.exists() or len(names) != len(self.list()):
                self._save(names)

    def rename(self, old: str, new: str) -> str:
        new = folder_name(new)
        with self._lock:
            names = self.list()
            old = next((n for n in names if n == old), "")
            if not old:
                raise FolderError("Folder not found.")
            if any(n != old and n.casefold() == new.casefold() for n in names):
                raise FolderError("A folder with this name already exists.")
            names[names.index(old)] = new
            self._save(names)
        return new

    def delete(self, name: str) -> None:
        with self._lock:
            names = self.list()
            if name not in names:
                raise FolderError("Folder not found.")
            names.remove(name)
            self._save(names)
