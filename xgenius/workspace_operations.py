"""Profile footprint and conservative cleanup of owned stale update artifacts."""
import os
import re
import shutil
import sys
import time
from pathlib import Path
from datetime import datetime, timezone
from xgenius.cookies import get_cookies_file_path
from xgenius.profile_leases import profile_directory


def _linked(path):
    return path.is_symlink() or bool(getattr(path.lstat(),'st_file_attributes',0) & 0x400)


def _size(path):
    total=files=errors=0
    if not path.exists():return total,files,errors
    stack=[path];seen=set()
    while stack:
        item=stack.pop()
        try:
            if _linked(item):continue
            stat=item.stat();identity=(stat.st_dev,stat.st_ino)
            if identity in seen:continue
            seen.add(identity)
            if item.is_dir():
                with os.scandir(item) as entries:stack.extend(Path(e.path) for e in entries)
            elif item.is_file():total+=stat.st_size;files+=1
        except OSError:errors+=1
    return total,files,errors


def profile_size(config,username):
    roots=[profile_directory(config,username),get_cookies_file_path(config,username).parent]
    values=[_size(root) for root in roots]
    total=sum(v[0] for v in values)
    return {'bytes':total,'gb':total/(1024**3),'files':sum(v[1] for v in values),
            'partial':any(v[2] for v in values),'measured_at':datetime.now(timezone.utc).isoformat()}


def obsolete_files(config,updates_root,protected=(),now=None):
    now=time.time() if now is None else now
    excluded={str(Path(p).resolve()).casefold() for p in [*protected,sys.executable] if p}
    candidates=[]
    update_root=Path(updates_root)
    if update_root.exists() and not _linked(update_root):
        for path in update_root.iterdir():
            if re.fullmatch(r'XAnty-\d{4}(?:\.\d+){2,6}(?:\.exe(?:\.part)?|\.part)',path.name) or path.name=='last-check.tmp':
                candidates.append((path,update_root,'update'))
    base=config.base_dir
    for path in base.iterdir():
        if path.name.startswith(('.xanty-transfer-','.xanty-import-','.xanty-export-')):
            candidates.append((path,base,'staging'))
    result=[]
    for path,root,kind in candidates:
        try:
            if _linked(path) or path.resolve().parent!=root.resolve() or str(path.resolve()).casefold() in excluded:
                continue
            age=now-path.stat().st_mtime
            if age<7*86400:continue
            size,files,errors=_size(path)
            if errors:continue
            result.append({'path':str(path),'bytes':size,'files':files,'kind':kind,'age_days':int(age/86400)})
        except OSError:continue
    return {'files':result,'count':len(result),'bytes':sum(p['bytes'] for p in result)}


def clean_obsolete_files(config,updates_root,protected=(),now=None):
    preview=obsolete_files(config,updates_root,protected,now)
    for record in preview['files']:
        path=Path(record['path'])
        if _linked(path):raise ValueError('Unsafe cleanup path')
        if path.is_dir():
            if any(_linked(item) for item in path.rglob('*')):raise ValueError('Unsafe link in temporary files')
            shutil.rmtree(path)
        else:path.unlink()
    return preview
