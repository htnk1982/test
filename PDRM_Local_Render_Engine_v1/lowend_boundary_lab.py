"""Reference-boundary low-end LAB. Not a production mastering certification.

The DSP changes the original stereo mix, never estimated stems. No new pitches
are synthesized by this module. The positive-reference envelope is empirical;
NO_EVIDENCE is not a claim that an arbitrary input is musically good.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib, json, math
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy import signal
from scipy.ndimage import uniform_filter1d, minimum_filter1d, maximum_filter1d

VERSION = 'lowend-boundary-lab-0.1.1'
EPS = 1e-24
@dataclass(frozen=True)
class Config:
    analysis_sr: int = 12000
    grid_seconds: float = .01
    normalization_lufs: float = -14.
    envelope_seconds: float = .06
    phrase_seconds: float = 12.
    minimum_excess_db: float = .5
    reference_margin_db: float = .5
    max_hit_cut_db: float = 2.0
    max_tail_cut_db: float = 2.0
    max_lowmid_cut_db: float = 1.5
    join_seconds: float = .08
    filter_seconds: float = .12
    def validate(self):
        for k,v in asdict(self).items():
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
                raise ValueError('Invalid finite configuration: '+k)
        if self.analysis_sr != 12000 or self.grid_seconds != .01:
            raise ValueError('Calibration uses 12 kHz / 10 ms grid')
        if not 0 < self.minimum_excess_db <= 3 or not 0 <= self.reference_margin_db <= 3:
            raise ValueError('Invalid boundary margin')
        if not 0 <= self.max_hit_cut_db <= 3 or not 0 <= self.max_tail_cut_db <= 3 or not 0 <= self.max_lowmid_cut_db <= 2:
            raise ValueError('Invalid intervention budget')
        if not .02 <= self.join_seconds <= .3 or not .08 <= self.filter_seconds <= .3:
            raise ValueError('Invalid smoothing')
        if not 4 <= self.phrase_seconds <= 30 or not .02 <= self.envelope_seconds <= .2:
            raise ValueError('Invalid context')
        return self

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''): h.update(b)
    return h.hexdigest()

def db(power):return 10*np.log10(np.maximum(power,EPS))

def validate_audio(x,sr):
    x=np.asarray(x,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=2 or len(x)<max(32,round(sr*.5)):
        raise ValueError('Finite stereo audio of at least 0.5 s required')
    if sr not in (32000,44100,48000,88200,96000):raise ValueError('Unsupported rate')
    if not np.all(np.isfinite(x)):raise ValueError('Non-finite audio')
    return x

def extract(x,sr,cfg=Config()):
    cfg.validate();x=validate_audio(x,sr)
    lufs=float(pyln.Meter(sr).integrated_loudness(x))
    if not math.isfinite(lufs):raise ValueError('Silent audio: no finite reference loudness')
    factor=cfg.normalization_lufs-lufs
    g=math.gcd(sr,cfg.analysis_sr)
    y=signal.resample_poly(x,cfg.analysis_sr//g,sr//g,axis=0,window=('kaiser',10.5))
    step=round(cfg.analysis_sr*cfg.grid_seconds);w=round(cfg.analysis_sr*cfg.envelope_seconds)
    def envelope(z):
        return np.maximum(uniform_filter1d(np.mean(z*z,axis=1),w,mode='nearest')[::step],EPS)
    out={'time':np.arange(0,len(y),step)/cfg.analysis_sr,'lufs':lufs,'gain_to_anchor_db':factor,
         'full_db':db(envelope(y))+factor}
    for k,lo,hi in [('low',20,120),('lowmid',120,300),('mid',250,2000),('deep',30,65)]:
        z=signal.sosfiltfilt(signal.butter(4,[lo,hi],btype='bandpass',fs=cfg.analysis_sr,output='sos'),y,axis=0)
        out[k+'_db']=db(envelope(z))+factor
    # Stereo powers, NOT mono summation. Antiphase energy must not disappear.
    out['present']=out['full_db']>-45
    out['low_active']=out['present'] & (out['low_db']>-50)
    out['configuration']=asdict(cfg)
    return out

def signature(f,cfg=Config()):
    p=np.asarray(f['present'],bool);low=np.asarray(f['low_db']);lm=np.asarray(f['lowmid_db'])
    if np.count_nonzero(p)<25:raise ValueError('Insufficient audible context')
    # Three independent defects; the sustained floor is not punished by itself.
    return dict(hit_q90_db=float(np.percentile(low[p],90)),
                low_floor_q20_db=float(np.percentile(low[p],20)),
                low_contrast_db=float(np.percentile(low[p],90)-np.percentile(low[p],20)),
                lowmid_floor_q20_db=float(np.percentile(lm[p],20)))

def calibrate(positive_features, source_ids, cfg=Config()):
    """Fit upper limits from role-explicit positive examples only.

    This is a small empirical reference envelope, not a trained perceptual model.
    Negative files and filenames never enter the decision function.
    """
    cfg.validate()
    if len(positive_features)<4 or len(source_ids)!=len(positive_features) or len(set(source_ids))!=len(source_ids):
        raise ValueError('At least four independent positive tracks required')
    sig=[signature(f,cfg) for f in positive_features]
    for f in positive_features:
        if f.get('configuration')!=asdict(cfg):raise ValueError('Feature/config mismatch')
    caps={k:max(s[k] for s in sig)+cfg.reference_margin_db for k in sig[0] if k!='low_contrast_db'}
    caps['low_contrast_min_db']=min(s['low_contrast_db'] for s in sig)-cfg.reference_margin_db
    caps['low_hit_supported_min_db']=min(s['hit_q90_db'] for s in sig)-3.0
    return dict(schema=1,version=VERSION,config=asdict(cfg),caps=caps,
                reference_ids=list(source_ids),reference_signatures=sig,
                scope='Empirical positive-reference envelope; uncalibrated outside supplied repertoire')

def _smooth_bounded(curve,dt,seconds):
    n=max(3,round(seconds/dt)|1);w=signal.windows.hann(n,sym=True);w/=w.sum()
    return np.convolve(np.pad(curve,(n//2,n//2),mode='edge'),w,mode='valid')

def plan(f,atlas,cfg=Config()):
    cfg.validate()
    if atlas.get('schema')!=1 or atlas.get('version')!=VERSION or atlas.get('config')!=asdict(cfg) or f.get('configuration')!=asdict(cfg):
        raise ValueError('Calibration identity/config mismatch')
    if not all(math.isfinite(v) for v in atlas['caps'].values()):raise ValueError('Invalid calibration caps')
    sig=signature(f,cfg);n=len(f['time']);dt=cfg.grid_seconds
    low=np.asarray(f['low_db']);lm=np.asarray(f['lowmid_db']);present=np.asarray(f['present'],bool)
    h=np.zeros(n);tail=np.zeros(n);body=np.zeros(n);caps=atlas['caps'];reasons=[]
    # Whole-track evidence gates local actuation, preventing ordinary per-note
    # variation from being labelled a defect solely by a large isolated peak.
    ex=sig['hit_q90_db']-caps['hit_q90_db']
    if ex>=cfg.minimum_excess_db:
        # Same curve attenuates body of overlarge hits; no beat-grid quantization.
        raw=np.clip(low-caps['hit_q90_db'],0,cfg.max_hit_cut_db)
        # Broaden only supported event body; taper according to its energy.
        h=raw*np.clip((low-(caps['hit_q90_db']-6))/6,0,1)
        reasons.append('EXCESS_HIT_LEVEL')
    low_ex=sig['low_floor_q20_db']-caps['low_floor_q20_db']
    contrast_deficit=caps['low_contrast_min_db']-sig['low_contrast_db']
    supported=sig['hit_q90_db']>=caps['low_hit_supported_min_db']
    deferred=[]
    if low_ex>=cfg.minimum_excess_db and contrast_deficit>=cfg.minimum_excess_db and supported:
        rise=low-np.r_[np.repeat(low[0],4),low[:-4]]
        attack=maximum_filter1d((rise>2).astype(float),size=21,mode='nearest')>0
        # Only tail/body above reference floor. Strong moving attacks are spared.
        tail=np.clip(low_ex,0,cfg.max_tail_cut_db)*np.clip((low-caps['low_floor_q20_db'])/8,0,1)
        tail[attack]=0
        reasons.append('EXCESS_LOW_FLOOR')
    mid_ex=sig['lowmid_floor_q20_db']-caps['lowmid_floor_q20_db']
    if low_ex>=cfg.minimum_excess_db and not supported:
        deferred.append('LOW_FLOOR_OUTSIDE_REFERENCE_SUPPORT')
    if mid_ex>=cfg.minimum_excess_db:
        deferred.append('LOWMID_FLOOR_REQUIRES_ROLE_ATTRIBUTION')
    for curve in (h,tail,body):curve[~present]=0
    lo=_smooth_bounded(np.maximum(h,tail),dt,cfg.join_seconds)
    bo=_smooth_bounded(body,dt,cfg.join_seconds)
    # A finite fade at file edges; preserve digital silence during rendering.
    guard=min(n//2,max(1,round(.10/dt)));ramp=np.linspace(0,1,guard)
    for v in (lo,bo):v[:guard]*=ramp;v[-guard:]*=ramp[::-1]
    return dict(time=np.asarray(f['time']),low_cut_db=lo,lowmid_cut_db=bo,
                reason_codes=reasons,deferred_reason_codes=deferred,
                status='CANDIDATE' if reasons else ('ABSTAIN_ROLE_OR_DOMAIN' if deferred else 'NO_EVIDENCE'),
                input_signature=sig,caps=caps,scope='Not a semantic diagnosis; no new bass synthesis')

def render_array(x,sr,p,cfg=Config(),strength=1.):
    """Dry plus bounded stereo-linked differential bands. No stem replacement."""
    cfg.validate();x=validate_audio(x,sr)
    if not math.isfinite(strength) or not 0<=strength<=1:raise ValueError('Invalid strength')
    t=np.asarray(p['time'],float);lo=np.asarray(p['low_cut_db'],float);lm=np.asarray(p['lowmid_cut_db'],float)
    if len(t)<2 or lo.shape!=t.shape or lm.shape!=t.shape or np.any(np.diff(t)<=0):raise ValueError('Invalid control timeline')
    if not all(np.all(np.isfinite(v)) for v in (t,lo,lm)):raise ValueError('Invalid control data')
    if np.any(lo<0) or np.any(lm<0) or np.max(lo)>max(cfg.max_hit_cut_db,cfg.max_tail_cut_db)+1e-10 or np.max(lm)>cfg.max_lowmid_cut_db+1e-10:
        raise ValueError('Out-of-budget control')
    if strength==0 or not (np.any(lo) or np.any(lm)):return x.copy()
    taps=max(1025,round(cfg.filter_seconds*sr)|1)
    a=signal.firwin(taps,140,fs=sr,window=('kaiser',10.5))
    b=signal.firwin(taps,350,fs=sr,window=('kaiser',10.5))
    # Exactly complementary at equal branch gains, apart from bounded floating
    # roundoff; high band is kept on the original dry path.
    low=signal.oaconvolve(x,a[:,None],mode='same',axes=0)
    lm_band=signal.oaconvolve(x,(b-a)[:,None],mode='same',axes=0)
    samples=np.arange(len(x))/sr
    g0=10**(-strength*np.interp(samples,t,lo)/20)
    g1=10**(-strength*np.interp(samples,t,lm)/20)
    delta=(g0-1)[:,None]*low+(g1-1)[:,None]*lm_band
    delta[np.all(x==0,axis=1)]=0
    y=x+delta
    if not np.all(np.isfinite(y)):raise RuntimeError('Non-finite output')
    return y

def authorize_fundamental(*,f0_hz,target_hz,source_event,source_harmonics,
                          observer_role,observer_reliable,need,source_rest):
    """Explicit prerequisite gate; not a probability model or synthesizer."""
    if not all(math.isfinite(v) and v>0 for v in (f0_hz,target_hz)):
        raise ValueError('Invalid pitch')
    if source_rest:return 'DENY_SOURCE_REST'
    if abs(1200*math.log2(f0_hz/target_hz))>50:return 'DENY_NEW_OCTAVE'
    if not source_event or not source_harmonics:return 'DENY_NO_SOURCE_EVIDENCE'
    if observer_role!='bass' or not observer_reliable:return 'ABSTAIN_OBSERVER'
    if not need:return 'KEEP_ALREADY_SUFFICIENT'
    return 'ALLOW_SAME_FUNDAMENTAL_CANDIDATE'

def evaluate_change(x,y,sr):
    """Physical checks, not a listening score."""
    x=validate_audio(x,sr);y=validate_audio(y,sr)
    if x.shape!=y.shape:raise ValueError('Shape changed')
    d=y-x
    def rms(z):return float(np.sqrt(np.mean(z*z)))
    high=signal.sosfilt(signal.butter(6,1000,fs=sr,btype='highpass',output='sos'),d,axis=0)
    return dict(residual_db=20*math.log10(max(rms(d),1e-15)/max(rms(x),1e-15)),
      residual_above1k_db=20*math.log10(max(rms(high),1e-15)/max(rms(x),1e-15)),
      source_silence_preserved=bool(np.all(y[np.all(x==0,axis=1)]==0)),
      finite=bool(np.isfinite(y).all()),frames=len(y),
      subjective_quality='NOT_EVALUATED')

def select_strength(x,sr,p,atlas,cfg=Config()):
    """Choose smallest rendered candidate meeting its empirical correction goal.

    Never reward cuts merely because their peak is lower. Unaddressed phenomena
    remain unresolved. A failure to meet the goal at the budget is explicit.
    """
    keys={'EXCESS_HIT_LEVEL':'hit_q90_db','EXCESS_LOW_FLOOR':'low_floor_q20_db',
          'EXCESS_LOWMID_FLOOR':'lowmid_floor_q20_db'}
    goals=[keys[k] for k in p['reason_codes']]
    if not goals:
        return x.copy(),dict(status=p['status'],strength=0.,trials=[],subjective_quality='NOT_EVALUATED')
    base=p['input_signature'];base_error=sum(max(0.,base[k]-atlas['caps'][k]) for k in goals)
    trials=[];best=None
    for strength in (.25,.5,.75,1.):
        y=render_array(x,sr,p,cfg,strength)
        measured=signature(extract(y,sr,cfg),cfg)
        q=evaluate_change(x,y,sr)
        error=sum(max(0.,measured[k]-atlas['caps'][k]) for k in goals)
        numerical_target_met=all(measured[k]<=atlas['caps'][k]+.25 for k in goals)
        # Numerical guard excludes meaningful corruption above intervention band.
        valid=q['finite'] and q['source_silence_preserved'] and q['residual_above1k_db']<=-60 and error<base_error-.05
        trial=dict(strength=strength,signature=measured,target_error_db=error,
                   numerical_target_met=numerical_target_met,physical_checks=valid,**q)
        trials.append(trial)
        if valid and (best is None or error<best[0]):best=(error,y,strength)
        if valid and numerical_target_met:
            return y,dict(status='NUMERICAL_TARGET_MET',strength=strength,trials=trials,subjective_quality='NOT_EVALUATED')
    if best is not None:
        return best[1],dict(status='PARTIAL_BUDGET_LIMITED',strength=best[2],trials=trials,subjective_quality='NOT_EVALUATED')
    return x.copy(),dict(status='ABSTAIN_NO_VALID_IMPROVEMENT',strength=0.,trials=trials,subjective_quality='NOT_EVALUATED')
