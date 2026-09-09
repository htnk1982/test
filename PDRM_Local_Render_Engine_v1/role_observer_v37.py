"""Analysis-only, dual-context evidence. Not a calibrated source probability.

No estimated stem samples leave this module. It runs the research checkpoint
through the previous, hash-validated loader, then returns power/pitch features.
"""
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import uniform_filter1d
from stem_observer_lab import Observer, sha, SOURCES
VERSION='role-observer-0.2.0'


def _features(original, stems, sr, start):
    # x shape [source,moment,channel]. Keep stereo energy (not the mono sum).
    src=np.concatenate([original[None],stems.transpose(0,2,1)],axis=0)
    g=math.gcd(sr,12000)
    x=signal.resample_poly(src,12000//g,sr//g,axis=1,window=('kaiser',10.5))
    sr=12000; hop=120; w=720
    out={'time':start+np.arange(0,x.shape[1],hop)/sr}
    for name,lo,hi in [('low',25,120),('body',120,300),('focus',300,450)]:
        z=signal.sosfiltfilt(signal.butter(4,[lo,hi],btype='bandpass',fs=sr,output='sos'),x,axis=1)
        p=np.maximum(uniform_filter1d(np.mean(z*z,axis=-1),w,axis=1,mode='nearest')[:,::hop],1e-24)
        out[name+'_power']=p.T
    # Periodicity from the bass estimate is supplementary evidence only.
    bass=x[2].mean(axis=1); n=2400; pad=n//2; y=np.pad(bass,(pad,pad)); pitches=[];periods=[]
    lo=int(sr/160);hi=int(sr/30)
    for c in range(0,len(bass),hop):
        a=y[c:c+n];a=a-a.mean()
        if np.mean(a*a)<1e-14:pitches.append(0.);periods.append(0.);continue
        ac=signal.correlate(a,a,mode='full',method='fft')[n-1:]
        en=np.r_[0,np.cumsum(a*a)];lag=np.arange(n)
        den=en[n-lag]+en[n]-en[lag]
        nd=2*ac/np.maximum(den,1e-24)
        peaks,_=signal.find_peaks(nd[lo:hi]);peaks+=lo
        if not len(peaks):pitches.append(0.);periods.append(0.);continue
        k=int(peaks[np.argmax(nd[peaks])]);h=.5*(nd[k-1]-nd[k+1])/(nd[k-1]-2*nd[k]+nd[k+1]) if abs(nd[k-1]-2*nd[k]+nd[k+1])>1e-12 else 0
        pitches.append(sr/(k+np.clip(h,-.5,.5)));periods.append(float(np.clip(nd[k],0,1)))
    out['bass_f0_hz']=np.asarray(pitches);out['bass_periodicity']=np.asarray(periods)
    return out


def observe_dual(model, source, start, end, pads=(1.,2.)):
    """Reuse the same core with two surrounding contexts, without truth claims."""
    source=Path(source);digest=sha(source);info=sf.info(source)
    if not (0<=start<end<=info.duration and end-start<=16):raise ValueError('Invalid observer core')
    results=[]
    for pad in pads:
        left=max(0,start-pad);right=min(info.duration,end+pad)
        with sf.SoundFile(source) as f:
            a=round(left*info.samplerate);b=round(right*info.samplerate);f.seek(a)
            raw=f.read(b-a,dtype='float32',always_2d=True)
        if raw.shape[1]!=2 or not np.isfinite(raw).all():raise ValueError('Invalid observer input')
        g=math.gcd(info.samplerate,44100);x=signal.resample_poly(raw,44100//g,info.samplerate//g,axis=0,window=('kaiser',10.5)).astype('float32')
        offset=float(x.mean());scale=float(x.mean(axis=1).std())
        if scale<1e-6:raise ValueError('Observer input too quiet')
        torch=model.torch
        with torch.inference_mode():
            s=model.model(torch.from_numpy(((x-offset)/scale).T.copy())[None])[0].cpu().numpy()*scale
        if s.shape!=(4,2,len(x)) or not np.isfinite(s).all():raise RuntimeError('Invalid separator result')
        i=round((start-left)*44100);j=i+round((end-start)*44100)
        result=_features(x[i:j],s[:,:,i:j],44100,start)
        result['reconstruction_error_db']=float(20*np.log10(max(np.sqrt(np.mean((s[:,:,i:j].sum(axis=0).T-x[i:j])**2))/max(np.sqrt(np.mean(x[i:j]**2)),1e-12),1e-15)))
        results.append(result)
    if sha(source)!=digest:raise RuntimeError('Observer source changed')
    if not np.array_equal(results[0]['time'],results[1]['time']):raise RuntimeError('Observer core clock mismatch')
    from stem_observer_lab import CHECKPOINT_SHA256
    arrays={'time':results[0]['time']}
    for k in ('low_power','body_power','focus_power','bass_f0_hz','bass_periodicity'):
        arrays[k]=np.stack([r[k] for r in results],axis=0)
    meta=dict(version=VERSION,source_sha256=digest,source_name=source.name,source_frames=info.frames,source_samplerate=info.samplerate,
        start_seconds=start,end_seconds=end,source_order=['mix']+list(SOURCES),contexts_seconds=list(pads),
        model_sha256=CHECKPOINT_SHA256,model='HDEMUCS_HIGH_MUSDB',model_versions=model.versions,
        reconstruction_error_db=[r['reconstruction_error_db'] for r in results],
        probabilities_calibrated=False,stem_audio_in_output=False)
    return arrays,meta
