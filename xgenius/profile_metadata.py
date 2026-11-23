"""Profile metadata, trash and audit stored in the atomic accounts document."""
import copy
import getpass
import shutil
import uuid
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone

from xgenius.proxy_service import ProxyCheckError, parse_proxy
from xgenius.profile_leases import ProfileLease

STATUSES = ('active', 'new', 'review', 'unused')
COLUMNS = ('number', 'name', 'start', 'profile_status', 'status', 'proxy', 'auto_login',
           'last_launch', 'runtime', 'tags', 'notes', 'group','profile_size','reminder')
DEFAULT_COLUMNS = list(COLUMNS[:9])
TRACKED = ('username', 'profile_name', 'notes', 'tags', 'group', 'proxy', 'password',
           'auth_token', 'ct0_token', 'auto_login', 'browser_language', 'browser_timezone',
           'window_width', 'window_height', 'headless', 'profile_status', 'favorite')
TRACKED += ('restore_tabs','extension_set','icon_text')
TRACKED += ('important','reminder_at','reminder_note')
TRACKED += ('block_images','block_media','block_fonts','phishing_protection')
SECRET_FIELDS = {'password', 'auth_token', 'ct0_token'}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def name_key(name):
    """Windows folds case and ignores trailing dots/spaces in ordinary paths."""
    return name.rstrip(' .').casefold()


def retention_days(value):
    if type(value) is not int or not 0 <= value <= 3650:
        raise ValueError('Срок хранения: целое число от 0 до 3650 дней (0 — бессрочно).')
    return value


def deadline(deleted_at, days):
    return (datetime.fromisoformat(deleted_at) + timedelta(days=days)).isoformat() if days else None


def metadata_values(data):
    if not isinstance(data, dict) or set(data) - {'profile_name', 'profile_status', 'favorite', 'tags', 'notes',
                                               'important','reminder_at','reminder_note','icon_text'}:
        raise ValueError('Invalid profile metadata')
    result = dict(data)
    if 'icon_text' in data:
        text=data['icon_text']
        if not isinstance(text,str) or len(text)>8 or any(ord(c)<32 or 0x7f<=ord(c)<0xa0 for c in text):
            raise ValueError('Icon text must contain up to 8 printable characters')
        result['icon_text']=text.strip()
    if 'profile_status' in data and data['profile_status'] not in STATUSES:
        raise ValueError('Invalid profile status')
    if 'favorite' in data and type(data['favorite']) is not bool:
        raise ValueError('favorite must be a boolean')
    if 'important' in data and type(data['important']) is not bool:
        raise ValueError('important must be a boolean')
    if 'reminder_at' in data:
        stamp=data['reminder_at']
        if stamp in ('',None):result['reminder_at']=None
        else:
            try:
                parsed=datetime.fromisoformat(stamp.replace('Z','+00:00'))
                if parsed.tzinfo is None:raise ValueError('Timezone required')
                result['reminder_at']=parsed.astimezone(timezone.utc).isoformat()
            except (TypeError,AttributeError,ValueError):raise ValueError('Reminder must contain a valid date with timezone') from None
    if 'reminder_note' in data and (not isinstance(data['reminder_note'],str) or len(data['reminder_note'])>2000):
        raise ValueError('Invalid reminder note')
    for key in ('profile_name', 'notes'):
        if key in data:
            if not isinstance(data[key], str) or len(data[key]) > (200 if key == 'profile_name' else 10000):
                raise ValueError('Invalid profile name or notes')
            result[key] = data[key].strip() if key == 'profile_name' else data[key]
            if key == 'profile_name' and not result[key]:
                raise ValueError('Profile name cannot be empty')
    if 'tags' in data:
        tags = data['tags'].split(',') if isinstance(data['tags'], str) else data['tags']
        if not isinstance(tags, list) or len(tags) > 100 or any(not isinstance(t, str) or len(t) > 100 for t in tags):
            raise ValueError('Invalid profile tags')
        result['tags'] = list(dict.fromkeys(t.strip() for t in tags if t.strip()))
    return result


def migrate(document):
    document.setdefault('accounts', [])
    document.setdefault('trash', [])
    document.setdefault('history', [])
    records = document['accounts'] + document['trash']
    number = max([document.get('next_number', 1)] + [a.get('profile_number', 0) + 1 for a in records])
    for account in records:
        account.setdefault('profile_id', uuid.uuid4().hex)
        if not account.get('profile_number'):
            account['profile_number'] = number
            number += 1
        account.setdefault('profile_status', 'new')
        account.setdefault('favorite', False)
        account.setdefault('runtime_seconds', 0)
        account.setdefault('runtime_checkpoint', None)
        account.setdefault('last_launch', None)
    document['next_number'] = number
    return document


def safe_value(key, value):
    if key in SECRET_FIELDS:
        return '••••' if value else ''
    if key == 'proxy' and value:
        try:
            return parse_proxy(value).server
        except (ProxyCheckError, TypeError):
            return '••••'
    return copy.deepcopy(value)


def event(document, account, action, changes=None, actor=None):
    document['history'].append({
        'id': uuid.uuid4().hex, 'at': now_iso(), 'actor': actor or getpass.getuser(),
        'profile_id': account['profile_id'], 'username': account['username'],
        'profile_name': account.get('profile_name') or account.get('dolphin_name') or account['username'],
        'action': action, 'changes': changes or {},
    })


def replace_accounts(document, accounts):
    """Apply normal CRUD with its audit events in one document replacement."""
    document = migrate(copy.deepcopy(document))
    before = {a['profile_id']: a for a in document['accounts']}
    by_name = {name_key(a['username']): a for a in document['accounts']}
    names = {a['username'] for a in accounts}
    if len({name_key(n) for n in names}) != len(accounts):
        raise ValueError('A profile with this name already exists.')
    reserved = {name_key(a['username']) for a in document['trash']}
    for account in accounts:
        if name_key(account['username']) in reserved:
            raise ValueError('Профиль с этим именем находится в корзине. Сначала восстановите или удалите его окончательно.')
        previous = by_name.get(name_key(account['username']))
        identity = before.get(account.get('profile_id'))
        if previous is None and identity and identity['username'] not in names:
            previous = identity
        if previous:
            account['profile_id'] = previous['profile_id']
            account['profile_number'] = previous['profile_number']
            # CRUD may save a snapshot taken before a maintenance checkpoint.
            for key in ('runtime_seconds', 'runtime_checkpoint', 'last_launch'):
                account[key] = previous.get(key)
        elif account.get('profile_id') not in before or before[account['profile_id']]['username'] in names:
            # A package copy has a new local identity, even if it carries the source UUID.
            account.pop('profile_id', None)
            account.pop('profile_number', None)
            account['runtime_checkpoint'] = None
    document['accounts'] = copy.deepcopy(accounts)
    migrate(document)
    for account in document['accounts']:
        previous = before.get(account['profile_id'])
        if previous is None:
            event(document, account, 'created')
            continue
        changes = {key: {'before': safe_value(key, previous.get(key)), 'after': safe_value(key, account.get(key))}
                   for key in TRACKED if previous.get(key) != account.get(key)}
        if changes:
            event(document, account, 'updated', changes)
    return document


def elapsed(checkpoint, end):
    return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(checkpoint)).total_seconds()) if checkpoint else 0


def record_session_time(manager, username, opened=False):
    """Accounting must never prevent the browser from opening or closing."""
    try:
        getattr(manager, 'start_profile_session' if opened else 'finish_profile_session', lambda u: None)(username)
    except Exception as exc:
        manager.logger.error(f'Could not save profile runtime: {type(exc).__name__}', username)


def apply_session_times(document, pending, checkpoint_at=None):
    """Apply queued lifecycle events to stable identities before any JSON commit."""
    active_ids = {a.get('profile_id') for a in document.get('accounts', [])}
    for account in document.get('accounts', []) + document.get('trash', []):
        for operation, stamp in pending.get(account.get('profile_id'), []):
            checkpoint = account.get('runtime_checkpoint')
            if checkpoint:
                account['runtime_seconds'] += elapsed(checkpoint, stamp)
                account['runtime_checkpoint'] = stamp if operation == 'start' else None
            elif operation == 'start':
                account.update(last_launch=stamp, runtime_checkpoint=stamp)
        if checkpoint_at and account.get('profile_id') in active_ids and account.get('runtime_checkpoint'):
            account['runtime_seconds'] += elapsed(account['runtime_checkpoint'], checkpoint_at)
            account['runtime_checkpoint'] = checkpoint_at


class ProfileMetadataMixin:
    def window_sets(self):
        with self._data_lock:
            return self._read_document().get('window_sets',[])

    def save_window_set(self,name,usernames,set_id=None):
        if not isinstance(name,str) or not name.strip() or len(name)>80 or any(ord(c)<32 for c in name):
            raise ValueError('Invalid window set name')
        with self._data_lock:
            doc=migrate(self._read_document())
            selected=self._select_profiles(doc['accounts'],usernames)
            if len(selected)>500:raise ValueError('A window set can contain at most 500 profiles')
            ids={a['username']:a['profile_id'] for a in selected}
            sets=doc.setdefault('window_sets',[])
            previous=next((s for s in sets if s['id']==set_id),None)
            if set_id and previous is None:raise ValueError('Window set not found')
            if any(s['name'].casefold()==name.strip().casefold() and s['id']!=set_id for s in sets):
                raise ValueError('A window set with this name already exists')
            saved={'id':set_id or uuid.uuid4().hex,'name':name.strip(),
                   'profile_ids':[ids[u] for u in dict.fromkeys(usernames)],'updated_at':now_iso()}
            if previous:sets[sets.index(previous)]=saved
            else:sets.append(saved)
            self._write_document(doc)
            return saved

    def delete_window_set(self,set_id):
        with self._data_lock:
            doc=self._read_document();sets=doc.get('window_sets',[])
            if not any(s['id']==set_id for s in sets):raise ValueError('Window set not found')
            doc['window_sets']=[s for s in sets if s['id']!=set_id];self._write_document(doc)

    def resolve_window_set(self,set_id):
        with self._data_lock:
            doc=self._read_document();record=next((s for s in doc.get('window_sets',[]) if s['id']==set_id),None)
            if record is None:raise ValueError('Window set not found')
            names={a.get('profile_id'):a['username'] for a in doc.get('accounts',[])}
            if any(p not in names for p in record['profile_ids']):
                raise ValueError('A window set contains a missing or trashed profile. Edit the set first.')
            return [names[p] for p in record['profile_ids']]

    def reserved_profile_names(self):
        with self._data_lock:
            doc = self._read_document()
            return {name_key(a['username']) for a in doc.get('accounts', []) + doc.get('trash', [])}

    def initialize_profile_metadata(self):
        with self._data_lock:
            self._pending_session_times = {}
            document = migrate(self._read_document())
            # After a crash retain the last checkpoint, never add application downtime.
            for a in document['accounts']:
                a['runtime_checkpoint'] = None
            self._write_document(document)

    def update_profile_metadata(self, names, data):
        values = metadata_values(data)
        with self._data_lock:
            accounts = self.load_accounts()
            selected = self._select_profiles(accounts, names)
            for account in selected:
                account.update(values)
            self.save_accounts(accounts)
        return len(selected)

    @staticmethod
    def _select_profiles(accounts, names):
        names = set(names)
        if not names or names - {a['username'] for a in accounts}:
            raise ValueError('One or more selected profiles no longer exist.')
        return [a for a in accounts if a['username'] in names]

    def profile_history(self, username=None):
        with self._data_lock:
            doc = self._read_document()
            records = doc.get('accounts', []) + doc.get('trash', [])
            ids = {a.get('profile_id') for a in records if a['username'] == username}
            rows = doc.get('history', [])
            return [e for e in reversed(rows) if username is None or
                    (e['profile_id'] in ids if ids else e['username'] == username)]

    def trash_rows(self):
        with self._data_lock:
            return [{k: a.get(k) for k in ('username', 'profile_id', 'profile_number', 'profile_name',
                                          'deleted_at', 'delete_after', 'retention_days', 'group', 'important', 'favorite')}
                    for a in self._read_document().get('trash', [])]

    def trash_profiles(self, names, days=30):
        days = retention_days(days)
        with self._data_lock:
            doc = migrate(self._read_document())
            selected = self._select_profiles(doc['accounts'], names)
            stamp = now_iso()
            for account in selected:
                account.update(deleted_at=stamp, delete_after=deadline(stamp, days), retention_days=days)
                event(doc, account, 'trashed')
            doc['trash'].extend(selected)
            doc['accounts'] = [a for a in doc['accounts'] if a not in selected]
            self._write_document(doc)
            return len(selected)

    def restore_profiles(self, names):
        with self._data_lock:
            doc = migrate(self._read_document())
            selected = self._select_profiles(doc['trash'], names)
            if {name_key(a['username']) for a in selected} & {name_key(a['username']) for a in doc['accounts']}:
                raise ValueError('A profile with this name already exists.')
            for account in selected:
                for key in ('deleted_at', 'delete_after', 'retention_days'):
                    account.pop(key, None)
                event(doc, account, 'restored')
            doc['accounts'].extend(selected)
            doc['trash'] = [a for a in doc['trash'] if a not in selected]
            self._write_document(doc)
            return len(selected)

    def set_trash_retention(self, names, days):
        days = retention_days(days)
        with self._data_lock:
            doc = migrate(self._read_document())
            selected = self._select_profiles(doc['trash'], names)
            for account in selected:
                old = account['retention_days']
                account.update(retention_days=days, delete_after=deadline(account['deleted_at'], days))
                if old != days:
                    event(doc, account, 'retention_changed', {'retention_days': {'before': old, 'after': days}})
            self._write_document(doc)
            return len(selected)

    def purge_trash(self, names=None):
        with self._data_lock:
            doc = migrate(self._read_document())
            selected = self._select_profiles(doc['trash'], names) if names is not None else [
                a for a in doc['trash'] if a.get('delete_after') and
                datetime.fromisoformat(a['delete_after']) <= datetime.fromisoformat(now_iso())]
            paths = []
            for account in selected:
                name = account['username']
                if name_key(name) in {name_key(a['username']) for a in doc['accounts']} or any(c in name for c in '/\\:\0'):
                    raise ValueError('Invalid profile path')
                for root, prefix in ((self.config.browser_profiles_dir, 'profile_'),
                                     (self.config.base_dir / 'kook', '@')):
                    root = root.resolve()
                    path = root / (prefix + name)
                    if path.resolve().parent != root or path.is_symlink():
                        raise ValueError('Invalid profile path')
                    paths.append(path)
            with ExitStack() as leases:
                for account in selected:
                    leases.enter_context(ProfileLease.acquire(self.config,account['username']))
                for path in paths:
                    if path.is_dir():
                        shutil.rmtree(path)
                    elif path.exists():
                        path.unlink()
            for account in selected:
                event(doc, account, 'purged', actor='system' if names is None else None)
            if selected:
                doc['trash'] = [a for a in doc['trash'] if a not in selected]
                self._write_document(doc)
            return len(selected)

    def start_profile_session(self, username):
        self._session_time(username, 'start')

    def finish_profile_session(self, username):
        self._session_time(username, 'finish')

    def checkpoint_sessions(self):
        self._session_time(None, 'checkpoint')

    def _session_time(self, username, operation):
        with self._data_lock:
            stamp = now_iso()
            doc = migrate(self._read_document())
            pending = getattr(self, '_pending_session_times', None)
            if pending is None:
                pending = self._pending_session_times = {}
            if operation in ('start', 'finish'):
                account = next((a for a in doc['accounts'] if a['username'] == username), None)
                if account is not None:
                    pending.setdefault(account['profile_id'], []).append((operation, stamp))
            if pending or (operation == 'checkpoint' and any(a.get('runtime_checkpoint') for a in doc['accounts'])):
                self._write_document(doc, checkpoint_at=stamp if operation == 'checkpoint' else None)
