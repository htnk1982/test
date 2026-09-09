"""Bounded spectral-persistence candidate. Analysis LAB, not taste certification.

Detects sustained *excess relative to supplied role-positive references*, not
long tones per se. A two-context semantic observer gates actuation; it never
supplies output samples. No reference filename is visible to inference.
"""
from dataclasses import dataclass, asdict
import math,hashlib,json
import numpy as np
from scipy import signal
from scipy.ndimage import uniform_filter1d, maximum_filter1d
VERSION='spectral-persistence-lab-0.1.0'
EPS=1e-24

@dataclass(frozen=True)
class Config:
    analysis_sr:int=12000
    frame_samples:int=4096
    hop_samples:int=240
    minimum_band_excess_db:float=.75
    reference_margin_db:float=.5
    max_cut_db:float=1.5
    persistence_seconds:float=.30
    smoothing_seconds:float=.12
    observer_edge_guard_seconds:float=.40
    low_center_hz:float=120.
    high_center_hz:float=600.
    max_observer_disagreement:float=.25
    minimum_role_share:float=.55
    def validate(self):
        for k,v in asdict(self).items():
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Nonfinite config '+k)
        if self.analysis_sr!=12000 or self.frame_samples!=4096 or self.hop_samples!=240:raise ValueError('Fixed calibrated analysis clock required')
        if not 0<=self.max_cut_db<=1.5 or not .1<=self.minimum_band_excess_db<=3:raise ValueError('Invalid processing budget')
        if not .2<=self.persistence_seconds<=2 or not .06<=self.smoothing_seconds<=.5:raise ValueError('Invalid time units')
        if not .35<=self.observer_edge_guard_seconds<=1:raise ValueError('Invalid observer edge guard')
        if not 80<=self.low_center_hz<self.high_center_hz<=700:raise ValueError('Invalid frequency scope')
        if not 0<self.max_observer_disagreement<=.5 or not .5<=self.minimum_role_share<=1:raise ValueError('Invalid evidence thresholds')
        return self

def centers():return 80*2**(np.arange(20)/6)

def validate_features(f):
    t=np.asarray(f['time']);freq=np.asarray(f['fc']);d=np.asarray(f['db']);full=np.asarray(f['full_db'])
    if len(t)<25 or d.shape!=(len(t),len(freq)) or full.shape!=t.shape or np.any(np.diff(t)<=0):raise ValueError('Invalid feature shape/clock')
    if not all(np.isfinite(v).all() for v in (t,freq,d,full)):raise ValueError('Nonfinite features')
    if not np.allclose(np.diff(t),.02,atol=1e-9) or not np.allclose(freq,centers(),rtol=0,atol=1e-9):raise ValueError('Feature unit/grid mismatch')

def extract(x,sr,anchor_gain_db,cfg=Config()):
    cfg.validate();x=np.asarray(x,dtype=np.float64)
    if sr not in (32000,44100,48000,88200,96000) or x.ndim!=2 or x.shape[1]!=2 or len(x)<sr*.5 or not np.isfinite(x).all():raise ValueError('Invalid stereo source')
    if not math.isfinite(anchor_gain_db):raise ValueError('Invalid gain anchor')
    g=math.gcd(sr,cfg.analysis_sr);y=signal.resample_poly(x,cfg.analysis_sr//g,sr//g,axis=0,window=('kaiser',10.5))
    n=cfg.frame_samples;hop=cfg.hop_samples;pad=n//2;y=np.pad(y,((pad,pad),(0,0)))
    w=signal.windows.hann(n,sym=False);f=np.fft.rfftfreq(n,1/cfg.analysis_sr);fc=centers()
    fold=np.ones(len(f));fold[1:-1]*=2
    weights=np.maximum(1-np.abs(np.log2(np.maximum(f[None,:],1)/fc[:,None]))/(1/6),0)*fold
    cs=np.arange(0,len(y)-2*pad,hop);power=[];full=[]
    for a in range(0,len(cs),128):
        frames=np.stack([y[c:c+n] for c in cs[a:a+128]])
        z=np.fft.rfft(frames*w[None,:,None],axis=1)
        p=np.mean(abs(z)**2,axis=-1)/(np.sum(w*w)*n)
        power.append(p@weights.T);full.append(np.sum(p*fold,axis=1))
    return dict(time=cs/cfg.analysis_sr,fc=fc,db=10*np.log10(np.maximum(np.concatenate(power),EPS))+anchor_gain_db,
                full_db=10*np.log10(np.maximum(np.concatenate(full),EPS))+anchor_gain_db)

def signature(f):
    validate_features(f);active=np.asarray(f['full_db'])>-45
    if active.sum()<25:raise ValueError('Insufficient audible context')
    return np.percentile(np.asarray(f['db'])[active],20,axis=0)

def calibrate(features,ids,cfg=Config()):
    cfg.validate()
    if len(features)<4 or len(features)!=len(ids) or len(set(ids))!=len(ids):raise ValueError('Independent positive reference groups required')
    sig=np.stack([signature(f) for f in features]);caps=sig.max(axis=0)+cfg.reference_margin_db
    atlas=dict(schema=1,version=VERSION,config=asdict(cfg),caps_db=caps.tolist(),reference_ids=list(ids),
               reference_signatures_db=sig.tolist(),scope='Exploratory same-corpus reference boundary; not a perceptual probability')
    atlas['sha256']=hashlib.sha256(json.dumps(atlas,sort_keys=True).encode()).hexdigest();return atlas

def _observer_gate(t,arrays,meta,source_sha,cfg,power_key="focus_power"):
    if meta is None or arrays is None:return np.zeros(len(t),bool),dict(status='ABSTAIN_NO_OBSERVER')
    if meta.get('source_sha256')!=source_sha:raise ValueError('Observer/source identity mismatch')
    if meta.get('version')!='role-observer-0.2.0' or meta.get('source_order')!=['mix','drums','bass','other','vocals']:raise ValueError('Observer schema mismatch')
    ot=np.asarray(arrays['time']);p=np.asarray(arrays[power_key])
    if p.shape!=(2,len(ot),5) or np.any(np.diff(ot)<=0) or not np.isfinite(p).all() or (p<0).any():raise ValueError('Invalid observer curves')
    shares=p[:,:,1:]/np.maximum(p[:,:,1:].sum(axis=-1,keepdims=True),EPS)
    winners=shares.argmax(axis=-1);stable=(winners[0]==winners[1])&(np.max(shares,axis=-1).min(axis=0)>=cfg.minimum_role_share)
    distance=np.sum(abs(shares[0]-shares[1]),axis=-1)/2
    stable&=distance<=cfg.max_observer_disagreement
    # Voice-dominant regions are NOT altered by this low-end branch. A vocal
    # correction needs its own diagnosis instead of calling it bass resonance.
    stable&=winners[0]!=3
    stable&=p[:,:,0].min(axis=0)>1e-12
    support=(t>=float(meta['start_seconds'])+cfg.observer_edge_guard_seconds)&(t<=float(meta['end_seconds'])-cfg.observer_edge_guard_seconds)
    permitted=(np.interp(t,ot,stable.astype(float),left=0,right=0)>.999)&support
    count={name:int(np.count_nonzero((winners[0]==i)&stable)) for i,name in enumerate(['drums','bass','other','vocals'])}
    return permitted,dict(status='OBSERVED',stable_nonvocal_frames=count,total_observer_frames=len(ot),
        median_share_disagreement=float(np.median(distance)),source_sha256=source_sha,
        probability_claim=False)

def plan(f,atlas,source_sha,observer=None,cfg=Config()):
    cfg.validate();validate_features(f)
    if atlas.get('version')!=VERSION or atlas.get('config')!=asdict(cfg):raise ValueError('Atlas mismatch')
    plain=dict(atlas);h=plain.pop('sha256',None)
    if hashlib.sha256(json.dumps(plain,sort_keys=True).encode()).hexdigest()!=h:raise ValueError('Atlas altered')
    caps=np.asarray(atlas['caps_db']);sig=signature(f);fc=np.asarray(f['fc']);t=np.asarray(f['time']);d=np.asarray(f['db'])
    eligible=(sig-caps>=cfg.minimum_band_excess_db)&(fc>=cfg.low_center_hz)&(fc<=cfg.high_center_hz)
    permission=np.zeros((len(t),len(fc)),dtype=bool);oreport={}
    for key,sel in [('body_power',(fc>=120)&(fc<300)),('focus_power',(fc>=300)&(fc<=450))]:
        gate,record=_observer_gate(t,*(observer or (None,None)),source_sha,cfg,key)
        permission[:,sel]=gate[:,None];oreport[key]=record
    # >450 Hz is outside the current role observer. Detect, but do not actuate.
    # A calibrated band floor is the opportunity, not permission to cut all tones.
    above=d>caps[None,:]+cfg.minimum_band_excess_db
    count=max(1,round(cfg.persistence_seconds/.02))
    persistent=uniform_filter1d(above.astype(float),count,axis=0,mode='nearest')>=.85
    # Protect a source broadband rise, rather than a fixed beat-grid transient.
    full=np.asarray(f['full_db']);rise=full-np.r_[np.repeat(full[0],3),full[:-3]]
    protect=maximum_filter1d((rise>3).astype(float),size=13,mode='nearest')>0
    raw=np.minimum(cfg.max_cut_db,np.maximum(0,d-caps[None,:]))
    raw*=eligible[None,:]&persistent&permission&~protect[:,None]
    n=max(3,round(cfg.smoothing_seconds/.02)|1);w=signal.windows.hann(n,sym=True);w/=w.sum()
    depth=np.stack([np.convolve(np.pad(raw[:,k],(n//2,n//2),mode='edge'),w,mode='valid') for k in range(len(fc))],axis=1)
    # Reapply support boundaries conservatively with a distance-based smooth fade,
    # not a hard post-smoothing switch which could generate control clicks.
    from scipy.ndimage import distance_transform_edt
    safe=permission&~protect[:,None]
    fade=np.stack([np.clip(distance_transform_edt(safe[:,j])*.02/.12,0,1) for j in range(len(fc))],axis=1)
    depth*=fade
    bands=[dict(center_hz=float(fc[j]),floor_excess_db=float(sig[j]-caps[j])) for j in np.flatnonzero(eligible)]
    return dict(time=t,fc=fc,depth_db=depth,source_sha256=source_sha,atlas_sha256=atlas['sha256'],
        observer=oreport,bands=bands,status='CANDIDATE' if np.any(depth) else ('ABSTAIN_ROLE_OR_COVERAGE' if bands else 'NO_EVIDENCE'),
        scope='Persistent spectral excess candidate, not proof of resonance or unpleasantness')

def render(x,sr,p,strength=1.,cfg=Config()):
    cfg.validate();x=np.asarray(x,dtype=np.float64)
    if sr not in (32000,44100,48000,88200,96000) or x.ndim!=2 or x.shape[1]!=2 or not np.isfinite(x).all():raise ValueError('Invalid source')
    dep=np.asarray(p['depth_db']);t=np.asarray(p['time']);fc=np.asarray(p['fc'])
    if dep.shape!=(len(t),len(fc)) or not np.isfinite(dep).all() or dep.min()<0 or dep.max()>cfg.max_cut_db+1e-9 or np.any(np.diff(t)<=0):raise ValueError('Invalid plan')
    if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('Invalid strength')
    if strength==0 or not np.any(dep):return x.copy()
    # Analyze only the differential signal; original mix remains the direct path.
    # Finite-window spectral changes still require a time-domain check.
    n=round(cfg.frame_samples*sr/cfg.analysis_sr);n+=n%2;hop=max(1,round(.02*sr));w=signal.windows.hann(n,sym=False)
    if not signal.check_NOLA(w,n,n-hop):raise RuntimeError('Invalid overlap-add normalization')
    pad=n;u=np.pad(x,((pad,pad+n),(0,0)));delta=np.zeros_like(u);den=np.zeros(len(u))
    freq=np.fft.rfftfreq(n,1/sr);shape=np.maximum(1-np.abs(np.log2(np.maximum(freq[None,:],1)/fc[:,None]))/(1/6),0)
    for a in range(0,len(u)-n+1,hop):
        time=(a+n//2-pad)/sr
        depth=np.array([np.interp(time,t,dep[:,j],left=0,right=0) for j in range(len(fc))])*strength
        den[a:a+n]+=w*w
        if not np.any(depth):continue
        # max, not sum: adjacent bands cannot silently stack their budgets.
        cut=np.max(depth[:,None]*shape,axis=0)
        z=np.fft.rfft(u[a:a+n]*w[:,None],axis=0)
        d=np.fft.irfft(z*(10**(-cut[:,None]/20)-1),n=n,axis=0)*w[:,None]
        delta[a:a+n]+=d
    sl=slice(pad,pad+len(x))
    if np.any(den[sl]<1e-12):raise RuntimeError('Incomplete overlap-add coverage')
    d=delta[sl]/den[sl,None];d[np.all(x==0,axis=1)]=0
    y=x+d
    if not np.isfinite(y).all():raise RuntimeError('Nonfinite rendered result')
    return y
