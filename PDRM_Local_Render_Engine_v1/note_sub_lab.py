"""PDRM Note-Sub Lab: additive, experimental low-end synthesis; not a mastering preset.

Original stereo audio is never separated/resynthesized. Analysis uses two filtered
views and a harmonic test. This is NOT semantic bass separation, a key detector,
a calibrated confidence model, or an implementation of a commercial processor.
No network requests, model downloads, installation, or production-core imports.
"""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):
    os.environ.setdefault(_key,'1')
from pathlib import Path
from contextlib import contextmanager
from collections import Counter
import argparse
import hashlib
import importlib.metadata
import json
import math
import shutil
import subprocess
import tempfile
import threading
import time
import traceback
import zipfile
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy import signal

VERSION='note-sub-lab-0.1.1'
KNOWN_C='ee2df798b8a3096bba078968c0db9e953769a42924f717de02f9107936e4e7d1'
EPS=1e-24
# Engineering starting values, not perceptual standards or learned probabilities.
CONFIG=dict(analysis_sr=4000,frame_seconds=0.192,hop_seconds=0.020,
            analysis_chunk_seconds=8.0,render_chunk_seconds=8.0,
            min_pitch_hz=30.0,max_pitch_hz=180.0,min_sub_hz=30.0,max_sub_hz=65.0,
            periodicity_min=0.84,low_periodicity_min=0.88,agreement_cents=35.0,
            harmonic_fraction_min=0.52,harmonic_support_ratio=0.16,min_harmonics=2,
            max_quarter_range_db=8.0,min_event_seconds=0.12,max_step_cents=75.0,
            max_event_span_cents=110.0,fade_seconds=0.060,desired_partial_ratio=0.50,
            max_added_peak=0.080,max_relative_peak=0.70,already_full_ratio=0.90,
            target_lufs=-14.0,pcm_tp_ceiling=-1.5,codec_tp_ceiling=-1.0,
            max_matching_gain_change_db=0.50,leakage_above_110_limit_db=-35.0,
            layer_below_20_limit_db=-20.0,scales=[1.0,0.5,0.25])


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def pcm_hash(path):
    """Canonical decoded float64 sample hash, excluding WAV metadata/time stamps."""
    h=hashlib.sha256()
    with sf.SoundFile(path) as f:
        h.update(f'{f.samplerate}:{f.channels}:{f.frames}:float64le'.encode('ascii'))
        while True:
            x=f.read(65536,dtype='float64',always_2d=True)
            if not len(x):break
            h.update(np.asarray(x,dtype='<f8').tobytes(order='C'))
    return h.hexdigest()


def obj_hash(obj):
    return hashlib.sha256(json.dumps(obj,sort_keys=True,ensure_ascii=False,
                          allow_nan=False,separators=(',',':')).encode()).hexdigest()


def read_json(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sync_owned_file(path):
    # Windows _commit requires a writable descriptor. Called ONLY on our outputs.
    with Path(path).open('r+b') as f:f.flush();os.fsync(f.fileno())


def atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.pdrm_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(data,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def atomic_wav(path,data,sr,subtype='FLOAT'):
    path=Path(path)
    fd,tmp=tempfile.mkstemp(prefix='.pdrm_',suffix='.wav',dir=path.parent);os.close(fd)
    try:
        sf.write(tmp,data,sr,subtype=subtype)
        sync_owned_file(tmp)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


@contextmanager
def job_lock(path):
    f=Path(path).open('a+b')
    if f.tell()==0:f.write(b'0');f.flush()
    f.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError as exc:
        f.close();raise RuntimeError('This job is already running. Do not start another copy.') from exc
    try:yield
    finally:f.close()


class Progress:
    def __init__(self,root=None):
        self.root=Path(root) if root else None
        self.state={'stage':'START','done':0,'total':0}
        self.started=time.monotonic();self.changed=self.started
        self.stop=threading.Event();self.error=None
        self.thread=threading.Thread(target=self._loop,daemon=True)
    def set(self,stage,done=0,total=0):
        if self.root and (self.root/'CANCEL').exists():
            raise InterruptedError('CANCEL requested; committed work is retained.')
        self.state=dict(stage=stage,done=done,total=total);self.changed=time.monotonic()
        if self.error:raise RuntimeError('Progress persistence failed: '+self.error)
    def _loop(self):
        while not self.stop.wait(2.0):
            v=dict(self.state,elapsed_seconds=round(time.monotonic()-self.started,1),
                   seconds_since_step=round(time.monotonic()-self.changed,1))
            try:
                if self.root:atomic_json(self.root/'heartbeat.json',v)
                print('[{stage}] {done}/{total}; elapsed={elapsed_seconds}s; step_age={seconds_since_step}s'.format(**v),flush=True)
            except Exception as exc:self.error=repr(exc);break
    def __enter__(self):self.thread.start();return self
    def __exit__(self,*args):self.stop.set();self.thread.join(5)


def finite(x):
    if not np.isfinite(x).all():raise ValueError('Non-finite input samples')


def cents(a,b):return abs(1200.0*math.log2(a/b))


def nsdf_pitch(x,sr=4000):
    """Normalized autocorrelation/SDF-style evidence, not polyphonic transcription."""
    x=np.asarray(x,dtype=np.float64);x=x-np.mean(x);n=len(x)
    if n<128 or np.mean(x*x)<1e-14:return None,0.0
    ac=signal.fftconvolve(x,x[::-1],mode='full')[n-1:]
    cs=np.r_[0.0,np.cumsum(x*x)]
    lo=max(2,int(sr/CONFIG['max_pitch_hz']));hi=min(n//2,int(sr/CONFIG['min_pitch_hz'])+1)
    lag=np.arange(hi+2);den=cs[n-lag]+cs[n]-cs[lag]
    curve=2*ac[:hi+2]/np.maximum(den,EPS)
    peaks,_=signal.find_peaks(curve[lo:hi+1]);peaks=peaks+lo
    if not len(peaks):return None,0.0
    best=float(np.max(curve[peaks]));good=peaks[curve[peaks]>=max(0.70,best*0.93)]
    if not len(good):return None,best
    p=int(good[0]);a,b,c=curve[p-1:p+2];d=a-2*b+c
    shift=float(np.clip(0.5*(a-c)/d,-0.5,0.5)) if abs(d)>EPS else 0.0
    hz=sr/(p+shift)
    if not CONFIG['min_pitch_hz']<=hz<=CONFIG['max_pitch_hz']:return None,float(b)
    return float(hz),float(np.clip(b,0,1))


def component(x,hz,sr):
    w=np.hanning(len(x));t=np.arange(len(x))/sr
    z=2*np.sum(w*x*np.exp(-2j*np.pi*hz*t))/max(np.sum(w),EPS)
    return float(abs(z)),float(np.angle(z))


def sub_frequency(f0):
    if CONFIG['min_sub_hz']<=f0<=CONFIG['max_sub_hz']:return f0
    f=f0/2.0
    return f if CONFIG['min_sub_hz']<=f<=CONFIG['max_sub_hz'] else None


def analyze_frame(wide,low,stereo,sub,t):
    out={'time':float(t),'state':'ABSTAIN','reason':'uncertain','amplitude':0.0}
    rms=float(np.sqrt(np.mean(stereo*stereo)))
    if rms<1e-5:out['reason']='silence';return out
    if np.mean(wide*wide)<0.04*np.mean(stereo*stereo):
        out['reason']='no_centered_low_tonal_evidence';return out
    q=np.array([np.mean(v*v) for v in np.array_split(wide,4)]);qdb=10*np.log10(np.maximum(q,EPS))
    if float(np.max(qdb)-np.min(qdb))>CONFIG['max_quarter_range_db']:
        out['reason']='transient_or_boundary';return out
    f,p=nsdf_pitch(wide);f2,p2=nsdf_pitch(low);out.update(periodicity=p,low_periodicity=p2)
    if f is None or f2 is None or p<CONFIG['periodicity_min'] or p2<CONFIG['low_periodicity_min']:
        out['reason']='weak_periodicity';return out
    out['f0_hz']=f
    if cents(f,f2)>CONFIG['agreement_cents']:
        out['reason']='pitch_views_disagree';return out
    amps=[component(wide,f*h,CONFIG['analysis_sr'])[0] for h in range(1,7) if f*h<740]
    largest=max(amps);support=sum(a>=largest*CONFIG['harmonic_support_ratio'] for a in amps)
    fit=float(min(1.0,sum(a*a/2 for a in amps)/max(np.mean(wide*wide),EPS)))
    out.update(harmonic_support=int(support),harmonic_fraction=fit)
    # Pure sine kick/bass cannot be distinguished by pitch alone; abstain here.
    if support<CONFIG['min_harmonics'] or fit<CONFIG['harmonic_fraction_min']:
        out['reason']='insufficient_harmonic_evidence';return out
    target=sub_frequency(f)
    if target is None:out['reason']='outside_single_octave_sub_range';return out
    existing,_=component(np.mean(stereo,axis=1),target,CONFIG['analysis_sr'])
    desired=min(largest*CONFIG['desired_partial_ratio'],CONFIG['max_added_peak'],rms*CONFIG['max_relative_peak'])
    sub_rms=float(np.sqrt(np.mean(sub*sub)))
    out.update(sub_hz=float(target),existing_target_amplitude=existing,existing_sub_rms=sub_rms,desired_amplitude=desired)
    if existing>=desired*CONFIG['already_full_ratio'] or sub_rms>=desired/math.sqrt(2):
        out.update(state='KEEP',reason='existing_low_end_sufficient');return out
    amplitude=min(max(0.0,desired-existing),CONFIG['max_added_peak'])
    if amplitude<1e-5:out.update(state='KEEP',reason='negligible_addition');return out
    out.update(state='REINFORCE' if existing>desired*0.20 else 'SYNTHESIZE',reason='eligible_tonal_interval',amplitude=float(amplitude))
    return out


def read_analysis(path,a_seconds,b_seconds):
    info=sf.info(path);sr=info.samplerate;target=CONFIG['analysis_sr']
    g=math.gcd(sr,target);down=sr//g
    a=max(0,int(math.floor(a_seconds*sr/down))*down);b=min(info.frames,int(math.ceil(b_seconds*sr)))
    with sf.SoundFile(path) as f:
        f.seek(a);x=f.read(max(0,b-a),dtype='float64',always_2d=True)
    finite(x)
    y=signal.resample_poly(x,target//g,down,axis=0,window=('kaiser',10.5))
    return y,a/sr


def collect_frames(path,job,progress,interrupt_after=None):
    info=sf.info(path);chunk=CONFIG['analysis_chunk_seconds'];sr=CONFIG['analysis_sr']
    hop=CONFIG['hop_seconds'];half=int(round(CONFIG['frame_seconds']*sr))//2
    rows=[];reused=0;computed=0;count=math.ceil(info.duration/chunk)
    for i in range(count):
        progress.set('ANALYZE_NOTES',i,count);cache=job/'analysis'/f'frames_{i:05d}.json';record=None
        if cache.exists():
            try:
                v=read_json(cache)
                if v['sha256']==obj_hash(v['rows']):record=v['rows']
            except (OSError,ValueError,KeyError,TypeError):pass
        if record is not None:reused+=1;rows.extend(record);continue
        a,b=i*chunk,min(info.duration,(i+1)*chunk)
        data,origin=read_analysis(path,a-0.35,b+0.35);mid=np.mean(data,axis=1)
        wide=signal.sosfiltfilt(signal.butter(4,[28,750],btype='bandpass',fs=sr,output='sos'),mid)
        low=signal.sosfiltfilt(signal.butter(4,[28,260],btype='bandpass',fs=sr,output='sos'),mid)
        sub=signal.sosfiltfilt(signal.butter(6,[25,70],btype='bandpass',fs=sr,output='sos'),data,axis=0)
        record=[]
        for j in range(int(round(a/hop)),int(math.ceil(b/hop))):
            t=j*hop;center=int(round((t-origin)*sr))
            if t-half/sr<0 or t+half/sr>info.duration or center-half<0 or center+half>len(data):
                record.append(dict(time=t,state='ABSTAIN',reason='file_edge',amplitude=0.0));continue
            sl=slice(center-half,center+half)
            record.append(analyze_frame(wide[sl],low[sl],data[sl],sub[sl],t))
        atomic_json(cache,{'rows':record,'sha256':obj_hash(record)})
        rows.extend(record);computed+=1
        if interrupt_after is not None and computed>=interrupt_after:raise RuntimeError('TEST_INTERRUPTION_AFTER_ANALYSIS_COMMIT')
    return rows,{'computed_chunks':computed,'reused_chunks':reused}


def smoother(x):
    x=np.clip(x,0,1);return x*x*x*(10+x*(-15+6*x))


def event_wave(event,times,phase=None):
    """Analytical integral of piecewise-linear frequency: no chunk phase resets."""
    times=np.asarray(times,dtype=np.float64)
    knots=np.asarray(event['times']);freq=np.asarray(event['frequencies'])
    amps=np.asarray(event['amplitudes']);integ=np.asarray(event['integral_cycles'])
    j=np.clip(np.searchsorted(knots,times,side='right')-1,0,len(knots)-2)
    dt=times-knots[j];width=knots[j+1]-knots[j];r=np.clip(dt/width,0,1)
    cycles=integ[j]+freq[j]*dt+0.5*(freq[j+1]-freq[j])/width*dt*dt
    amp=amps[j]+(amps[j+1]-amps[j])*smoother(r)
    fade=min(CONFIG['fade_seconds'],(event['end']-event['start'])/2)
    env=smoother((times-event['start'])/fade)*smoother((event['end']-times)/fade)
    mask=(times>=event['start'])&(times<event['end'])
    return mask*amp*env*np.cos(2*np.pi*cycles+(event.get('phase',0.0) if phase is None else phase))


def make_events(rows,path):
    groups=[];group=[]
    def close():
        if group:groups.append(group.copy());group.clear()
    for r in rows:
        if r.get('amplitude',0)<=0:close();continue
        if group and (r['time']-group[-1]['time']>CONFIG['hop_seconds']*1.5 or
                      cents(r['f0_hz'],group[-1]['f0_hz'])>CONFIG['max_step_cents'] or
                      cents(r['sub_hz'],group[-1]['sub_hz'])>CONFIG['max_step_cents']):close()
        group.append(r)
    close();events=[];rejected=[]
    for g in groups:
        start,end=g[0]['time'],g[-1]['time']
        if end-start<CONFIG['min_event_seconds']-1e-8:
            rejected.append(dict(start=start,end=end,reason='short_stable_run'));continue
        freq=np.array([r['sub_hz'] for r in g])
        if cents(float(np.max(freq)),float(np.min(freq)))>CONFIG['max_event_span_cents']:
            rejected.append(dict(start=start,end=end,reason='unstable_pitch_trajectory'));continue
        tt=np.array([r['time'] for r in g]);cycles=np.r_[0.0,np.cumsum((freq[1:]+freq[:-1])*0.5*np.diff(tt))]
        e=dict(start=start,end=end,times=tt.tolist(),frequencies=freq.tolist(),
               amplitudes=[r['amplitude'] for r in g],integral_cycles=cycles.tolist(),
               median_f0_hz=float(np.median([r['f0_hz'] for r in g])),median_sub_hz=float(np.median(freq)),phase=0.0)
        data,origin=read_analysis(path,start,min(end,start+2.0))
        t=origin+np.arange(len(data))/CONFIG['analysis_sr'];keep=(t>=start)&(t<end);data=data[keep];t=t[keep]
        if not len(t):continue
        best=None
        for phase in np.arange(8)*np.pi/4:
            y=event_wave(e,t,float(phase));corr=float(np.sum(y*np.mean(data,axis=1)))
            peak=float(np.max(np.abs(data+y[:,None])));cost=(corr<-1e-8,peak,-corr,float(phase))
            if best is None or cost<best[0]:best=(cost,float(phase))
        e['phase']=best[1];events.append(e)
    return events,rejected


def layer_chunk(events,start_frame,frames,sr,scale=1.0):
    t=(start_frame+np.arange(frames,dtype=np.float64))/sr;out=np.zeros(frames,dtype=np.float64)
    if frames:
        for e in events:
            if e['start']>t[-1] or e['end']<=t[0]:continue
            mask=(t>=e['start'])&(t<e['end']);out[mask]+=event_wave(e,t[mask])*scale
    return out


def k_filter(sr):
    meter=pyln.Meter(sr)
    return [(np.asarray(s.b)*s.passband_gain,np.asarray(s.a)) for s in meter._filters.values()]


def measure(path,progress=None,label='MEASURE'):
    info=sf.info(path);sr=info.samplerate;channels=info.channels
    if channels not in (1,2):raise ValueError('Only mono/stereo measurement is supported')
    coeff=k_filter(sr);zi=[np.zeros((max(len(a),len(b))-1,channels)) for b,a in coeff]
    width=int(2*sr);win=int(round(.4*sr));hop=int(round(.1*sr))
    tail=np.empty(0);blocks=[];peak=0.;tp=0.;sumsq=0.;psum=None;fgrid=None;seen=0
    with sf.SoundFile(path) as fin:
        for a in range(0,info.frames,width):
            if progress:progress.set(label,a,info.frames)
            b=min(info.frames,a+width);pad=128;left=max(0,a-pad);right=min(info.frames,b+pad)
            fin.seek(left);xp=fin.read(right-left,dtype='float64',always_2d=True);finite(xp);x=xp[a-left:b-left]
            peak=max(peak,float(np.max(np.abs(x))))
            up=signal.resample_poly(xp,4,1,axis=0,window=('kaiser',10.5))
            tp=max(tp,float(np.max(np.abs(up[(a-left)*4:(b-left)*4]))))
            sumsq+=float(np.sum(x*x));seen+=x.size;weighted=x
            for k,(bb,aa) in enumerate(coeff):weighted,zi[k]=signal.lfilter(bb,aa,weighted,axis=0,zi=zi[k])
            power=np.r_[tail,np.sum(weighted*weighted,axis=1)]
            if len(power)>=win:
                starts=np.arange(0,len(power)-win+1,hop);cs=np.r_[0.,np.cumsum(power)]
                blocks.extend(((cs[starts+win]-cs[starts])/win).tolist());tail=power[int(starts[-1])+hop:]
            else:tail=power
            nfft=16384;xx=x
            if len(xx)<nfft:xx=np.pad(xx,((0,nfft-len(xx)),(0,0)))
            ff,ps=signal.welch(xx,fs=sr,nperseg=nfft,noverlap=nfft//2,axis=0,detrend=False)
            part=np.mean(ps,axis=1)*(b-a);psum=part if psum is None else psum+part;fgrid=ff
    expected=max(0,int(np.round((info.duration-.4)/.1))+1)
    if len(blocks)<expected and len(tail):blocks.append(float(np.sum(tail)/win))
    z=np.asarray(blocks);lev=-.691+10*np.log10(np.maximum(z,EPS));good=z[lev>=-70];lufs=None
    if len(good):
        threshold=-.691+10*np.log10(np.mean(good))-10;good=z[(lev>-70)&(lev>threshold)]
        if len(good):lufs=float(-.691+10*np.log10(np.mean(good)))
    total=float(np.sum(psum)) if psum is not None else 0.0
    def ratio(mask):return None if total<EPS else float(10*np.log10(max(float(np.sum(psum[mask]))/total,EPS)))
    return dict(lufs_i=lufs,sample_peak_dbfs=float(20*np.log10(max(peak,1e-12))),
                true_peak_dbtp_estimate=float(20*np.log10(max(tp,1e-12))),
                rms_dbfs=float(10*np.log10(max(sumsq/max(seen,1),EPS))),
                above_110_energy_db=ratio(fgrid>=110),below_20_energy_db=ratio(fgrid<20),
                frames=info.frames,samplerate=sr,channels=channels)


def valid_audio_cache(path,marker):
    try:
        v=read_json(marker);return path.exists() and file_hash(path)==v['sha256']
    except (OSError,ValueError,KeyError,TypeError):return False


def render(path,job,events,progress,scale,gain=1.0,label='candidate',interrupt_after=None):
    info=sf.info(path);sr=info.samplerate;width=int(round(CONFIG['render_chunk_seconds']*sr))
    chunks=job/'chunks'/label;chunks.mkdir(parents=True,exist_ok=True)
    committed=[];count=math.ceil(info.frames/width);computed=0;reused=0
    with sf.SoundFile(path) as f:
        for i,a in enumerate(range(0,info.frames,width)):
            progress.set('RENDER_'+label,i,count);b=min(info.frames,a+width)
            p=chunks/f'{i:05d}.wav';marker=p.with_suffix('.json')
            if valid_audio_cache(p,marker):reused+=1
            else:
                f.seek(a);x=f.read(b-a,dtype='float64',always_2d=True);finite(x)
                d=layer_chunk(events,a,b-a,sr,scale)
                y=d[:,None] if label=='delta' else gain*(x+d[:,None])
                finite(y);atomic_wav(p,y,sr,'FLOAT')
                atomic_json(marker,dict(sha256=file_hash(p),frames=b-a));computed+=1
                if interrupt_after is not None and computed>=interrupt_after:raise RuntimeError('TEST_INTERRUPTION_AFTER_RENDER_COMMIT')
            committed.append(p)
    out=job/f'{label}.wav';marker=out.with_suffix('.done.json')
    if not valid_audio_cache(out,marker):
        tmp=job/f'.{label}.partial.wav'
        with sf.SoundFile(tmp,'w',samplerate=sr,channels=1 if label=='delta' else 2,format='WAV',subtype='FLOAT') as dst:
            for p in committed:
                with sf.SoundFile(p) as src:
                    while True:
                        x=src.read(65536,dtype='float32',always_2d=True)
                        if not len(x):break
                        dst.write(x)
        sync_owned_file(tmp);os.replace(tmp,out)
        atomic_json(marker,dict(sha256=file_hash(out),pcm_sha256=pcm_hash(out)))
    return out,dict(computed_chunks=computed,reused_chunks=reused)


def ffmpeg_path():
    p=shutil.which('ffmpeg')
    if p:return p
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError,RuntimeError,OSError):return None


def codec_file(ff,src,dst,decode=False):
    cmd=[ff,'-y','-nostdin','-hide_banner','-loglevel','error','-i',str(src),'-map_metadata','-1']
    cmd+=['-c:a','pcm_f32le'] if decode else ['-c:a','libmp3lame','-b:a','320k']
    subprocess.run(cmd+[str(dst)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=1800)


def validate_manifest(path):
    path=Path(path).resolve();path=path/'manifest.json' if path.is_dir() else path;m=read_json(path)
    if m.get('experiment_id')!='PDRM-v0.6-Round9-HarmonicLoudness-exp1':raise ValueError('Select the accepted Round 9 manifest.json')
    job=path.parent
    if read_json(job/'LAB_INTERNAL/blind_mapping.json').get('C')!='HarmonicElasticity':raise ValueError('This job does not map C to HarmonicElasticity')
    src=job/'RENDERS/HarmonicElasticity.wav'
    if file_hash(src)!=KNOWN_C:raise ValueError('The input is not the audited C. Do not substitute an MP3 or processed copy.')
    return src


def run_job(source,root,write_mp3=True,expected_hash=None,interrupt_after=None):
    source=Path(source).resolve();root=Path(root).resolve()
    if root==source.parent or source.parent in root.parents:raise ValueError('Output must be outside the original audio/job directory')
    info=sf.info(source)
    if source.suffix.lower() not in ('.wav','.flac') or info.channels!=2 or info.samplerate not in (44100,48000,88200,96000) or info.duration<0.5:
        raise ValueError('Stereo WAV/FLAC, 44.1/48/88.2/96 kHz, at least 0.5 seconds required')
    h=file_hash(source)
    if expected_hash is not None and h!=expected_hash:raise ValueError('Input fingerprint mismatch')
    versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')}
    ident=dict(input_sha256=h,version=VERSION,code_sha256=file_hash(__file__),config=CONFIG,versions=versions,write_mp3=write_mp3)
    job=root/('sub_'+obj_hash(ident)[:20]);job.mkdir(parents=True,exist_ok=True)
    with job_lock(job/'job.lock'),Progress(job) as progress:
        try:
            final=job/'RESULT';proof=final/'PROOF.json'
            if final.exists():
                if not proof.exists():raise RuntimeError('Foreign/incomplete RESULT directory; nothing overwritten')
                saved=read_json(proof)
                if saved.get('identity')!=ident:raise RuntimeError('Foreign RESULT identity')
                for name,sha in saved['files'].items():
                    if file_hash(final/name)!=sha:raise RuntimeError('Result modified: '+name)
                if file_hash(source)!=h:raise RuntimeError('Input changed')
                report=read_json(final/'SUB_REPORT.json');report['rerun_status']='IDEMPOTENT_SKIP'
                print('IDEMPOTENT_SKIP:',final,flush=True);return report,final
            (job/'analysis').mkdir(exist_ok=True);atomic_json(job/'identity.json',ident)
            failures=read_json(job/'failure.json').get('count',0) if (job/'failure.json').exists() else 0
            if failures>=3:raise RuntimeError('Three failures recorded. Stop and inspect SUB_FAILURE.json; no automatic retry.')
            base=measure(source,progress,'MEASURE_BASELINE')
            if base['lufs_i'] is None:raise ValueError('Silent input: no low-end experiment is needed')
            if abs(base['lufs_i']-CONFIG['target_lufs'])>0.10:raise ValueError('Use the already level-matched C near -14 LUFS, not another master')
            if base['true_peak_dbtp_estimate']>CONFIG['pcm_tp_ceiling']:raise ValueError('Baseline already exceeds the experimental peak ceiling; no limiter is added')
            rows,acache=collect_frames(source,job,progress,interrupt_after)
            events,rejected=make_events(rows,source)
            atomic_json(job/'events.json',dict(events=events,rejected=rejected,frame_reason_counts=dict(Counter(r['reason'] for r in rows))))
            choices=[];chosen=None;selected_scale=0.0
            delta,dcache=render(source,job,events,progress,1.0,label='delta');dm=measure(delta,progress,'MEASURE_ADDED_LAYER')
            if events:
                if dm['above_110_energy_db'] is None or dm['above_110_energy_db']>CONFIG['leakage_above_110_limit_db']:
                    raise RuntimeError('Added-layer leakage above 110 Hz fails the engineering gate')
                if dm['below_20_energy_db']>CONFIG['layer_below_20_limit_db']:
                    raise RuntimeError('Added-layer energy below 20 Hz fails the engineering gate')
                for i,scale in enumerate(CONFIG['scales']):
                    raw,cache=render(source,job,events,progress,scale,label=f'raw_{i}')
                    met=measure(raw,progress,'MEASURE_RAW');gain_db=CONFIG['target_lufs']-met['lufs_i'];gain=10**(gain_db/20)
                    allowed=abs(gain_db)<=CONFIG['max_matching_gain_change_db'] and met['true_peak_dbtp_estimate']+gain_db<=CONFIG['pcm_tp_ceiling']
                    choices.append(dict(scale=scale,gain_db=gain_db,raw_metrics=met,engineering_gate=allowed,cache=cache))
                    if not allowed:continue
                    candidate,_=render(source,job,events,progress,scale,gain,label=f'matched_{i}')
                    cm=measure(candidate,progress,'VALIDATE_MATCHED')
                    if abs(cm['lufs_i']-CONFIG['target_lufs'])>.05 or cm['true_peak_dbtp_estimate']>CONFIG['pcm_tp_ceiling']:
                        choices[-1]['engineering_gate']=False;continue
                    chosen=candidate;selected_scale=scale;break
            status='RENDERED_EXPERIMENT_NOT_QUALITY_APPROVAL' if chosen else ('NO_ELIGIBLE_ADDITION' if not events else 'NO_ADDITION_WITHIN_GATES')
            stage=job/'publish_staging'
            if stage.exists():shutil.rmtree(stage)
            stage.mkdir();shutil.copyfile(source,stage/'CONTROL_C.wav');shutil.copyfile(chosen or source,stage/'SUB_AUGMENTED.wav')
            tmp=stage/'DELTA_SUB_FLOAT.wav'
            with sf.SoundFile(tmp,'w',samplerate=info.samplerate,channels=1,format='WAV',subtype='FLOAT') as f:
                width=int(CONFIG['render_chunk_seconds']*info.samplerate)
                for a in range(0,info.frames,width):
                    progress.set('EXPORT_DELTA',a,info.frames)
                    f.write(layer_chunk(events if chosen else [],a,min(width,info.frames-a),info.samplerate,selected_scale))
            final_met=measure(chosen,progress,'FINAL_METRICS') if chosen else base
            report=dict(version=VERSION,status=status,identity=ident,source_name=source.name,
                        source_unchanged=False,production_core_modified=False,winner_audio_modified=False,
                        baseline_metrics=base,output_metrics=final_met,unscaled_layer_metrics=dm,
                        output_pcm_sha256=pcm_hash(stage/'SUB_AUGMENTED.wav'),
                        selected_scale=selected_scale,
                        matched_output_gain_db=(CONFIG['target_lufs']-choices[-1]['raw_metrics']['lufs_i']) if chosen else 0.0,
                        proposal_trials=choices,analysis_cache=acache,delta_cache=dcache,
                        eligible_events=len(events),selected_events=len(events) if chosen else 0,
                        selected_seconds=sum(e['end']-e['start'] for e in events) if chosen else 0.0,
                        frame_reason_counts=dict(Counter(r['reason'] for r in rows)),rejected_runs=rejected,
                        limits=['Synthetic-tested research prototype; not validated on this real mix yet.',
                                'No semantic bass/kick separation, key detection, or chord recognition.',
                                'Periodicity and harmonic support are heuristic evidence, not calibrated probabilities.',
                                'Short/ambiguous notes, pure sine sources, and large glides may be left unchanged.',
                                'No-op does not prove that the mix has enough bass.',
                                'Band leakage and true peak are numerical estimates, not certified measurements.',
                                'Output is common_gain * (C + DELTA_SUB_FLOAT), up to float rounding.',
                                'WAV metadata may vary across clean runs; determinism compares decoded PCM, not WAV header timestamps.'])
            codec={};ff=ffmpeg_path() if write_mp3 else None
            if write_mp3 and not ff:raise RuntimeError('Existing ffmpeg/imageio-ffmpeg not found. No installation was attempted.')
            if ff:
                blind=stage/'BLIND_TEST';blind.mkdir();names=['CONTROL_C','SUB_AUGMENTED']
                if int(h[:2],16)%2:names.reverse()
                mapping=dict(zip(('A','B'),names))
                for letter,name in mapping.items():
                    progress.set('ENCODE_'+letter);dest=blind/f'LISTEN_{letter}_320kbps.mp3'
                    codec_file(ff,stage/(name+'.wav'),dest)
                    decoded=job/f'codec_{letter}_decoded.wav';codec_file(ff,dest,decoded,True)
                    codec[name]=measure(decoded,progress,'CODEC_QC_'+letter)
                vals=[m['lufs_i'] for m in codec.values()]
                if any(v is None for v in vals) or max(vals)-min(vals)>.10 or any(m['true_peak_dbtp_estimate']>CONFIG['codec_tp_ceiling'] for m in codec.values()):
                    raise RuntimeError('MP3 round-trip level/peak gate failed; no listening package published')
                (stage/'REVEAL_AFTER_LISTENING.txt').write_text('\n'.join(f'{k} = {v}' for k,v in mapping.items()),encoding='utf-8')
                with zipfile.ZipFile(stage/'PDRM_Note_Sub_BLIND_MP3.zip','w',zipfile.ZIP_STORED) as z:
                    for p in sorted(blind.glob('*.mp3')):z.write(p,p.name)
            report['codec']=codec
            if file_hash(source)!=h:raise RuntimeError('Input changed during processing; result not published')
            report['source_unchanged']=True;atomic_json(stage/'SUB_REPORT.json',report)
            atomic_json(stage/'NOTE_EVENTS.json',dict(events=events,rejected=rejected))
            md=f'# PDRM 音符追従サブ補完 — 実行結果\n\n状態: `{status}`\n\n採用イベント数: {report["selected_events"]}\n追加対象時間: {report["selected_seconds"]:.2f}秒\n追加レイヤー倍率: {selected_scale}\n\n原C・本番DSPは変更していません。音質の合格判定ではありません。\n\n音程推定は2mix内の周期性と倍音の検査であり、楽器を意味的に分離していません。\n曖昧な区間は生成しません。ゼロ追加は低音十分の証明ではありません。\n\n`SUB_REPORT.json`と`NOTE_EVENTS.json`に処理・見送り理由があります。\n'
            (stage/'SUB_REPORT.md').write_text(md,encoding='utf-8')
            for p in stage.rglob('*'):
                if p.is_file():sync_owned_file(p)
            hashes={str(p.relative_to(stage)).replace('\\','/'):file_hash(p) for p in stage.rglob('*') if p.is_file()}
            atomic_json(stage/'PROOF.json',dict(identity=ident,files=hashes))
            if final.exists():raise RuntimeError('RESULT appeared during publication; nothing overwritten')
            os.rename(stage,final);progress.set('COMPLETE',1,1)
            print(status,'\n',final/'SUB_REPORT.json',flush=True);return report,final
        except Exception as exc:
            old=read_json(job/'failure.json').get('count',0) if (job/'failure.json').exists() else 0
            failure=dict(status='FAILED_NOT_PUBLISHED',count=old+1,error=repr(exc),traceback=traceback.format_exc(),stage=progress.state)
            atomic_json(job/'failure.json',failure);atomic_json(job/'SUB_FAILURE.json',failure)
            print('FAILED. Do not repeat blindly. Diagnostic:',job/'SUB_FAILURE.json',flush=True);raise


def main():
    parser=argparse.ArgumentParser(description='Isolated note-following sub-bass experiment; accepted C only by default')
    parser.add_argument('--manifest',type=Path);parser.add_argument('--output-root',type=Path)
    args=parser.parse_args();path=args.manifest
    if path is None:
        import tkinter as tk
        from tkinter import filedialog
        app=tk.Tk();app.withdraw()
        chosen=filedialog.askopenfilename(title='Select accepted Round 9 manifest.json',filetypes=[('Round9 manifest','manifest.json')])
        app.destroy()
        if not chosen:print('Cancelled. No files changed.');return
        path=Path(chosen)
    src=validate_manifest(path)
    root=args.output_root or Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share')))/'PDRM_Local_Render_Engine_v1'/'note_sub_lab'
    source_job=path.resolve().parent if path.is_file() else path.resolve()
    if root.resolve()==source_job or source_job in root.resolve().parents:raise ValueError('Do not put output inside the original Round9 job')
    run_job(src,root,write_mp3=True,expected_hash=KNOWN_C)


if __name__=='__main__':main()
