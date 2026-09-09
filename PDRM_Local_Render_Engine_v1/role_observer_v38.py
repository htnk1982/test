"""Per-band, analysis-only extension to the existing research observer.

The same original 8-second core is observed with distinct neighbouring contexts.
Neither agreement nor source-energy shares are calibrated correctness scores.
The original-mix spectrum and each estimated role are recorded on the SAME band
clock, including the former 450-Hz coverage boundary. No stem audio is returned.
"""
from __future__ import annotations
from pathlib import Path
import math
import time
import numpy as np
import soundfile as sf
from scipy import signal
from role_observer_v37 import _features
from stem_observer_lab import sha, CHECKPOINT_SHA256

VERSION='role-observer-0.3.0'

def observe_bandwise(model,source,start,end,pads=(1.,2.)):
    source=Path(source);info=sf.info(source)
    if info.channels!=2 or info.samplerate not in (32000,44100,48000,88200,96000):
        raise ValueError('Supported stereo source required')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (start,end,*pads)):
        raise ValueError('Finite second-valued times required')
    if not 0<=start<end<=info.duration or not .5<=end-start<=16:
        raise ValueError('Bounded original source core required')
    if len(pads)!=2 or pads[0]==pads[1] or min(pads)<.5 or max(pads)>4:
        raise ValueError('Two distinct, bounded observer contexts required')
    digest=sha(source);t0=time.monotonic();results=[]
    n=4096;hop=240;fs=12000;fc=80*2**(np.arange(20)/6)
    freq=np.fft.rfftfreq(n,1/fs);fold=np.ones(len(freq));fold[1:-1]=2
    win=signal.windows.hann(n,sym=False)
    weights=np.maximum(1-np.abs(np.log2(np.maximum(freq[None,:],1)/fc[:,None]))/(1/6),0)*fold
    normalizer=np.sum(win*win)*n
    for pad in pads:
        left=max(0.,start-pad);right=min(info.duration,end+pad)
        with sf.SoundFile(source) as f:
            first=round(left*info.samplerate);last=round(right*info.samplerate);f.seek(first)
            raw=f.read(last-first,dtype='float32',always_2d=True)
        if not np.isfinite(raw).all():raise ValueError('Non-finite observer source')
        g=math.gcd(info.samplerate,44100)
        x=signal.resample_poly(raw,44100//g,info.samplerate//g,axis=0,window=('kaiser',10.5)).astype('float32')
        mean=float(x.mean());scale=float(x.mean(axis=1).std())
        # Existing model input convention retained. Degenerate anti-phase input
        # is not called silence/healthy: it is an explicit observer limitation.
        if scale<1e-6:raise ValueError('Insufficient centred model input; observer unavailable')
        with model.torch.inference_mode():
            s=model.model(model.torch.from_numpy(((x-mean)/scale).T.copy())[None])[0].cpu().numpy()*scale
        if s.shape!=(4,2,len(x)) or not np.isfinite(s).all():raise RuntimeError('Invalid separator output')
        i=round((start-left)*44100);j=i+round((end-start)*44100)
        if j>len(x):raise RuntimeError('Observer core exceeds sampled source')
        result=_features(x[i:j],s[:,:,i:j],44100,start)
        stack=np.concatenate([x.T[None],s],axis=0).transpose(0,2,1)
        g=math.gcd(44100,fs);z=signal.resample_poly(stack,fs//g,44100//g,axis=1,window=('kaiser',10.5))
        centres=round((start-left)*fs)+np.arange(0,round((end-start)*fs),hop)
        # Only real file ends are zero-extended. Interior cores use actual
        # context; never pretend padding supplies a missing observation.
        zz=np.pad(z,((0,0),(n//2,n//2),(0,0)))
        spectral=[]
        for a in range(0,len(centres),64):
            frames=np.stack([zz[:,c:c+n,:] for c in centres[a:a+64]])
            ft=np.fft.rfft(frames*win[None,None,:,None],axis=2)
            power=np.mean(abs(ft)**2,axis=-1)/normalizer
            spectral.append(power@weights.T)
        result['band_power']=np.concatenate(spectral,axis=0)
        result['band_time']=start+np.arange(len(centres))*.02
        result['reconstruction_error_db']=float(20*np.log10(max(np.sqrt(np.mean((s[:,:,i:j].sum(axis=0).T-x[i:j])**2))/max(np.sqrt(np.mean(x[i:j]**2)),1e-15),1e-15)))
        results.append(result)
    if sha(source)!=digest:raise RuntimeError('Source changed during observation')
    arrays={k:np.stack([r[k] for r in results]) for k in ('low_power','body_power','focus_power','bass_f0_hz','bass_periodicity','band_power')}
    arrays.update(time=results[0]['time'],band_time=results[0]['band_time'],fc=fc)
    meta=dict(version=VERSION,source_sha256=digest,source_name=source.name,start_seconds=start,end_seconds=end,
              source_frames=info.frames,source_samplerate=info.samplerate,source_order=['mix','drums','bass','other','vocals'],
              contexts_seconds=list(pads),model_sha256=CHECKPOINT_SHA256,model='HDEMUCS_HIGH_MUSDB',
              seconds=time.monotonic()-t0,probabilities_calibrated=False,stem_audio_in_output=False,
              reconstruction_error_db=[r['reconstruction_error_db'] for r in results],model_versions=model.versions)
    return arrays,meta
