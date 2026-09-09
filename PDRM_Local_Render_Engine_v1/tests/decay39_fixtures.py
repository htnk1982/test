"""Explicit synthetic evidence. Never represented as neural inference or music labels."""
from __future__ import annotations
from dataclasses import asdict
import copy
import hashlib
import numpy as np
import event_decay_v39 as ed
import spectral_persistence_lab as sp


def event(target=12, role='bass', family='octave-related-1-2-4'):
    return ed.Event(.60, .80, .98, 3.40, target, (target-6, target+6), role, family)


def features(level_shift=0., target_color=0., slope=-6., fault_db=0., role='bass'):
    t=np.arange(200)*.02; n=len(t);d=np.full((n,20),-70.)
    e=event(role=role);u=np.maximum(t-e.start_seconds,0)
    for j,level in ((6,-25.),(12,-24.+target_color),(18,-30.)):
        d[:,j]=np.where((t>=.6)&(t<3.4),level+slope*u,-90.)
    if fault_db:
        phase=np.clip((t-1.40)/.30,0,1);phase=phase*phase*(3-2*phase)
        d[:,12]+=fault_db*phase*(t<3.4)
    return dict(time=t,fc=sp.centers(),db=d+level_shift,full_db=np.where((t>=.6)&(t<3.4),-20.,-60.)+level_shift)


def local_label(e):
    return dict(quality='positive',role=e.role,phenomenon=ed.PHENOMENON,
        time_range_seconds=[e.start_seconds,e.end_seconds])


def atlas():
    e=event()
    rows=[dict(group_id=f'synthetic-source-{i}',features=features(target_color=i*.7,slope=-5-i),event=e,label=local_label(e)) for i in range(4)]
    return ed.calibrate(rows)


def oracle(t,e,sha='0'*64):
    return dict(provider='synthetic_oracle',source_sha256=sha,event_key=e.key(),time=np.array(t,copy=True),supported=np.ones(len(t),dtype=bool))


def audio_fixture(sr=32000,phase=.2,decay=.8,color_db=0.,fault_db=0.,target=12,legato=False):
    """Original plus a tail-only level defect of one known component.

    Clean ground truth is used only by the benchmark evaluator. The processor
    receives the altered mixture, the event hypothesis, and explicit test oracle.
    """
    t=np.arange(round(4*sr))/sr;e=event(target=target);u=t-e.start_seconds
    attack=np.clip(u/.08,0,1);attack=np.sin(np.pi*attack/2)**2
    release=np.clip((e.end_seconds-t)/.16,0,1);release=release**2*(3-2*release)
    common=attack*release*np.exp(-decay*np.maximum(u-.08,0))
    common[(u<0)|(t>=e.end_seconds)]=0
    if legato:
        common=attack*release;common[(u<0)|(t>=e.end_seconds)]=0
    fc=sp.centers();target_wave=.070*10**(color_db/20)*common*np.cos(2*np.pi*fc[target]*t+phase)
    peers=.055*common*np.cos(2*np.pi*fc[target-6]*t+.1+phase)+.035*common*np.cos(2*np.pi*fc[target+6]*t-.2+phase)
    # A separate HF component checks that only the selected low-mid event changes.
    high=.005*np.sin(2*np.pi*2300*t)*np.sin(np.pi*np.clip(t/4,0,1))**2
    clean=np.column_stack((target_wave+peers+high,.93*target_wave+.96*peers-high))
    q=np.clip((t-1.45)/.35,0,1);q=q*q*(3-2*q)
    extra=target_wave*(10**(fault_db*q/20)-1)
    bad=clean+np.column_stack((extra,.93*extra))
    return clean,bad,e


def audio_atlas(sr=32000):
    examples=[]
    for i,(p,d,c) in enumerate(((.1,.70,-1.),(.8,.78,0.),(1.6,.86,1.),(2.2,.94,.4))):
        clean,_,e=audio_fixture(sr,phase=p,decay=d,color_db=c)
        f=sp.extract(clean,sr,0)
        examples.append(dict(group_id=f'calibration-synthetic-{i}',features=f,event=e,label=local_label(e)))
    return ed.calibrate(examples)
