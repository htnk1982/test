"""GUI/worker boundary for the future release executable.

The GUI never performs DSP on its Tk thread. A worker receives an immutable,
sealed manifest and writes a bounded status document. Cancellation is an owned
file flag checked by the same progress object passed into the audio pipeline.
No product planner/model is selected in this module.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import json,os,subprocess,sys,tempfile,time
from integration_contract_v40 import digest
from target_settings import Targets

VERSION='gui-runtime-v0.1.0'
SCHEMA=1
STATUS_SCHEMA=1
MAX_SOURCES=1000


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.gui_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(value,f,ensure_ascii=False,indent=2,allow_nan=False);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        Path(name).unlink(missing_ok=True)


def make_manifest(sources,targets,replace_managed,work_root,session_dir,*,runtime_id):
    targets=targets.validate()
    if type(replace_managed) is not bool:raise ValueError('Explicit replacement flag required')
    src=[]
    for value in sources:
        p=Path(value).absolute()
        if not p.is_file() or p.suffix.lower() not in ('.wav','.flac'):raise ValueError('Existing WAV/FLAC sources required')
        src.append(str(p))
    if not src or len(src)>MAX_SOURCES:raise ValueError('1-1000 source files required')
    if len(set(s.casefold() for s in src))!=len(src):raise ValueError('Duplicate source path')
    if not isinstance(runtime_id,str) or not runtime_id:raise ValueError('Runtime identity required')
    work=Path(work_root).absolute();session=Path(session_dir).absolute()
    body=dict(schema=SCHEMA,version=VERSION,sources=src,targets=targets.to_dict(),
        replace_managed=replace_managed,work_root=str(work),session_dir=str(session),runtime_id=runtime_id)
    body['sha256']=digest(body);return body


def read_manifest(path):
    value=json.loads(Path(path).read_text(encoding='utf-8'));p=dict(value);h=p.pop('sha256',None)
    if h!=digest(p) or value.get('schema')!=SCHEMA or value.get('version')!=VERSION:raise ValueError('Worker manifest changed')
    Targets.from_fields(value['targets'])
    if type(value.get('replace_managed')) is not bool or not 1<=len(value.get('sources',[]))<=MAX_SOURCES:raise ValueError('Invalid worker manifest')
    if not isinstance(value.get('runtime_id'),str) or not value['runtime_id']:raise ValueError('Missing runtime identity')
    return value


class StatusProgress:
    def __init__(self,session,manifest_hash):
        self.session=Path(session);self.session.mkdir(parents=True,exist_ok=True)
        self.status=self.session/'status.json';self.cancel=self.session/'CANCEL';self.manifest_hash=manifest_hash
        self.file_index=0;self.file_total=0;self.current_file=None;self.failures=[];self.completed=[]
        self._write('START',0,0,'RUNNING')
    def _write(self,stage,done,total,overall,**extra):
        record=dict(schema=STATUS_SCHEMA,version=VERSION,manifest_sha256=self.manifest_hash,
            overall=overall,stage=str(stage),done=int(done),total=int(total),file_index=self.file_index,
            file_total=self.file_total,current_file=self.current_file,completed=list(self.completed),failures=list(self.failures),
            updated_unix=time.time(),**extra)
        atomic_json(self.status,record);return record
    def set_file(self,index,total,path):
        self.file_index=int(index);self.file_total=int(total);self.current_file=Path(path).name
        self.check_cancel();self._write('FILE_START',0,1,'RUNNING')
    def set(self,stage,done=0,total=0):
        self.check_cancel();self._write(stage,done,total,'RUNNING')
    def success(self,path,result):
        self.completed.append(dict(file=Path(path).name,status='COMPLETE',lowend_assessment=result.get('lowend_assessment')))
        self._write('FILE_COMPLETE',1,1,'RUNNING')
    def failure(self,path,exc):
        self.failures.append(dict(file=Path(path).name,error_type=type(exc).__name__,error=str(exc)))
        self._write('FILE_FAILED',1,1,'RUNNING')
    def check_cancel(self):
        if self.cancel.exists():raise InterruptedError('GUI cancellation requested')
    def finish(self,status):return self._write(status,1,1,status)


def run_batch(manifest_path,processor):
    """Run finite sequential files; ordinary per-file failure does not freeze UI."""
    manifest=read_manifest(manifest_path);status=StatusProgress(manifest['session_dir'],manifest['sha256'])
    targets=Targets.from_fields(manifest['targets']);sources=[Path(p) for p in manifest['sources']]
    try:
        for i,source in enumerate(sources,1):
            status.set_file(i,len(sources),source)
            try:
                result=processor(source,targets,manifest['replace_managed'],Path(manifest['work_root']),status)
                status.success(source,result)
            except InterruptedError:
                raise
            except Exception as exc:
                status.failure(source,exc)
        return status.finish('COMPLETE_WITH_ERRORS' if status.failures else 'COMPLETE')
    except InterruptedError as exc:
        return status._write('CANCELLED',0,1,'CANCELLED',cancel_reason=str(exc))


def request_cancel(session_dir):
    path=Path(session_dir)/'CANCEL';path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8') as f:f.write('cancel\n');f.flush();os.fsync(f.fileno())
    return path


def read_status(session_dir,manifest_hash=None):
    path=Path(session_dir)/'status.json'
    if not path.is_file():return None
    value=json.loads(path.read_text(encoding='utf-8'))
    if value.get('schema')!=STATUS_SCHEMA or value.get('version')!=VERSION:raise ValueError('Unknown worker status')
    if manifest_hash is not None and value.get('manifest_sha256')!=manifest_hash:raise ValueError('Status belongs to another request')
    return value


def launch(command,manifest_path,*,cwd=None):
    """Thin launcher so GUI tests can assert DSP is outside the Tk process."""
    return subprocess.Popen([str(v) for v in command]+['--worker-manifest',str(manifest_path)],cwd=cwd)
