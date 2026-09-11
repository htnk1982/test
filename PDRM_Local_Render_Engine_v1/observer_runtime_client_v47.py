"""Client for the isolated Spleeter observer runtime.

The mastering process exchanges sealed JSON feature arrays only. It never imports
TensorFlow/Spleeter and never receives stem samples. Runtime files are immutable
inputs; per-call request/response files live in one owned temporary directory.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import json,os,subprocess,sys
import numpy as np
from integration_contract_v40 import digest,file_hash,valid_hash

VERSION='observer-runtime-client-0.1.0'
REQUEST_VERSION='pdrm-observer-request-0.1.0'
RESPONSE_VERSION='pdrm-observer-response-0.1.0'
SOURCE_ORDER=('mix','drums','bass','other','vocals')


def _load_sealed(path,max_bytes=8*1024*1024):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>max_bytes:raise RuntimeError('Missing/invalid observer JSON')
    v=json.loads(path.read_text(encoding='utf-8'));b=dict(v);seal=b.pop('sha256',None)
    if seal!=digest(b):raise RuntimeError('Observer JSON seal mismatch')
    return v


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
    time=np.asarray(arrays.get('time'),dtype=float)
    if time.ndim!=1 or len(time)<2 or not np.isfinite(time).all() or np.any(np.diff(time)<=0):raise RuntimeError('Invalid observer clock')
    out={'time':time}
    for key in ('low_power','body_power','focus_power','upper_focus_power'):
        a=np.asarray(arrays.get(key),dtype=float)
        if a.shape!=(2,len(time),5) or not np.isfinite(a).all() or np.any(a<=0):raise RuntimeError('Invalid observer '+key)
        out[key]=a
    for key in ('bass_f0_hz','bass_periodicity'):
        a=np.asarray(arrays.get(key),dtype=float)
        if a.shape!=(2,len(time)) or not np.isfinite(a).all():raise RuntimeError('Invalid observer '+key)
        out[key]=a
    if np.any(out['bass_f0_hz']<0) or np.any((out['bass_periodicity']<0)|(out['bass_periodicity']>1)):raise RuntimeError('Invalid observer pitch evidence')
    return out,meta


def observe_dual(runtime,source,start,end,pads=(1.,2.),*,work_root=None,timeout=240,progress=None):
    runtime,python,worker,manifest=runtime_identity(runtime);source=Path(source).absolute()
    if not source.is_file() or source.is_symlink():raise ValueError('Regular source required')
    body=dict(schema=1,version=REQUEST_VERSION,source=str(source),source_sha256=file_hash(source),start_seconds=float(start),end_seconds=float(end),contexts_seconds=[float(v) for v in pads])
    request=dict(body);request['sha256']=digest(request)
    root=Path(work_root).absolute() if work_root is not None else None
    if root is not None:
        root.mkdir(parents=True,exist_ok=True)
        if root.resolve()==source.parent.resolve() or source.parent.resolve() in root.resolve().parents:raise ValueError('Observer work must be outside source folder')
    before=request['source_sha256']
    with TemporaryDirectory(prefix='.observer-v47-',dir=root) as td:
        td=Path(td);req=td/'request.json';resp=td/'response.json';req.write_text(json.dumps(request,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        env=dict(os.environ)
        for key in ('PYTHONHOME','PYTHONPATH','MODEL_PATH'):env.pop(key,None)
        env['PYTHONUTF8']='1';env['TF_CPP_MIN_LOG_LEVEL']='2';env['OMP_NUM_THREADS']='2';env['NO_PROXY']='*';env['no_proxy']='*'
        flags=0x08000000 if os.name=='nt' else 0
        if progress:progress.set('STEM_OBSERVER',0,1)
        result=subprocess.run([str(python),'-I',str(worker),'--request',str(req),'--response',str(resp)],cwd=runtime,env=env,
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=flags)
        if result.returncode:
            raise RuntimeError('Observer worker failed rc=%d stderr=%s'%(result.returncode,result.stderr[-4000:]))
        response=_load_sealed(resp);arrays,meta=_validate_response(response,request,manifest)
        if file_hash(source)!=before:raise RuntimeError('Observer changed source')
        if any(p.suffix.lower() in ('.wav','.flac','.mp3') for p in td.rglob('*') if p.is_file()):raise RuntimeError('Observer persisted stem/audio in IPC directory')
        if progress:progress.set('STEM_OBSERVER',1,1)
        return arrays,meta
