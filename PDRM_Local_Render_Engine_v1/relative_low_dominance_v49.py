"""Relative low-vs-mid dominance boundary for broad low-end actuation.

Absolute low level after whole-track loudness anchoring can invert intuition: a
low-heavy song may normalize downward while a sparse event normalizes upward.
This boundary therefore measures low/mid balance, where the common gain cancels.
Positive references set a permissive envelope; long sustain alone is not a flaw.
"""
from __future__ import annotations
from dataclasses import asdict
import json,math
import numpy as np
from scipy import signal
import auto_peak_v34 as auto
import source_events_v41 as events
from integration_contract_v40 import capture,digest,valid_hash

VERSION='relative-low-dominance-lab-0.1.0'
MIN_EXCESS_DB=.75
MAX_CUT_DB=2.0
MARGIN_DB=.75


def _signature(f):
    p=np.asarray(f['present'],bool);ratio=np.asarray(f['low_db'])-np.asarray(f['mid_db'])
    valid=p&np.isfinite(ratio)&(np.asarray(f['low_db'])>-65)&(np.asarray(f['mid_db'])>-65)
    if np.count_nonzero(valid)<25:raise ValueError('Insufficient low/mid reference support')
    return dict(q50_db=float(np.percentile(ratio[valid],50)),q90_db=float(np.percentile(ratio[valid],90)),q97_db=float(np.percentile(ratio[valid],97)))


def calibrate(reference_specs,progress=None):
    if len(reference_specs)<4:raise ValueError('At least four positive references required')
    ids=[];pcms=[];rows=[]
    for spec in reference_specs:
        if spec.get('role')!='bass' or spec.get('quality')!='positive':raise ValueError('Only bass-positive references allowed')
        ident=capture(spec['path'])
        if ident.file_sha256 in ids or ident.pcm_sha256 in pcms:raise ValueError('References must be independent')
        m=auto.measure(spec['path'],progress,'RELATIVE_REFERENCE_MEASURE')
        if m['lufs_i'] is None:raise ValueError('Silent reference')
        f=events.extract_features(spec['path'],anchor_gain_db=-14-m['lufs_i'],progress=progress)
        rows.append(_signature(f));ids.append(ident.file_sha256);pcms.append(ident.pcm_sha256)
    atlas=dict(schema=1,version=VERSION,reference_ids=ids,pcm_groups=pcms,per_track=rows,
        cap_q90_db=max(r['q90_db'] for r in rows)+MARGIN_DB,cap_q97_db=max(r['q97_db'] for r in rows)+MARGIN_DB,
        margin_db=MARGIN_DB,minimum_excess_db=MIN_EXCESS_DB,max_cut_db=MAX_CUT_DB,
        scope='Positive-reference low/mid balance envelope; duration alone is not a defect')
    atlas['sha256']=digest(atlas);return atlas


def validate(atlas,reference_ids=None):
    p=dict(atlas);seal=p.pop('sha256',None)
    if seal!=digest(p) or atlas.get('schema')!=1 or atlas.get('version')!=VERSION:raise ValueError('Relative calibration seal/version mismatch')
    ids=atlas.get('reference_ids',[]);pcms=atlas.get('pcm_groups',[])
    if len(ids)<4 or len(ids)!=len(set(ids)) or len(pcms)!=len(ids) or len(set(pcms))!=len(pcms) or not all(valid_hash(x) for x in ids+pcms):raise ValueError('Invalid relative reference identities')
    if reference_ids is not None and ids!=list(reference_ids):raise ValueError('Relative reference groups differ from broad calibration')
    for k in ('cap_q90_db','cap_q97_db','margin_db','minimum_excess_db','max_cut_db'):
        if not isinstance(atlas.get(k),(int,float)) or isinstance(atlas.get(k),bool) or not math.isfinite(float(atlas[k])):raise ValueError('Invalid relative calibration '+k)
    return atlas


def analyze(f,atlas):
    validate(atlas);ratio=np.asarray(f['low_db'],float)-np.asarray(f['mid_db'],float);present=np.asarray(f['present'],bool)
    valid=present&np.isfinite(ratio)&(np.asarray(f['low_db'])>-65)&(np.asarray(f['mid_db'])>-65)
    cap=float(atlas['cap_q90_db']);excess=np.maximum(0.,ratio-cap);curve=np.clip(excess,0,float(atlas['max_cut_db']))
    curve[~valid]=0
    # Require a finite neighborhood, not isolated numerical spikes. This does not
    # penalize duration; it only stabilizes the control surface.
    n=9;w=signal.windows.hann(n);w/=w.sum();curve=np.convolve(np.pad(curve,(n//2,n//2),mode='edge'),w,mode='valid')
    if len(curve):
        guard=min(len(curve)//2,10)
        if guard:curve[:guard]*=np.linspace(0,1,guard);curve[-guard:]*=np.linspace(1,0,guard)
    q90=float(np.percentile(ratio[valid],90)) if np.any(valid) else -999.
    q97=float(np.percentile(ratio[valid],97)) if np.any(valid) else -999.
    return dict(time=np.asarray(f['time'],float),low_cut_db=curve,ratio_db=ratio,valid=valid,
        q90_db=q90,q97_db=q97,cap_q90_db=cap,cap_q97_db=float(atlas['cap_q97_db']),
        excess_q90_db=max(0.,q90-cap),candidate=bool(np.any(curve>=atlas['minimum_excess_db']*.25)),
        scope='Relative low/mid dominance; not bass-role evidence')


def score(f,atlas):
    q=_signature(f);return max(0.,q['q90_db']-float(atlas['cap_q90_db']))
