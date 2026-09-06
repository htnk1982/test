"""Groove-first low-end controller lab.

Analysis may use uncertain semantic observers; all audible edits are applied to the
original physical stereo mix. Automatic octave-down synthesis is prohibited.
This is a lab module, not yet a production quality approval.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import percentile_filter, uniform_filter1d, gaussian_filter1d, median_filter
import note_sub_lab as io
import note_sub_lab_v02 as ns

VERSION='groove-lowend-lab-0.1.0'
EPS=1e-24

@dataclass(frozen=True)
class Config:
    analysis_sr:int=12000
    observer_sr:int=4000
    observer_grid_seconds:float=.020
    grid_seconds:float=.010
    low_lo_hz:float=20.0
    low_hi_hz:float=120.0
    deep_lo_hz:float=25.0
    deep_hi_hz:float=65.0
    body_lo_hz:float=65.0
    body_hi_hz:float=140.0
    mid_lo_hz:float=250.0
    mid_hi_hz:float=2000.0
    context_seconds:float=2.0
    max_trim_db:float=3.0
    onset_rise_db:float=3.0
    attack_protect_before:float=.030
    attack_protect_after:float=.100
    event_min_contrast_db:float=2.5
    octave_ratio_limit:float=1.20
    add_scale_cap:float=.35
    deep_body_no_need_db:float=-4.0
    deep_body_full_need_db:float=-16.0
    max_add_event_seconds:float=.80
    global_deep_rms_budget_db:float=.12
    low_fir_seconds:float=.040
    def validate(self,sr:int|None=None):
        vals=[v for v in asdict(self).values() if isinstance(v,(int,float))]
        if not all(math.isfinite(float(v)) for v in vals):raise ValueError('Non-finite config')
        if not 8000<=self.analysis_sr<=24000 or not 3000<=self.observer_sr<=12000:raise ValueError('Invalid analysis rate')
        if not 0<self.grid_seconds<=.05 or not 0<=self.max_trim_db<=4:raise ValueError('Invalid timing/trim')
        if not 15<=self.low_lo_hz<self.deep_lo_hz<self.deep_hi_hz<=self.low_hi_hz<self.body_hi_hz<self.mid_lo_hz<self.mid_hi_hz:
            raise ValueError('Invalid frequency bands')
        if sr is not None and sr not in (44100,48000,88200,96000):raise ValueError('Unsupported rate')


def _resample_mono(path:Path,cfg:Config):
    with sf.SoundFile(path) as f:
        sr=f.samplerate;x=f.read(dtype='float64',always_2d=True)
    io.finite(x);cfg.validate(sr);g=math.gcd(sr,cfg.analysis_sr)
    y=signal.resample_poly(x,cfg.analysis_sr//g,sr//g,axis=0,window=('kaiser',10.5))
    return np.mean(y,axis=1),sr


def _band(x,sr,lo,hi,order=4):
    sos=signal.butter(order,[lo,hi],btype='bandpass',fs=sr,output='sos')
    return signal.sosfiltfilt(sos,x)


def _grid_power(x,sr,dt,window):
    step=max(1,int(round(dt*sr)));w=max(1,int(round(window*sr)))
    p=np.maximum(uniform_filter1d(x*x,w,mode='nearest'),EPS)
    return p[::step]


def analyze_proxy_observer(path,cfg=Config()):
    """Conservative separation-free semantic proxy; never used as output audio."""
    path=Path(path)
    with sf.SoundFile(path) as f:
        sr0=f.samplerate;x=f.read(dtype='float64',always_2d=True)
    io.finite(x);g=math.gcd(sr0,cfg.observer_sr)
    mono=np.mean(signal.resample_poly(x,cfg.observer_sr//g,sr0//g,axis=0,window=('kaiser',10.5)),axis=1);sr=cfg.observer_sr
    nper=1024;hop=max(64,int(round(cfg.observer_grid_seconds*sr)));nover=nper-hop
    _,times,z=signal.stft(mono,fs=sr,nperseg=nper,noverlap=nover,boundary='zeros',padded=True)
    power=np.abs(z)**2
    h=median_filter(power,size=(1,17),mode='nearest');p=median_filter(power,size=(17,1),mode='nearest')
    denom=h+p+EPS;hm=h/denom;pm=p/denom;freqs=np.fft.rfftfreq(nper,1/sr)
    bass=(freqs>=30)&(freqs<=220);kick=(freqs>=25)&(freqs<=160)
    bass_power=np.sum(power[bass]*hm[bass],axis=0);drum_power=np.sum(power[kick]*pm[kick],axis=0)
    conf=bass_power/(bass_power+drum_power+EPS)
    return dict(mode='MIX_PROXY_HPSS',times=np.asarray(times),bass_power=bass_power,drum_power=drum_power,
                bass_confidence=np.clip(conf,0,1),claim='uncertain semantic evidence; not source separation')


def analyze_precomputed_stems(source,bass,drums,cfg=Config()):
    """Observer for external analysis-only stems; no stem audio is rendered."""
    source,bass,drums=map(Path,(source,bass,drums));si=sf.info(source)
    for p in (bass,drums):
        i=sf.info(p)
        if i.channels!=2 or i.samplerate!=si.samplerate or i.frames!=si.frames:raise ValueError('Observer stem shape mismatch')
    def curve(p,lo,hi):
        m,_=_resample_mono(p,cfg);b=_band(m,cfg.analysis_sr,lo,hi);return _grid_power(b,cfg.analysis_sr,cfg.grid_seconds,.040)
    bp=curve(bass,30,220);dp=curve(drums,25,160);n=min(len(bp),len(dp));bp,dp=bp[:n],dp[:n]
    times=np.arange(n)*cfg.grid_seconds;conf=bp/(bp+dp+EPS)
    return dict(mode='PRECOMPUTED_STEMS',times=times,bass_power=bp,drum_power=dp,bass_confidence=np.clip(conf,0,1),
                claim='analysis-only stems; rendered audio remains original two-mix')


def analyze_mix(path,cfg=Config()):
    path=Path(path);mono,_=_resample_mono(path,cfg);sr=cfg.analysis_sr;dt=cfg.grid_seconds
    low=_band(mono,sr,cfg.low_lo_hz,cfg.low_hi_hz);deep=_band(mono,sr,cfg.deep_lo_hz,cfg.deep_hi_hz)
    body=_band(mono,sr,cfg.body_lo_hz,cfg.body_hi_hz);mid=_band(mono,sr,cfg.mid_lo_hz,cfg.mid_hi_hz)
    fast=10*np.log10(_grid_power(low,sr,dt,.012));slow=10*np.log10(_grid_power(low,sr,dt,.060))
    deep_p=_grid_power(deep,sr,dt,.060);body_p=_grid_power(body,sr,dt,.060);mid_p=_grid_power(mid,sr,dt,.080)
    n=min(map(len,(fast,slow,deep_p,body_p,mid_p)));fast,slow=fast[:n],slow[:n];deep_p,body_p,mid_p=deep_p[:n],body_p[:n],mid_p[:n]
    ratio=slow-10*np.log10(mid_p);ratio_context=uniform_filter1d(ratio,size=max(1,int(round(2.0/dt))),mode='nearest')
    context=max(3,int(round(cfg.context_seconds/dt))|1)
    p20=percentile_filter(slow,20,size=context,mode='nearest');p90=percentile_filter(slow,90,size=context,mode='nearest')
    lag=max(1,int(round(.040/dt)));previous=np.concatenate([np.full(lag,fast[0]),fast[:-lag]])
    onset=(fast-previous>=cfg.onset_rise_db)&(slow>=p20+3.)
    inds=np.flatnonzero(onset);onsets=[];minsep=max(1,int(round(.080/dt)))
    for i in inds:
        if not onsets or i-onsets[-1]>=minsep:onsets.append(int(i))
        elif fast[i]>fast[onsets[-1]]:onsets[-1]=int(i)
    return dict(times=np.arange(n)*dt,fast_db=fast,low_db=slow,deep_power=deep_p,body_power=body_p,mid_power=mid_p,
                low_mid_ratio_db=ratio,ratio_context_db=ratio_context,p20_db=p20,p90_db=p90,onsets=onsets)


def plan_trim(features,cfg=Config()):
    """Preserve attacks; trim stable tails/floor when low end dominates locally."""
    dt=cfg.grid_seconds;slow=np.asarray(features['low_db']);ratio=np.asarray(features['low_mid_ratio_db'])
    rc=np.asarray(features['ratio_context_db']);p20=np.asarray(features['p20_db']);p90=np.asarray(features['p90_db']);n=len(slow)
    grad=np.abs(np.gradient(slow));depth=np.zeros(n,dtype=np.float64);onsets=list(features['onsets'])
    for k,oi in enumerate(onsets):
        nxt=onsets[k+1] if k+1<len(onsets) else n
        peak=float(np.max(slow[oi:min(n,oi+max(1,int(.12/dt))+1)]))
        minend=oi+max(1,int(.12/dt));maxend=min(n,oi+max(1,int(1.5/dt)),nxt);end=maxend
        for j in range(minend,maxend):
            if slow[j]<peak-10.:end=j;break
        a=oi+max(1,int(.070/dt))
        if end<=a:continue
        j=np.arange(a,end);tail=(j-a)/max(1,end-a)
        section=np.clip((rc[j]-.5)/4.,0,1);local=np.clip((ratio[j]-.5)/4.,0,1);stable=np.clip((1.7-grad[j])/1.7,0,1)
        dep=cfg.max_trim_db*(.20+.80*tail)*np.maximum(section*.7,local)*stable;depth[j]=np.maximum(depth[j],dep)
    span=np.maximum(p90-p20,3.);pos=np.clip((slow-p20)/span,0,1);stable=np.clip((.9-grad)/.9,0,1);section=np.clip((rc-1.)/4.,0,1)
    floor=cfg.max_trim_db*.65*stable*section*np.clip((pos-.15)/.55,0,1);depth=np.maximum(depth,floor)
    protected=np.zeros(n,dtype=bool);pre=max(0,int(round(cfg.attack_protect_before/dt)));post=max(1,int(round(cfg.attack_protect_after/dt)))
    for oi in onsets:protected[max(0,oi-pre):min(n,oi+post)]=True
    protected|=slow>=p90-.5
    depth[protected]=0.;depth=gaussian_filter1d(depth,sigma=max(.5,.025/dt),mode='nearest');depth[protected]=0.;depth=np.clip(depth,0,cfg.max_trim_db)
    return dict(times=np.asarray(features['times']),depth_db=depth,max_trim_db=float(np.max(depth)),mean_trim_db=float(np.mean(depth)),
                active_fraction=float(np.mean(depth>.10)),onsets=len(onsets))


def render_trim(source,dest,plan,cfg=Config(),progress=None):
    source,dest=Path(source),Path(dest);info=sf.info(source);cfg.validate(info.samplerate)
    taps=max(255,int(round(cfg.low_fir_seconds*info.samplerate))|1)
    coeff=signal.firwin(taps,[cfg.low_lo_hz,cfg.low_hi_hz],pass_zero=False,window=('kaiser',10.5),fs=info.samplerate)
    pad=len(coeff)//2;width=8*info.samplerate;tmp=dest.with_suffix('.partial.wav')
    with sf.SoundFile(source) as src,sf.SoundFile(tmp,'w',samplerate=info.samplerate,channels=2,format='WAV',subtype='FLOAT') as out:
        for start in range(0,info.frames,width):
            end=min(info.frames,start+width);a=max(0,start-pad);b=min(info.frames,end+pad);src.seek(a)
            x=src.read(b-a,dtype='float64',always_2d=True);io.finite(x);dry=x[start-a:end-a]
            band=signal.oaconvolve(x,coeff[:,None],mode='same',axes=0)[start-a:end-a];t=np.arange(start,end,dtype=np.float64)/info.samplerate
            dep=np.interp(t,plan['times'],plan['depth_db']);gain=10**(-dep/20);y=dry+(gain[:,None]-1.)*band
            y[np.all(dry==0,axis=1)]=0.;io.finite(y);out.write(y.astype('float32'))
            if progress:progress.set('GROOVE_LOWEND_TRIM',end,info.frames)
    io.sync_owned_file(tmp);tmp.replace(dest);return dest


def _event_metrics(path,event,cfg=Config()):
    start,end=float(event['start']),float(event['end']);dur=end-start
    with sf.SoundFile(path) as f:
        sr=f.samplerate;a=max(0,int(round((start-.20)*sr)));b=min(f.frames,int(round((end+.20)*sr)));f.seek(a);x=f.read(b-a,dtype='float64',always_2d=True)
    io.finite(x);g=math.gcd(sr,cfg.analysis_sr);y=signal.resample_poly(x,cfg.analysis_sr//g,sr//g,axis=0,window=('kaiser',10.5));m=np.mean(y,axis=1)
    deep=_band(m,cfg.analysis_sr,cfg.deep_lo_hz,cfg.deep_hi_hz);body=_band(m,cfg.analysis_sr,cfg.body_lo_hz,cfg.body_hi_hz);low=_band(m,cfg.analysis_sr,cfg.low_lo_hz,cfg.low_hi_hz)
    s=max(0,int(round(.20*cfg.analysis_sr)));e=min(len(m),s+max(1,int(round(dur*cfg.analysis_sr))))
    dp=float(np.mean(deep[s:e]**2)+EPS);bp=float(np.mean(body[s:e]**2)+EPS);eventp=float(np.mean(low[s:e]**2)+EPS)
    pre=low[max(0,s-int(.15*cfg.analysis_sr)):s];post=low[e:min(len(low),e+int(.15*cfg.analysis_sr))]
    vals=[float(np.mean(v*v)+EPS) for v in (pre,post) if len(v)];valley=min(vals) if vals else eventp;contrast=10*math.log10(eventp/valley)
    lp=np.maximum(uniform_filter1d(low*low,max(1,int(.025*cfg.analysis_sr)),mode='nearest'),EPS)
    knots=np.asarray(event['times']);idx=np.clip(np.round((knots-(start-.20))*cfg.analysis_sr).astype(int),0,len(lp)-1)
    env=np.sqrt(lp[idx]);floor=math.sqrt(valley);peak=float(max(np.max(env),floor+EPS));shape=np.clip((env-floor)/(peak-floor+EPS),0,1);shape=io.smoother(shape)
    return dict(deep_body_db=10*math.log10(dp/bp),event_valley_contrast_db=contrast,envelope=shape.tolist())


def gate_and_shape_events(events,physical,observer=None,cfg=Config()):
    """No octave-down. Same-fundamental additions follow source envelope and need."""
    accepted=[];decisions=[];ot=None;oc=None
    if observer is not None:
        ot=np.asarray(observer.get('times',[]),dtype=float);oc=np.asarray(observer.get('bass_confidence',[]),dtype=float)
    for e0 in events:
        e={k:(list(v) if isinstance(v,list) else v) for k,v in e0.items()};f0=float(e.get('median_f0_hz',0));sub=float(e.get('median_sub_hz',0));ratio=f0/max(sub,EPS)
        rec=dict(start=float(e['start']),end=float(e['end']),f0_hz=f0,target_hz=sub)
        if observer is None or ot is None or len(ot)<2 or oc is None or len(oc)!=len(ot):
            rec.update(action='KEEP',reason='semantic_observer_unavailable');decisions.append(rec);continue
        if ratio>cfg.octave_ratio_limit:
            rec.update(action='KEEP',reason='automatic_octave_down_prohibited');decisions.append(rec);continue
        if e['end']-e['start']>cfg.max_add_event_seconds:
            rec.update(action='KEEP',reason='sustained_event_no_automatic_sub');decisions.append(rec);continue
        met=_event_metrics(physical,e,cfg);rec.update(deep_body_db=met['deep_body_db'],event_valley_contrast_db=met['event_valley_contrast_db'])
        if met['event_valley_contrast_db']<cfg.event_min_contrast_db:
            rec.update(action='KEEP',reason='insufficient_event_to_valley_contrast');decisions.append(rec);continue
        mask=(ot>=e['start'])&(ot<=e['end']);conf=float(np.median(oc[mask])) if np.any(mask) else 0.;rec['observer_bass_confidence']=conf
        threshold=.62 if observer.get('mode')=='PRECOMPUTED_STEMS' else .72
        if conf<threshold:
            rec.update(action='KEEP',reason='semantic_bass_confidence_low');decisions.append(rec);continue
        need=float(np.clip((cfg.deep_body_no_need_db-met['deep_body_db'])/(cfg.deep_body_no_need_db-cfg.deep_body_full_need_db),0,1));scale=cfg.add_scale_cap*need
        if scale<.03:
            rec.update(action='KEEP',reason='deep_fundamental_already_sufficient');decisions.append(rec);continue
        amps=np.asarray(e['amplitudes'],dtype=float);shape=np.asarray(met['envelope'],dtype=float)
        if len(shape)!=len(amps):raise RuntimeError('Event envelope shape mismatch')
        e['amplitudes']=(amps*shape*scale).tolist();e['groove_scale']=scale;e['groove_observer']=observer.get('mode')
        if not np.any(np.asarray(e['amplitudes'])>1e-6):
            rec.update(action='KEEP',reason='shaped_amount_negligible');decisions.append(rec);continue
        accepted.append(e);rec.update(action='SUB_ACCENT',reason='same_fundamental_event_reinforcement',scale=scale);decisions.append(rec)
    return accepted,decisions


def band_rms_db(path,lo,hi,cfg=Config()):
    m,_=_resample_mono(Path(path),cfg);b=_band(m,cfg.analysis_sr,lo,hi)
    return 10*math.log10(float(np.mean(b*b))+EPS)
