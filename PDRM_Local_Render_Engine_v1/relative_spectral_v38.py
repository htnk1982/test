"""Boundary38 LAB: relative spectral opportunities plus verified role observation.

Unlike v37's same-Hz absolute floor, compare each band's contribution to the
unchanged mixture, allowing +/- 1/3-octave reference neighbourhood. This is an
explicit nuisance tolerance, NOT inferred f0, semantic equivalence, or a claim
of perceptual correctness. The positive repertoire still informs development.

A reference exceedance proposes an operation; it does not prove an unpleasant
resonance. Whole-track screening intentionally targets recurrent persistence.
Short isolated defects need the separate event path and are not certified here.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from typing import Any
import numpy as np
from scipy import signal
from scipy.ndimage import uniform_filter1d, maximum_filter1d, distance_transform_edt
import spectral_persistence_lab as legacy

VERSION = 'relative-spectral-lab-0.1.0'
ROLE_ORDER = ['mix', 'drums', 'bass', 'other', 'vocals']

@dataclass(frozen=True)
class Config:
    reference_radius_bands: int = 2  # six bands/octave => +/- 1/3 octave
    reference_margin_db: float = .5
    minimum_excess_db: float = .75
    low_center_hz: float = 120.
    high_center_hz: float = 600.
    max_cut_db: float = 1.5
    persistence_seconds: float = .30
    smooth_seconds: float = .12
    source_presence_db: float = -45.
    observer_edge_guard_seconds: float = .4
    minimum_role_share: float = .55
    maximum_share_disagreement: float = .25
    minimum_role_power_fraction: float = .05

    def validate(self) -> Config:
        for k, v in asdict(self).items():
            if isinstance(v, bool) or not isinstance(v, (float,int)) or not math.isfinite(v):
                raise ValueError('Invalid finite config: '+k)
        if type(self.reference_radius_bands) is not int or not 0 <= self.reference_radius_bands <= 3:
            raise ValueError('Reference neighbourhood must be an integer count of bands')
        if not 0 <= self.reference_margin_db <= 3 or not .1 <= self.minimum_excess_db <= 3:
            raise ValueError('Invalid evidence margin')
        if not 80 <= self.low_center_hz < self.high_center_hz <= 650 or not 0 <= self.max_cut_db <= 1.5:
            raise ValueError('Invalid spectral budget')
        if not .2 <= self.persistence_seconds <= 2 or not .06 <= self.smooth_seconds <= .5:
            raise ValueError('Time constants are seconds')
        if not .35 <= self.observer_edge_guard_seconds <= 1 or not -80 <= self.source_presence_db <= -20:
            raise ValueError('Invalid silence/edge support')
        if not .5 <= self.minimum_role_share <= 1 or not 0 < self.maximum_share_disagreement <= .5:
            raise ValueError('Invalid observer agreement budget')
        if not 0 < self.minimum_role_power_fraction <= 1:
            raise ValueError('Invalid role energy support')
        return self

def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()

def validate_features(f: dict) -> None:
    legacy.validate_features(f)
    t=np.asarray(f['time']);fc=np.asarray(f['fc'])
    if not np.isfinite(t).all() or not np.isfinite(fc).all() or t[0] < 0:
        raise ValueError('Invalid feature clock/frequencies')

def signature(f: dict,cfg=Config()) -> np.ndarray:
    cfg.validate();validate_features(f)
    active=np.asarray(f['full_db'])>cfg.source_presence_db
    if np.count_nonzero(active)<25:
        raise ValueError('Insufficient context; not a healthy KEEP diagnosis')
    rel=np.asarray(f['db'])-np.asarray(f['full_db'])[:,None]
    return np.percentile(rel[active],20,axis=0)

def calibrate(features,reference_ids,cfg=Config()) -> dict:
    cfg.validate()
    if len(features)<4 or len(reference_ids)!=len(features) or len(set(reference_ids))!=len(reference_ids):
        raise ValueError('At least four unique reference groups required')
    sig=np.stack([signature(f,cfg) for f in features]);r=cfg.reference_radius_bands
    cap=np.array([sig[:,max(0,j-r):min(sig.shape[1],j+r+1)].max()+cfg.reference_margin_db for j in range(sig.shape[1])])
    out=dict(schema=1,version=VERSION,config=asdict(cfg),caps_db=cap.tolist(),fc=legacy.centers().tolist(),
             reference_ids=list(reference_ids),reference_signatures_db=sig.tolist(),
             reference_scope='Positive bass-review mixture contexts; not stem-clean timbre exemplars',
             scope='Empirical relative persistence boundary; neither source probability nor taste certification')
    out['sha256']=digest(out)
    return out

def validate_atlas(atlas,cfg=Config()):
    cfg.validate();a=dict(atlas);h=a.pop('sha256',None)
    if digest(a)!=h or atlas.get('version')!=VERSION or atlas.get('schema')!=1 or atlas.get('config')!=asdict(cfg):
        raise ValueError('Atlas identity/config mismatch')
    c=np.asarray(atlas.get('caps_db'),dtype=float)
    if c.shape!=(20,) or not np.isfinite(c).all() or not np.allclose(atlas['fc'],legacy.centers(),rtol=0,atol=1e-9):
        raise ValueError('Invalid reference bounds')

def screen(f,atlas,cfg=Config()) -> dict:
    validate_atlas(atlas,cfg);s=signature(f,cfg);fc=np.asarray(f['fc'])
    excess=s-np.asarray(atlas['caps_db'])
    eligible=(excess>=cfg.minimum_excess_db)&(fc>=cfg.low_center_hz)&(fc<=cfg.high_center_hz)
    return dict(eligible=eligible,excess_db=excess,signature_db=s,
                status='RELATIVE_EXCESS_CANDIDATE' if eligible.any() else 'NO_RELATIVE_EXCESS',
                healthy_audio_claim=False)

def observer_evidence(arrays,meta,source_sha256,cfg=Config()):
    """Validate every supplied observation even when the audio screen is a no-op."""
    cfg.validate()
    if meta.get('version')!='role-observer-0.3.0' or meta.get('source_order')!=ROLE_ORDER:
        raise ValueError('Observer schema/order mismatch')
    if not isinstance(source_sha256,str) or meta.get('source_sha256')!=source_sha256:
        raise ValueError('Wrong source observer')
    from stem_observer_lab import CHECKPOINT_SHA256
    if meta.get('model_sha256')!=CHECKPOINT_SHA256:
        raise ValueError('Unknown research observer checkpoint')
    t=np.asarray(arrays['band_time'],dtype=float);fc=np.asarray(arrays['fc'],dtype=float)
    p=np.asarray(arrays['band_power'],dtype=float)
    if p.shape!=(2,len(t),5,20) or len(t)<25 or not np.isfinite(p).all() or np.any(p<0):
        raise ValueError('Invalid spectral observer powers')
    if not np.isfinite(t).all() or not np.allclose(np.diff(t),.02,rtol=0,atol=1e-8):
        raise ValueError('Observer clock must be seconds, 20ms grid')
    if not np.allclose(fc,legacy.centers(),rtol=0,atol=1e-8):
        raise ValueError('Observer band mismatch')
    start,end=meta.get('start_seconds'),meta.get('end_seconds')
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (start,end)) or not 0<=start<end:
        raise ValueError('Invalid observer interval')
    if abs(t[0]-start)>.021 or abs((t[-1]+.02)-end)>.021:
        raise ValueError('Observer interval and clock disagree')
    powers=p[:,:,1:,:]
    shares=powers/np.maximum(powers.sum(axis=2,keepdims=True),1e-24)
    winners=shares.argmax(axis=2)  # [pass,time,band]
    agree=winners[0]==winners[1]
    dist=np.sum(abs(shares[0]-shares[1]),axis=1)/2
    reliable=agree&(shares.max(axis=2).min(axis=0)>=cfg.minimum_role_share)&(dist<=cfg.maximum_share_disagreement)
    strongest=np.max(powers,axis=2).min(axis=0)
    mix=p[:,:,0,:].min(axis=0)
    reliable&=(mix>1e-12)&(strongest>=cfg.minimum_role_power_fraction*mix)
    reliable&=(t[:,None]>=start+cfg.observer_edge_guard_seconds)&(t[:,None]<=end-cfg.observer_edge_guard_seconds)
    return dict(time=t,winner=winners[0],reliable=reliable,shares=shares,disagreement=dist,
                probability_claim=False)

def plan(f,atlas,source_sha256,observer=None,cfg=Config()) -> dict:
    cfg.validate();s=screen(f,atlas,cfg)
    t=np.asarray(f['time']);fc=np.asarray(f['fc']);rel=np.asarray(f['db'])-np.asarray(f['full_db'])[:,None]
    permission=np.zeros_like(rel,dtype=bool);role_counts={}
    evidence=None
    if observer is not None:
        evidence=observer_evidence(*observer,source_sha256,cfg)
        for j in range(len(fc)):
            permitted=evidence['reliable'][:,j]&(evidence['winner'][:,j]!=3)
            permission[:,j]=np.interp(t,evidence['time'],permitted.astype(float),left=0,right=0)>.999
            role_counts[str(j)]={role:int(np.count_nonzero(evidence['reliable'][:,j]&(evidence['winner'][:,j]==i))) for i,role in enumerate(ROLE_ORDER[1:])}
    cap=np.asarray(atlas['caps_db']);active=np.asarray(f['full_db'])>cfg.source_presence_db
    excessive=(rel>cap[None,:]+cfg.minimum_excess_db)&active[:,None]
    count=max(1,round(cfg.persistence_seconds/.02))
    persistent=uniform_filter1d(excessive.astype(float),count,axis=0,mode='nearest')>=.85
    full=np.asarray(f['full_db']);rise=full-np.r_[np.repeat(full[0],3),full[:-3]]
    protected=maximum_filter1d((rise>3).astype(float),size=13,mode='nearest')>0
    support=permission&active[:,None]&~protected[:,None]
    raw=np.minimum(cfg.max_cut_db,np.maximum(0.,rel-cap[None,:]))
    raw*=persistent&support&s['eligible'][None,:]
    n=max(3,round(cfg.smooth_seconds/.02)|1);w=signal.windows.hann(n,sym=True);w/=w.sum()
    depth=np.stack([np.convolve(np.pad(raw[:,j],(n//2,n//2),mode='edge'),w,mode='valid') for j in range(len(fc))],axis=1)
    fade=np.stack([np.clip(distance_transform_edt(support[:,j])*.02/.12,0,1) for j in range(len(fc))],axis=1)
    depth*=fade
    if not s['eligible'].any():state='KEEP_NO_RELATIVE_EXCESS'
    elif not permission[:,s['eligible']].any():state='ABSTAIN_OBSERVER_OR_VOCAL'
    elif not depth.any():state='KEEP_NO_SUPPORTED_PERSISTENCE'
    else:state='SPECTRAL_CANDIDATE'
    bands=[dict(center_hz=float(fc[j]),relative_floor_excess_db=float(s['excess_db'][j])) for j in np.flatnonzero(s['eligible'])]
    return dict(time=t,fc=fc,depth_db=depth,source_sha256=source_sha256,atlas_sha256=atlas['sha256'],
                config=asdict(cfg),status=state,bands=bands,role_counts=role_counts,
                screen_status=s['status'],observer_used=evidence is not None,
                healthy_audio_claim=False,quantity_calibration='LAB_MAX_1_5DB_NOT_TASTE_APPROVED')

def render(x,sr,p,strength=1.,cfg=Config()):
    cfg.validate()
    if p.get('config')!=asdict(cfg):raise ValueError('Plan config mismatch')
    # The former differential renderer is reused without changing its DSP.
    return legacy.render(x,sr,p,strength,legacy.Config(max_cut_db=cfg.max_cut_db))

def render_verified(source,p,strength=1.,cfg=Config()):
    """Read one immutable source, check plan/source identity and return samples."""
    from pathlib import Path
    import soundfile as sf
    from stem_observer_lab import sha
    source=Path(source);before=sha(source)
    if before!=p.get('source_sha256'):raise ValueError('Plan belongs to another source')
    x,sr=sf.read(source,dtype='float64',always_2d=True)
    if not np.isfinite(x).all() or x.ndim!=2 or x.shape[1]!=2:raise ValueError('Invalid source')
    y=render(x,sr,p,strength,cfg)
    if sha(source)!=before:raise RuntimeError('Source changed during render')
    return y,sr
