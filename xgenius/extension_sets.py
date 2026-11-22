"""Local, portable presets of unpacked Manifest V3 Chrome extensions.

Only managed copies are modified. Existing manifest public keys are retained;
keyless extensions receive a public RSA key in their managed manifest, keeping
their Chrome ID stable when profiles move to another computer. The private key
is discarded: this feature does not sign, download, or publish extensions.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


_SET_ID = re.compile(r'^[a-f0-9]{32}$')
_EXTENSION_ID = re.compile(r'^[a-p]{32}$')
_VERSION = re.compile(r'^(0|[1-9][0-9]*)(\.(0|[1-9][0-9]*)){0,3}$')
_LOCK = threading.RLock()
_RESERVED = {'CON', 'PRN', 'AUX', 'NUL', *[f'COM{i}' for i in range(1, 10)],
             *[f'LPT{i}' for i in range(1, 10)]}


class ExtensionSetError(ValueError):
    """A preset cannot be validated, copied, or safely published."""


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def _plain_path(path: Path, *, missing=False) -> None:
    """Check parents too: resolving first would hide a junction or symlink."""
    for item in reversed((path, *path.parents)):
        try:
            if _linked(item):
                raise ExtensionSetError('Symbolic links and Windows reparse points are not supported')
        except FileNotFoundError:
            if not missing:
                raise ExtensionSetError(f'Extension path does not exist: {path}')


def _path(value) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise ExtensionSetError('Choose a local unpacked extension directory')
    raw = str(value)
    if '\x00' in raw or '..' in PureWindowsPath(raw).parts or '..' in PurePosixPath(raw).parts:
        raise ExtensionSetError('Path traversal is not supported')
    result = Path(os.path.abspath(raw))
    _plain_path(result, missing=True)
    return result


def _filename(name: str) -> None:
    if (not name or name in ('.', '..') or any(c in name for c in ':\\/')
            or name.endswith((' ', '.')) or any(ord(c) < 32 for c in name)
            or name.split('.')[0].upper() in _RESERVED):
        raise ExtensionSetError('Unsafe filename in extension directory')


def _tree(root: Path):
    _plain_path(root)
    if not root.is_dir():
        raise ExtensionSetError('Choose a directory containing manifest.json')
    for directory, folders, files in os.walk(root, followlinks=False):
        parent = Path(directory)
        _plain_path(parent)
        seen = set()
        for name in sorted([*folders, *files]):
            _filename(name)
            if name.casefold() in seen:
                raise ExtensionSetError('Duplicate filenames in extension directory')
            seen.add(name.casefold())
            path = parent / name
            if _linked(path):
                raise ExtensionSetError('Symbolic links and Windows reparse points are not supported')
            mode = path.stat().st_mode
            if not stat.S_ISREG(mode) and not stat.S_ISDIR(mode):
                raise ExtensionSetError('Only regular files and directories are supported')
            yield path, stat.S_ISDIR(mode)


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExtensionSetError('Duplicate property in extension JSON')
        result[key] = value
    return result


def _json(path: Path) -> dict:
    _plain_path(path)
    if not path.is_file() or path.stat().st_size > 4 * 1024 * 1024:
        raise ExtensionSetError('Missing or oversized extension manifest or preset metadata')
    try:
        value = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_json)
    except (ValueError, UnicodeError) as exc:
        raise ExtensionSetError(f'Invalid JSON in {path.name}') from exc
    if not isinstance(value, dict):
        raise ExtensionSetError(f'{path.name} must contain a JSON object')
    return value


def _key_bytes(key: str) -> bytes:
    if not isinstance(key, str) or not key or len(key) > 65536:
        raise ExtensionSetError('Invalid extension manifest public key')
    try:
        data = base64.b64decode(''.join(key.split()), validate=True)
        serialization.load_der_public_key(data)
        return data
    except (ValueError, TypeError) as exc:
        raise ExtensionSetError('Invalid extension manifest public key') from exc


def _extension_id(key: str) -> str:
    digest = hashlib.sha256(_key_bytes(key)).hexdigest()[:32]
    return ''.join(chr(ord('a') + int(character, 16)) for character in digest)


def _new_key() -> str:
    public = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    return base64.b64encode(public.public_bytes(serialization.Encoding.DER,
                                               serialization.PublicFormat.SubjectPublicKeyInfo)).decode('ascii')


def _resource(root: Path, value, *, wildcard=False) -> None:
    if not isinstance(value, str) or not value:
        raise ExtensionSetError('Invalid extension manifest resource path')
    parts = value.split('/')
    if ('\\' in value or PureWindowsPath(value).is_absolute() or value.startswith('/')
            or any(p in ('', '.', '..') or ':' in p or '\x00' in p for p in parts)):
        raise ExtensionSetError('Unsafe extension manifest resource path')
    if '*' in value or '?' in value:
        if not wildcard:
            raise ExtensionSetError('Invalid extension manifest resource path')
        return
    file = root.joinpath(*parts)
    _plain_path(file)
    if not file.is_file():
        raise ExtensionSetError(f'Extension resource does not exist: {value}')


def _manifest(root: Path, *, require_key=False) -> dict:
    # Validate all files, including resources not explicitly listed in the manifest.
    for _ in _tree(root):
        pass
    data = _json(root / 'manifest.json')
    if type(data.get('manifest_version')) is not int or data['manifest_version'] != 3:
        raise ExtensionSetError('Only Manifest V3 extensions are supported by current Chrome')
    name, version = data.get('name'), data.get('version')
    if not isinstance(name, str) or not name.strip() or len(name) > 75:
        raise ExtensionSetError('Extension manifest requires a valid name')
    if (not isinstance(version, str) or not _VERSION.fullmatch(version)
            or any(int(p) > 65535 for p in version.split('.')) or not any(int(p) for p in version.split('.'))):
        raise ExtensionSetError('Extension manifest requires a valid version')
    if 'key' in data:
        _key_bytes(data['key'])
    elif require_key:
        raise ExtensionSetError('Managed extension is missing its stable public key')
    for field in ('permissions', 'optional_permissions', 'host_permissions', 'optional_host_permissions'):
        if field in data and (not isinstance(data[field], list) or any(not isinstance(v, str) for v in data[field])):
            raise ExtensionSetError(f'Invalid extension manifest {field}')
    for field in ('options_page', 'devtools_page'):
        if field in data:
            _resource(root, data[field])
    for field, properties in (('background', ('service_worker',)), ('action', ('default_popup',)),
                              ('options_ui', ('page',))):
        if field in data:
            if not isinstance(data[field], dict):
                raise ExtensionSetError(f'Invalid extension manifest {field}')
            for property_name in properties:
                if property_name in data[field]:
                    _resource(root, data[field][property_name])
    for field in ('icons', 'chrome_url_overrides'):
        if field in data:
            if not isinstance(data[field], dict):
                raise ExtensionSetError(f'Invalid extension manifest {field}')
            for resource in data[field].values():
                _resource(root, resource)
    for field in ('content_scripts', 'web_accessible_resources'):
        if field not in data:
            continue
        if not isinstance(data[field], list):
            raise ExtensionSetError(f'Invalid extension manifest {field}')
        for item in data[field]:
            if not isinstance(item, dict):
                raise ExtensionSetError(f'Invalid extension manifest {field}')
            for property_name in (('js', 'css') if field == 'content_scripts' else ('resources',)):
                if property_name in item:
                    if not isinstance(item[property_name], list):
                        raise ExtensionSetError(f'Invalid extension manifest {field}')
                    for resource in item[property_name]:
                        _resource(root, resource, wildcard=field == 'web_accessible_resources')
    return data


def _copy_tree(source: Path, target: Path) -> None:
    target.mkdir()
    for path, directory in _tree(source):
        output = target / path.relative_to(source)
        if directory:
            output.mkdir()
        else:
            # Validate again directly before opening; never retain links in copies.
            _plain_path(path)
            before = path.stat()
            with path.open('rb') as reader, output.open('xb') as writer:
                opened = os.fstat(reader.fileno())
                if (before.st_ino, before.st_dev) != (opened.st_ino, opened.st_dev):
                    raise ExtensionSetError('Extension files changed during copying; retry')
                shutil.copyfileobj(reader, writer, 1024 * 1024)


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')


def _name(value) -> str:
    if (not isinstance(value, str) or not value.strip() or len(value.strip()) > 128
            or any(ord(c) < 32 for c in value)):
        raise ExtensionSetError('Preset name must contain 1 to 128 characters without control characters')
    return value.strip()


def _set_id(value) -> str:
    if not isinstance(value, str) or not _SET_ID.fullmatch(value):
        raise ExtensionSetError('Invalid extension preset ID')
    return value


def _public(metadata: dict) -> dict:
    return {'id': metadata['id'], 'name': metadata['name'], 'extensions': [
        {field: item[field] for field in ('name', 'version', 'id')} for item in metadata['extensions']]}


def _read_preset(root: Path, preset_id: str) -> dict:
    _plain_path(root)
    data = _json(root / 'preset.json')
    if data.get('version') != 1 or data.get('id') != preset_id:
        raise ExtensionSetError('Invalid extension preset metadata')
    _name(data.get('name'))
    items = data.get('extensions')
    if not isinstance(items, list) or not items:
        raise ExtensionSetError('Extension preset contains no extensions')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('id'), str) or not _EXTENSION_ID.fullmatch(item['id']):
            raise ExtensionSetError('Invalid extension ID in preset')
        if item['id'] in seen:
            raise ExtensionSetError('Duplicate extension ID in preset')
        seen.add(item['id'])
        manifest = _manifest(root / 'extensions' / item['id'], require_key=True)
        if (item.get('name') != manifest['name'] or item.get('version') != manifest['version']
                or item['id'] != _extension_id(manifest['key'])):
            raise ExtensionSetError('Extension preset does not match its manifest')
    # Metadata may never hide linked/unvalidated auxiliary files from materialize.
    for _ in _tree(root):
        pass
    return data


def _remove(directory: Path, parent: Path) -> None:
    # Recursive deletion is restricted to verified direct children of our root.
    if directory.parent != parent or directory == parent:
        raise ExtensionSetError('Unsafe extension cleanup path')
    _plain_path(directory, missing=True)
    if directory.exists():
        for _ in _tree(directory):
            pass
        shutil.rmtree(directory)


def _publish(stage: Path, target: Path) -> None:
    backup = target.parent / ('.backup-' + uuid.uuid4().hex)
    existed = target.exists()
    if existed:
        # Inspect the whole old snapshot before moving it. Otherwise a nested
        # junction could be discovered only during backup cleanup, after commit.
        for _ in _tree(target):
            pass
        os.replace(target, backup)
    try:
        os.replace(stage, target)
    except BaseException:
        if existed:
            os.replace(backup, target)
        raise
    if existed:
        _remove(backup, target.parent)


class ExtensionSetStore:
    def __init__(self, config):
        self.root = _path(Path(config.base_dir) / 'extension_sets')

    def list(self) -> list[dict]:
        with _LOCK:
            _plain_path(self.root, missing=True)
            if not self.root.exists():
                return []
            try:
                presets = [_public(_read_preset(path, path.name)) for path in sorted(self.root.iterdir())
                           if _SET_ID.fullmatch(path.name)]
                return sorted(presets, key=lambda p: (p['name'].casefold(), p['id']))
            except OSError as exc:
                raise ExtensionSetError('Could not read extension presets') from exc

    def save(self, name: str, directories: list[str], preset_id: str | None = None) -> dict:
        name = _name(name)
        if not isinstance(directories, list) or not directories:
            raise ExtensionSetError('Choose at least one unpacked extension directory')
        with _LOCK:
            stage = None
            try:
                identifier = _set_id(preset_id) if preset_id is not None else uuid.uuid4().hex
                target = self.root / identifier
                previous = _read_preset(target, identifier) if preset_id is not None else None
                sources, seen = [], set()
                for value in directories:
                    if not isinstance(value, str):
                        raise ExtensionSetError('Choose local unpacked extension directories')
                    source = _path(value)
                    canonical = os.path.normcase(str(source))
                    if canonical in seen:
                        raise ExtensionSetError('Duplicate extension directory')
                    seen.add(canonical)
                    if source == self.root or source in self.root.parents or self.root in source.parents:
                        raise ExtensionSetError('Choose an extension outside the managed preset directory')
                    sources.append((source, canonical, _manifest(source)))
                _plain_path(self.root, missing=True)
                self.root.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.root))
                (stage / 'extensions').mkdir()
                metadata = {'version': 1, 'id': identifier, 'name': name, 'extensions': []}
                old_keys = {}
                if previous:
                    for item in previous['extensions']:
                        old_keys[item.get('source')] = _json(target / 'extensions' / item['id'] / 'manifest.json')['key']
                used = set()
                for source, canonical, manifest in sources:
                    manifest = dict(manifest)
                    if 'key' not in manifest:
                        manifest['key'] = old_keys.get(canonical) or _new_key()
                    extension_id = _extension_id(manifest['key'])
                    if extension_id in used:
                        raise ExtensionSetError('Two selected extensions have the same Chrome extension ID')
                    used.add(extension_id)
                    destination = stage / 'extensions' / extension_id
                    _copy_tree(source, destination)
                    _write_json(destination / 'manifest.json', manifest)
                    metadata['extensions'].append({'name': manifest['name'], 'version': manifest['version'],
                                                   'id': extension_id, 'source': canonical})
                _write_json(stage / 'preset.json', metadata)
                _read_preset(stage, identifier)
                _publish(stage, target)
                return _public(metadata)
            except OSError as exc:
                raise ExtensionSetError('Could not save extension preset; check disk space and write access') from exc
            finally:
                if stage is not None:
                    _remove(stage, self.root)

    def delete(self, preset_id: str) -> None:
        identifier = _set_id(preset_id)
        with _LOCK:
            try:
                target = self.root / identifier
                _read_preset(target, identifier)
                _remove(target, self.root)
            except OSError as exc:
                raise ExtensionSetError('Could not delete extension preset') from exc

    def materialize(self, preset_id: str, profile_dir: Path) -> list[Path]:
        """Prepare the selected preset; an empty selection disables loading.

        Deselection preserves portable files. A selected ID can still load its
        in-profile snapshot after transfer or deletion of the global preset.
        """
        if not preset_id:
            return []
        with _LOCK:
            stage = None
            profile = _path(profile_dir)
            managed = profile / 'XAntyExtensions'
            try:
                _plain_path(managed, missing=True)
                identifier = _set_id(preset_id)
                source = self.root / identifier
                _plain_path(source, missing=True)
                if not source.exists():
                    # Imported profiles carry the preset themselves, even if the
                    # destination computer never had that global preset.
                    transferred = managed / identifier
                    metadata = _read_preset(transferred, identifier)
                    return [transferred / 'extensions' / item['id'] for item in metadata['extensions']]
                metadata = _read_preset(source, identifier)
                profile.mkdir(parents=True, exist_ok=True)
                stage = Path(tempfile.mkdtemp(prefix='.stage-', dir=profile))
                destination = stage / identifier
                _copy_tree(source, destination)
                # Source paths are local editing metadata and do not travel.
                portable = {'version': 1, **_public(metadata)}
                _write_json(destination / 'preset.json', portable)
                _read_preset(destination, identifier)
                _publish(stage, managed)
                return [managed / identifier / 'extensions' / item['id'] for item in metadata['extensions']]
            except OSError as exc:
                raise ExtensionSetError('Could not prepare profile extensions; check disk space and write access') from exc
            finally:
                if stage is not None:
                    _remove(stage, profile)
