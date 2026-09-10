"""Crash-recovery ownership for PDRM per-track working directories.

Only directories created by this module and carrying a matching sealed owner
manifest are eligible for cleanup. Live/reused PIDs are protected. A stale job
for another source/request is never removed by recovery of the current source.
This is operational safety only; it does not certify audio quality.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import json,os,shutil,time,uuid
import psutil
from integration_contract_v40 import digest,valid_hash

VERSION='crash-recovery-v1.0.0'
SCHEMA=1
PREFIX='.pdrm-owned-'
MARKER='OWNER.json'


def _plain(value):
    return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))


def _proc_create_time(pid):
    try:return float(psutil.Process(pid).create_time())
    except (psutil.NoSuchProcess,psutil.AccessDenied,psutil.ZombieProcess):return None


def _is_same_live_process(pid,created):
    now=_proc_create_time(pid)
    return now is not None and abs(now-float(created))<.01


def _sealed(body):
    body=_plain(body);return dict(body,sha256=digest(body))


def _read_marker(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size>65536:return None
        value=json.loads(path.read_text(encoding='utf-8'))
        body=dict(value);seal=body.pop('sha256',None)
        if seal!=digest(body) or value.get('schema')!=SCHEMA or value.get('version')!=VERSION:return None
        if value.get('owner')!='PDRM_PROCESSED_INTEGRATION':return None
        if not valid_hash(value.get('source_sha256')) or not valid_hash(value.get('request_sha256')):return None
        if type(value.get('pid')) is not int or value['pid']<=0:return None
        if not isinstance(value.get('process_create_time'),(int,float)):return None
        return value
    except (OSError,ValueError,TypeError,json.JSONDecodeError):return None


def _dir_size(path):
    total=0
    try:
        for p in path.rglob('*'):
            try:
                if p.is_file() and not p.is_symlink():total+=p.stat().st_size
            except OSError:pass
    except OSError:pass
    return total


def recover(root,*,source_sha256,request_sha256=None,current_pid=None):
    """Remove stale owned work for this source only; never follow links.

    request_sha256=None intentionally recovers old requests for the same source,
    because their large caches are no longer needed once no owning process lives.
    """
    root=Path(root).resolve();removed=[];kept=[];freed=0
    if not root.exists():return dict(removed=removed,kept=kept,bytes_freed=0)
    current_pid=os.getpid() if current_pid is None else int(current_pid)
    for d in root.iterdir():
        if not d.name.startswith(PREFIX) or d.is_symlink() or not d.is_dir():continue
        marker=_read_marker(d/MARKER)
        if marker is None:
            kept.append(dict(path=str(d),reason='UNVERIFIED_OWNER'))
            continue
        if marker['source_sha256']!=source_sha256:
            kept.append(dict(path=str(d),reason='OTHER_SOURCE'))
            continue
        if request_sha256 is not None and marker['request_sha256']!=request_sha256:
            kept.append(dict(path=str(d),reason='OTHER_REQUEST'))
            continue
        if marker['pid']==current_pid and _is_same_live_process(marker['pid'],marker['process_create_time']):
            kept.append(dict(path=str(d),reason='CURRENT_PROCESS'))
            continue
        if _is_same_live_process(marker['pid'],marker['process_create_time']):
            kept.append(dict(path=str(d),reason='LIVE_OWNER'))
            continue
        size=_dir_size(d)
        shutil.rmtree(d)
        if d.exists():raise RuntimeError('Failed to remove stale owned workspace: '+str(d))
        removed.append(str(d));freed+=size
    return dict(removed=removed,kept=kept,bytes_freed=freed)


@contextmanager
def owned_workspace(root,*,source_sha256,request_sha256):
    root=Path(root).resolve();root.mkdir(parents=True,exist_ok=True)
    if not valid_hash(source_sha256) or not valid_hash(request_sha256):raise ValueError('Valid source/request hashes required')
    pid=os.getpid();created=_proc_create_time(pid)
    if created is None:raise RuntimeError('Cannot establish process identity')
    name=PREFIX+source_sha256[:12]+'-'+uuid.uuid4().hex[:12]
    path=root/name;path.mkdir()
    body=dict(schema=SCHEMA,version=VERSION,owner='PDRM_PROCESSED_INTEGRATION',
        source_sha256=source_sha256,request_sha256=request_sha256,pid=pid,
        process_create_time=created,created_unix=time.time(),token=uuid.uuid4().hex)
    (path/MARKER).write_text(json.dumps(_sealed(body),ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        yield path
    finally:
        # Normal exit removes the whole owned area. A hard-killed process cannot
        # execute this block, leaving marker+workspace for the next recovery.
        if path.exists() and not path.is_symlink():shutil.rmtree(path)
