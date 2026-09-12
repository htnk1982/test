"""Client for the isolated Spleeter observer runtime.

The mastering process exchanges sealed JSON feature arrays only. It never imports
TensorFlow/Spleeter and never receives stem samples. One-shot calls remain
available as an equivalence oracle; production observation reuses one persistent
worker process per observer instance to avoid repeated model initialization.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import atexit,json,os,subprocess,sys,time
import numpy as np
from integration_contract_v40 import digest,file_hash,valid_hash

VERSION='observer-runtime-client-0.2.0'
REQUEST_VERSION='pdrm-observer-request-0.1.0'
RESPONSE_VERSION='pdrm-observer-response-0.1.0'
SESSION_VERSION='pdrm-observer-session-0.1.0'
SESSION_ERROR_VERSION='pdrm-observer-session-error-0.1.0'
SOURCE_ORDER=('mix','drums','bass','other','vocals')


def _load_sealed(path,max_bytes=8*1024*1024):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>max_bytes:raise RuntimeError('Missing/invalid observer JSON')
    v=json.loads(path.read_text(encoding='utf-8'));b=dict(v);seal=b.pop('sha256',None)
    if seal!=digest(b):raise RuntimeError('Observer JSON seal mismatch')
    return v


def _atomic_request(path,value):
    path=Path(path);tmp=path.with_name('.'+path.name+'.tmp')
    if path.exists() or tmp.exists():raise FileExistsError('Observer request path already exists')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    os.replace(tmp,path)


def runtime_identity(runtime):
    runtime=Path(runtime).absolute();python=runtime/'python.exe';worker=runtime/'observer_worker_spleeter_v47.py';manifest=runtime/'PDRM_OBSERVER_RUNTIME_MANIFEST.json'
    if sys.platform!='win32':raise RuntimeError('Spleeter runtime capsule is Windows-x64 only')
    for p in (python,worker,manifest):
        if not p.is_file() or p.is_symlink():raise RuntimeError('Incomplete observer runtime: '+str(p))
    m=_load_sealed(manifest)
    if m.get('schema')!=1 or m.get('worker_sha256')!=file_hash(worker) or not valid_hash(m.get('model_asset_sha256')):
        raise RuntimeError('Observer runtime manifest mismatch')
    return runtime,python,worker,m


def _validate_response(response,request,manifest):
    if response.get('schema')!=1 or response.get('version')!=RESPONSE_VERSION or response.get('request_sha256')!=request['sha256']:
        raise RuntimeError('Observer response/request mismatch')
    meta=response.get('meta',{});arrays=response.get('arrays',{})
    if meta.get('source_sha256')!=request['source_sha256'] or meta.get('runtime_manifest_sha256')!=manifest['sha256'] or meta.get('model_asset_sha256')!=manifest['model_asset_sha256']:
        raise RuntimeError('Observer provenance mismatch')
    if meta.get('source_order')!=list(SOURCE_ORDER) or meta.get('stem_audio_persisted') is not False or meta.get('stem_audio_in_master') is not False or meta.get('network_downloads_allowed') is not False:
        raise RuntimeError('Observer policy mismatch')
    time_axis=np.asarray(arrays.get('time'),dtype=float)
    if time_axis.ndim!=1 or len(time_axis)<2 or not np.isfinite(time_axis).all() or np.any(np.diff(time_axis)<=0):raise RuntimeError('Invalid observer clock')
    out={'time':time_axis}
    for key in ('low_power','body_power','focus_power','upper_focus_power'):
        a=np.asarray(arrays.get(key),dtype=float)
        if a.shape!=(2,len(time_axis),5) or not np.isfinite(a).all() or np.any(a<=0):raise RuntimeError('Invalid observer '+key)
        out[key]=a
    for key in ('bass_f0_hz','bass_periodicity'):
        a=np.asarray(arrays.get(key),dtype=float)
        if a.shape!=(2,len(time_axis)) or not np.isfinite(a).all():raise RuntimeError('Invalid observer '+key)
        out[key]=a
    if np.any(out['bass_f0_hz']<0) or np.any((out['bass_periodicity']<0)|(out['bass_periodicity']>1)):raise RuntimeError('Invalid observer pitch evidence')
    return out,meta


def _request(source,start,end,pads):
    source=Path(source).absolute()
    if not source.is_file() or source.is_symlink():raise ValueError('Regular source required')
    body=dict(schema=1,version=REQUEST_VERSION,source=str(source),source_sha256=file_hash(source),start_seconds=float(start),end_seconds=float(end),contexts_seconds=[float(v) for v in pads])
    request=dict(body);request['sha256']=digest(request)
    return source,request


def _environment():
    env=dict(os.environ)
    for key in ('PYTHONHOME','PYTHONPATH','MODEL_PATH'):env.pop(key,None)
    env['PYTHONUTF8']='1';env['TF_CPP_MIN_LOG_LEVEL']='2';env['OMP_NUM_THREADS']='2';env['NO_PROXY']='*';env['no_proxy']='*'
    return env


def _no_audio_files(root):
    return not any(p.suffix.lower() in ('.wav','.flac','.mp3','.aif','.aiff') for p in Path(root).rglob('*') if p.is_file())


def observe_dual(runtime,source,start,end,pads=(1.,2.),*,work_root=None,timeout=240,progress=None):
    """Compatibility one-shot path and equivalence oracle."""
    runtime,python,worker,manifest=runtime_identity(runtime);source,request=_request(source,start,end,pads)
    root=Path(work_root).absolute() if work_root is not None else None
    if root is not None:
        root.mkdir(parents=True,exist_ok=True)
        if root.resolve()==source.parent.resolve() or source.parent.resolve() in root.resolve().parents:raise ValueError('Observer work must be outside source folder')
    before=request['source_sha256']
    with TemporaryDirectory(prefix='.observer-v47-',dir=root) as td:
        td=Path(td);req=td/'request.json';resp=td/'response.json';req.write_text(json.dumps(request,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        flags=0x08000000 if os.name=='nt' else 0
        if progress:progress.set('STEM_OBSERVER',0,1)
        result=subprocess.run([str(python),'-I',str(worker),'--request',str(req),'--response',str(resp)],cwd=runtime,env=_environment(),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=flags)
        if result.returncode:
            raise RuntimeError('Observer worker failed rc=%d stderr=%s'%(result.returncode,result.stderr[-4000:]))
        response=_load_sealed(resp);arrays,meta=_validate_response(response,request,manifest)
        if file_hash(source)!=before:raise RuntimeError('Observer changed source')
        if not _no_audio_files(td):raise RuntimeError('Observer persisted stem/audio in IPC directory')
        if progress:progress.set('STEM_OBSERVER',1,1)
        return arrays,meta


class PersistentObserverSession:
    """One embedded-Python/Spleeter process reused for sequential observer calls."""

    def __init__(self,runtime,*,work_root=None,timeout=240,startup_timeout=None):
        self.runtime,self.python,self.worker,self.manifest=runtime_identity(runtime)
        self.work_root=None if work_root is None else Path(work_root).absolute()
        self.timeout=float(timeout);self.startup_timeout=float(startup_timeout if startup_timeout is not None else timeout)
        if not 30<=self.timeout<=900 or not 30<=self.startup_timeout<=900:raise ValueError('Invalid persistent observer timeout')
        if self.work_root is not None:
            self.work_root.mkdir(parents=True,exist_ok=True)
            if self.work_root.is_symlink():raise ValueError('Linked observer work root refused')
        self._temp=None;self.session_dir=None;self.process=None;self.ready=None;self._counter=0;self._closed=False
        atexit.register(self.close)

    def __enter__(self):self.start();return self
    def __exit__(self,exc_type,exc,tb):self.close()

    def _stderr_tail(self,limit=4000):
        if self.session_dir is None:return ''
        p=self.session_dir/'worker.stderr.txt'
        try:return p.read_text(encoding='utf-8',errors='replace')[-limit:]
        except Exception:return ''

    def _wait_for(self,path,*,timeout,error_path=None):
        deadline=time.monotonic()+timeout
        path=Path(path);error_path=None if error_path is None else Path(error_path)
        while time.monotonic()<deadline:
            if path.is_file():return path
            if error_path is not None and error_path.is_file():return error_path
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError('Persistent observer worker exited rc=%s stderr=%s'%(self.process.returncode,self._stderr_tail()))
            time.sleep(.02)
        self._abort()
        raise TimeoutError('Persistent observer timed out waiting for '+path.name)

    def start(self):
        if self._closed:raise RuntimeError('Persistent observer session is closed')
        if self.process is not None:
            if self.process.poll() is not None:raise RuntimeError('Persistent observer worker already exited')
            return self
        self._temp=TemporaryDirectory(prefix='.observer-session-v47-')
        self.session_dir=Path(self._temp.name)
        stdout_path=self.session_dir/'worker.stdout.txt';stderr_path=self.session_dir/'worker.stderr.txt'
        flags=0x08000000 if os.name=='nt' else 0
        with stdout_path.open('w',encoding='utf-8',errors='replace') as out,stderr_path.open('w',encoding='utf-8',errors='replace') as err:
            self.process=subprocess.Popen([str(self.python),'-I',str(self.worker),'--serve-dir',str(self.session_dir)],cwd=self.runtime,env=_environment(),
                stdin=subprocess.DEVNULL,stdout=out,stderr=err,text=True,creationflags=flags)
        ready_path=self._wait_for(self.session_dir/'READY.json',timeout=self.startup_timeout)
        ready=_load_sealed(ready_path)
        if ready.get('schema')!=1 or ready.get('version')!=SESSION_VERSION or ready.get('worker_version')!=self.manifest.get('worker_version') or ready.get('manifest_sha256')!=self.manifest.get('sha256'):
            self._abort();raise RuntimeError('Persistent observer READY identity mismatch')
        if ready.get('separator_initialized') is not True or ready.get('network_downloads_allowed') is not False or ready.get('stem_audio_persisted') is not False:
            self._abort();raise RuntimeError('Persistent observer READY policy mismatch')
        self.ready=ready
        return self

    @property
    def worker_pid(self):
        return None if self.ready is None else self.ready.get('worker_pid')

    def observe_dual(self,source,start,end,pads=(1.,2.),*,progress=None):
        self.start();source,request=_request(source,start,end,pads);before=request['source_sha256']
        self._counter+=1;token='%08d'%self._counter
        req=self.session_dir/f'job-{token}.request.json';resp=self.session_dir/f'job-{token}.response.json';err=self.session_dir/f'job-{token}.error.json'
        if progress:progress.set('STEM_OBSERVER',0,1)
        _atomic_request(req,request)
        result_path=self._wait_for(resp,timeout=self.timeout,error_path=err)
        if result_path==err:
            failure=_load_sealed(err)
            raise RuntimeError('Persistent observer job failed: %s: %s'%(failure.get('error_type'),failure.get('error')))
        response=_load_sealed(resp);arrays,meta=_validate_response(response,request,self.manifest)
        if meta.get('persistent_session') is not True or meta.get('worker_pid')!=self.worker_pid:
            raise RuntimeError('Persistent observer response came from another worker/session')
        if file_hash(source)!=before:raise RuntimeError('Observer changed source')
        if not _no_audio_files(self.session_dir):raise RuntimeError('Persistent observer persisted stem/audio in IPC directory')
        for p in (resp,err):p.unlink(missing_ok=True)
        if progress:progress.set('STEM_OBSERVER',1,1)
        return arrays,meta

    def _abort(self):
        p=self.process
        if p is not None and p.poll() is None:
            try:p.terminate();p.wait(timeout=5)
            except Exception:
                try:p.kill()
                except Exception:pass

    def close(self):
        if self._closed:return
        self._closed=True
        try:
            if self.process is not None and self.process.poll() is None and self.session_dir is not None:
                (self.session_dir/'STOP').write_text('STOP\n',encoding='ascii')
                try:self.process.wait(timeout=10)
                except Exception:self._abort()
        finally:
            self.process=None;self.ready=None
            if self._temp is not None:
                try:self._temp.cleanup()
                except Exception:pass
            self._temp=None;self.session_dir=None
            try:atexit.unregister(self.close)
            except Exception:pass
