"""Isolated analysis-only Spleeter worker for PDRM.

The worker receives sealed JSON requests and writes sealed JSON responses.
Separated waveforms never leave process memory and are never mixed into output.
One-shot mode remains available as an equivalence oracle. Persistent mode keeps
one TensorFlow/Spleeter Separator alive across sequential observation windows.
"""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,math,os,sys,tempfile,time,traceback,urllib.request

VERSION='spleeter-observer-worker-0.2.0'
REQUEST_VERSION='pdrm-observer-request-0.1.0'
RESPONSE_VERSION='pdrm-observer-response-0.1.0'
SESSION_VERSION='pdrm-observer-session-0.1.0'
SESSION_ERROR_VERSION='pdrm-observer-session-error-0.1.0'
MANIFEST_NAME='PDRM_OBSERVER_RUNTIME_MANIFEST.json'
MODEL='spleeter:4stems'
SOURCE_ORDER=('mix','drums','bass','other','vocals')
MAX_CORE_SECONDS=16.0
MAX_PAD_SECONDS=4.0
MAX_REQUEST_BYTES=1024*1024


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def valid_hash(v):return isinstance(v,str) and len(v)==64 and all(c in '0123456789abcdef' for c in v)


def _sealed_read(path,max_bytes=MAX_REQUEST_BYTES):
    path=Path(path)
    if not path.is_file() or path.is_symlink() or path.stat().st_size>max_bytes:raise ValueError('Invalid JSON input file')
    value=json.loads(path.read_text(encoding='utf-8'));body=dict(value);seal=body.pop('sha256',None)
    if seal!=digest(body):raise ValueError('JSON seal mismatch')
    return value


def _atomic_json(path,value):
    path=Path(path)
    if path.exists() or path.is_symlink():raise FileExistsError('Response path must not exist')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.observer-',suffix='.json',dir=path.parent);os.close(fd);tmp=Path(name)
    try:
        tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        os.replace(tmp,path)
    finally:
        if tmp.exists():tmp.unlink()


def _seal(value):
    out=dict(value);out['sha256']=digest(out);return out


def _runtime_root():return Path(__file__).resolve().parent


def _manifest():
    root=_runtime_root();p=root/MANIFEST_NAME
    value=_sealed_read(p,8*1024*1024)
    if value.get('schema')!=1 or value.get('worker_version')!=VERSION:raise RuntimeError('Runtime manifest version mismatch')
    if value.get('worker_sha256')!=file_hash(__file__):raise RuntimeError('Worker source changed')
    vc=value.get('vc_runtime_files')
    if not isinstance(vc,dict) or 'vcruntime140.dll' not in vc or 'msvcp140.dll' not in vc:
        raise RuntimeError('Application-local VC runtime manifest missing')
    for name,meta in vc.items():
        f=root/name
        if not f.is_file() or f.is_symlink() or f.stat().st_size!=meta['bytes'] or file_hash(f)!=meta['sha256']:
            raise RuntimeError('VC runtime file integrity mismatch: '+name)
    model_root=root/'models'/'4stems'
    if not (model_root/'.probe').is_file():raise RuntimeError('Offline model probe missing')
    for rel,meta in value.get('model_files',{}).items():
        f=model_root/rel
        if not f.is_file() or f.is_symlink() or f.stat().st_size!=meta['bytes'] or file_hash(f)!=meta['sha256']:
            raise RuntimeError('Model file integrity mismatch: '+rel)
    return value


def _validate_request(value):
    if value.get('schema')!=1 or value.get('version')!=REQUEST_VERSION:raise ValueError('Request version mismatch')
    source=Path(value.get('source',''))
    if not source.is_absolute() or not source.is_file() or source.is_symlink():raise ValueError('Absolute regular source required')
    if not valid_hash(value.get('source_sha256')) or file_hash(source)!=value['source_sha256']:raise ValueError('Source hash mismatch')
    start=float(value.get('start_seconds'));end=float(value.get('end_seconds'))
    pads=value.get('contexts_seconds')
    if not (math.isfinite(start) and math.isfinite(end) and 0<=start<end and end-start<=MAX_CORE_SECONDS):raise ValueError('Invalid observer core')
    if not isinstance(pads,list) or len(pads)!=2 or len(set(pads))!=2:raise ValueError('Exactly two distinct context pads required')
    pads=[float(v) for v in pads]
    if any(not math.isfinite(v) or v<0 or v>MAX_PAD_SECONDS for v in pads):raise ValueError('Invalid context pad')
    return source,start,end,tuple(pads)


def _disable_downloads():
    def blocked(*a,**k):raise RuntimeError('Runtime network download blocked')
    urllib.request.urlopen=blocked
    urllib.request.urlretrieve=blocked
    os.environ['NO_PROXY']='*';os.environ['no_proxy']='*'


def _load_runtime():
    manifest=_manifest();model_root=_runtime_root()/'models';os.environ['MODEL_PATH']=str(model_root);_disable_downloads()
    import numpy as np
    import scipy
    import soundfile as sf
    import tensorflow as tf
    from scipy import signal
    from spleeter.separator import Separator
    separator=Separator(MODEL,multiprocess=False)
    return manifest,separator,np,scipy,sf,tf,signal


def _features(original,stems,sr,start,np,signal):
    from scipy.ndimage import uniform_filter1d
    src=np.stack((original,stems['drums'],stems['bass'],stems['other'],stems['vocals']),axis=0)
    g=math.gcd(sr,12000);x=signal.resample_poly(src,12000//g,sr//g,axis=1,window=('kaiser',10.5));sr=12000
    hop=120;window=720;out={'time':(start+np.arange(0,x.shape[1],hop)/sr).tolist()}
    for name,lo,hi in (('low',25,120),('body',120,300),('focus',300,450),('upper_focus',450,700)):
        z=signal.sosfiltfilt(signal.butter(4,[lo,hi],btype='bandpass',fs=sr,output='sos'),x,axis=1)
        p=np.maximum(uniform_filter1d(np.mean(z*z,axis=-1),window,axis=1,mode='nearest')[:,::hop],1e-24)
        out[name+'_power']=p.T.tolist()
    bass=x[2].mean(axis=1);n=2400;pad=n//2;y=np.pad(bass,(pad,pad));pitches=[];periods=[];lo=int(sr/160);hi=int(sr/30)
    for c in range(0,len(bass),hop):
        a=y[c:c+n];a=a-a.mean()
        if np.mean(a*a)<1e-14:pitches.append(0.);periods.append(0.);continue
        ac=signal.correlate(a,a,mode='full',method='fft')[n-1:];en=np.r_[0,np.cumsum(a*a)];lag=np.arange(n)
        den=en[n-lag]+en[n]-en[lag];nd=2*ac/np.maximum(den,1e-24);peaks,_=signal.find_peaks(nd[lo:hi]);peaks+=lo
        if not len(peaks):pitches.append(0.);periods.append(0.);continue
        k=int(peaks[np.argmax(nd[peaks])]);q=nd[k-1]-2*nd[k]+nd[k+1]
        h=.5*(nd[k-1]-nd[k+1])/q if abs(q)>1e-12 else 0.
        pitches.append(float(sr/(k+np.clip(h,-.5,.5))));periods.append(float(np.clip(nd[k],0,1)))
    out['bass_f0_hz']=pitches;out['bass_periodicity']=periods
    return out


def _process(request,manifest,separator,np,sf,tf,signal,*,persistent_session):
    source,start,end,pads=_validate_request(request)
    info=sf.info(source)
    if info.channels!=2 or not (0<=start<end<=info.duration):raise ValueError('Source geometry/core mismatch')
    contexts=[];reconstruction=[]
    for pad_seconds in pads:
        left=max(0.,start-pad_seconds);right=min(info.duration,end+pad_seconds)
        with sf.SoundFile(source) as f:
            a=round(left*info.samplerate);b=round(right*info.samplerate);f.seek(a);raw=f.read(b-a,dtype='float32',always_2d=True)
        if raw.shape[1]!=2 or not np.isfinite(raw).all():raise ValueError('Invalid observer input')
        g=math.gcd(info.samplerate,44100);x=signal.resample_poly(raw,44100//g,info.samplerate//g,axis=0,window=('kaiser',10.5)).astype('float32')
        before=x.copy();stems=separator.separate(x,'pdrm-observer')
        if set(stems)!={'vocals','drums','bass','other'} or any(np.asarray(v).shape!=x.shape or not np.isfinite(v).all() for v in stems.values()):raise RuntimeError('Invalid separator result')
        np.testing.assert_array_equal(x,before)
        i=round((start-left)*44100);j=i+round((end-start)*44100);core=x[i:j]
        s={k:np.asarray(v[i:j],dtype=np.float32) for k,v in stems.items()}
        if len(core)!=j-i:raise RuntimeError('Observer core clock mismatch')
        contexts.append(_features(core,s,44100,start,np,signal))
        summed=s['vocals']+s['drums']+s['bass']+s['other'];num=np.sqrt(np.mean((summed-core)**2));den=max(np.sqrt(np.mean(core**2)),1e-12)
        reconstruction.append(float(20*np.log10(max(num/den,1e-15))))
        del stems,s,raw,x,core,summed
    if file_hash(source)!=request['source_sha256']:raise RuntimeError('Observer source changed')
    if contexts[0]['time']!=contexts[1]['time']:raise RuntimeError('Context clocks differ')
    arrays={'time':contexts[0]['time']}
    for key in ('low_power','body_power','focus_power','upper_focus_power','bass_f0_hz','bass_periodicity'):
        arrays[key]=[c[key] for c in contexts]
    meta=dict(worker_version=VERSION,model=MODEL,model_asset_sha256=manifest['model_asset_sha256'],runtime_manifest_sha256=manifest['sha256'],
        source_sha256=request['source_sha256'],source_name=source.name,source_samplerate=info.samplerate,source_frames=info.frames,
        start_seconds=start,end_seconds=end,contexts_seconds=list(pads),source_order=list(SOURCE_ORDER),reconstruction_error_db=reconstruction,
        probabilities_calibrated=False,stem_audio_persisted=False,stem_audio_in_master=False,network_downloads_allowed=False,
        runtime_executable=str(Path(sys.executable).resolve()),runtime_prefix=str(Path(sys.prefix).resolve()),tensorflow_version=tf.__version__,
        worker_pid=os.getpid(),persistent_session=bool(persistent_session))
    response=dict(schema=1,version=RESPONSE_VERSION,request_sha256=request['sha256'],arrays=arrays,meta=meta)
    response['sha256']=digest(response)
    return response


def run(request_path,response_path):
    manifest,separator,np,scipy,sf,tf,signal=_load_runtime()
    request=_sealed_read(request_path)
    response=_process(request,manifest,separator,np,sf,tf,signal,persistent_session=False)
    _atomic_json(response_path,response)


def _session_error(request_name,exc):
    return _seal(dict(schema=1,version=SESSION_ERROR_VERSION,request_name=request_name,error_type=type(exc).__name__,
        error=str(exc),traceback=traceback.format_exc(),worker_pid=os.getpid()))


def serve(session_dir):
    session=Path(session_dir).resolve()
    if not session.is_dir() or session.is_symlink():raise ValueError('Persistent session directory must be a regular directory')
    manifest,separator,np,scipy,sf,tf,signal=_load_runtime()
    ready=_seal(dict(schema=1,version=SESSION_VERSION,worker_version=VERSION,manifest_sha256=manifest['sha256'],
        worker_pid=os.getpid(),native_extensions_loaded=True,separator_initialized=True,network_downloads_allowed=False,
        stem_audio_persisted=False,stem_audio_in_master=False))
    _atomic_json(session/'READY.json',ready)
    while True:
        if (session/'STOP').exists():break
        jobs=sorted(session.glob('job-*.request.json'))
        if not jobs:
            time.sleep(.02);continue
        request_path=jobs[0]
        processing=request_path.with_name(request_path.name.replace('.request.json','.processing.json'))
        try:
            os.replace(request_path,processing)
        except FileNotFoundError:
            continue
        token=processing.name[len('job-'):-len('.processing.json')]
        response_path=session/f'job-{token}.response.json'
        error_path=session/f'job-{token}.error.json'
        try:
            request=_sealed_read(processing)
            response=_process(request,manifest,separator,np,sf,tf,signal,persistent_session=True)
            _atomic_json(response_path,response)
        except Exception as exc:
            _atomic_json(error_path,_session_error(processing.name,exc))
        finally:
            processing.unlink(missing_ok=True)
    stopped=_seal(dict(schema=1,version=SESSION_VERSION,worker_version=VERSION,worker_pid=os.getpid(),stopped=True))
    try:_atomic_json(session/'STOPPED.json',stopped)
    except FileExistsError:pass


def self_test():
    m,separator,np,scipy,sf,tf,signal=_load_runtime()
    value=dict(success=True,worker_version=VERSION,python=sys.version,executable=str(Path(sys.executable).resolve()),prefix=str(Path(sys.prefix).resolve()),
        packages=dict(spleeter='2.4.2',tensorflow=tf.__version__,numpy=np.__version__,scipy=scipy.__version__,soundfile=sf.__version__),
        manifest_sha256=m['sha256'],network_downloads_allowed=False,native_extensions_loaded=True,separator_initialized=separator is not None,
        persistent_mode_available=True,application_local_vc_runtime=True,vc_runtime_files=sorted(m['vc_runtime_files']))
    print(json.dumps(value,ensure_ascii=True),flush=True)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--request');ap.add_argument('--response');ap.add_argument('--self-test',action='store_true');ap.add_argument('--serve-dir');a=ap.parse_args()
    modes=int(a.self_test)+int(bool(a.serve_dir))+int(bool(a.request or a.response))
    if modes!=1:raise SystemExit('choose exactly one mode: self-test, serve-dir, or request/response')
    if a.self_test:self_test();return
    if a.serve_dir:serve(Path(a.serve_dir));return
    if not a.request or not a.response:raise SystemExit('request/response required')
    run(Path(a.request),Path(a.response))


if __name__=='__main__':main()
