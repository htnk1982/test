"""Explicit bridge from source-authorized relative tails to prepared audio.

The source event/evidence must already be supplied by a validated observation
layer. This adapter does not claim to discover a musical part or create labels.
A source deficit is only an upper permission: need is remeasured on the actual
HE/AUTO snapshot before any joint narrow proposal can be emitted.
"""
from dataclasses import asdict
from pathlib import Path
import math
import numpy as np
import soundfile as sf
import auto_peak_v34 as auto
import event_decay_v39 as decay
import spectral_persistence_lab as spectral
from integration_contract_v40 import Span,digest
from joint_lowend_v42 import NarrowCut

VERSION='physical-decay-bridge-lab-0.1.0'


def _features(path,identity,event,anchor_gain):
    sr=identity.samplerate;step=round(.02*sr)
    a=max(0,math.floor((event.start_seconds-.5)*sr/step)*step)
    b=min(identity.frames,math.ceil((event.end_seconds+.5)*sr/step)*step)
    with sf.SoundFile(path) as src:
        src.seek(a);x=src.read(b-a,dtype='float64',always_2d=True)
    if len(x)!=b-a or not np.isfinite(x).all():raise ValueError('Invalid local audio evidence')
    f=spectral.extract(x,sr,anchor_gain);f['time']=f['time']+a/sr
    return f


def _mapped_event(snapshot,event):
    sr=snapshot.source.samplerate;rr=snapshot.physical.samplerate
    def mapped(seconds):return snapshot.clock.nearest(round(seconds*sr))/rr
    return decay.Event(mapped(event.start_seconds),mapped(event.anchor_start_seconds),
        mapped(event.anchor_end_seconds),mapped(event.end_seconds),event.target_band,
        event.companion_bands,event.role,event.family).validate()


def confirm_relative_tail(context,event,atlas,source_support,*,allow_test_evidence=False,progress=None):
    """Return NarrowCut or None plus a provenance-complete assessment.

    Neither the source observation hash nor the physical waveform hash is
    substituted. The relationship is the verified RenderSnapshot. Unknown
    portions remain unknown; calibration gaps return abstention, not good audio.
    """
    snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path)
    event.validate();decay.validate_atlas(atlas)
    original=auto.measure(context.source_path,progress,'TAIL_SOURCE_MEASURE')
    physical=auto.measure(context.physical_path,progress,'TAIL_PHYSICAL_MEASURE')
    if original['lufs_i'] is None or physical['lufs_i'] is None:raise ValueError('Finite loudness required')
    source_f=_features(context.source_path,snapshot.source,event,-14-original['lufs_i'])
    p=decay.plan(source_f,event,atlas,snapshot.source.file_sha256,source_support,allow_test_evidence=allow_test_evidence)
    record=dict(version=VERSION,snapshot_sha256=snapshot.token,source_sha256=snapshot.source.file_sha256,
        physical_sha256=snapshot.physical.file_sha256,source_event=asdict(event),
        source_assessment=p['status'],atlas_sha256=atlas['sha256'],
        source_support_provider=None if source_support is None else source_support.get('provider'),
        source_observation_hash_substituted=False,subjective_quality='NOT_EVALUATED')
    if p['status']!='RELATIVE_TAIL_CANDIDATE':
        return None,dict(record,status=p['status'],physical_remeasurement_used=False)
    pe=_mapped_event(snapshot,event)
    ff=_features(context.physical_path,snapshot.physical,pe,-14-physical['lufs_i'])
    relation=decay.relation(ff,pe);pt=np.asarray(ff['time']);sr=snapshot.source.samplerate;rr=snapshot.physical.samplerate
    u=(pt-pe.start_seconds)/(pe.end_seconds-pe.start_seconds)
    cap=np.interp(u,atlas['phase'],atlas['cap_db'])
    needed=np.maximum(0.,relation['relative_decay_db']-cap)
    cfg=decay.Config()
    need_supported=(relation['companion_change_db']<=-cfg.companion_withdrawal_db)&(relation['peer_disagreement_db']<=cfg.maximum_peer_disagreement_db)
    if not relation['joint_onset_supported']:need_supported[:]=False
    physical_index=np.array([snapshot.clock.nearest(round(float(t)*sr)) for t in p['time']])/rr
    actual_need=np.interp(physical_index,pt,needed*need_supported,left=0,right=0)
    source_depth=np.asarray(p['depth_db'])[:,event.target_band]
    permitted=np.minimum(source_depth,actual_need)
    permitted[actual_need<cfg.minimum_excess_db]=0
    peak=float(permitted.max())
    if peak<1e-8:
        snapshot.verify(context.source_path,context.physical_path)
        return None,dict(record,status='KEEP_PHYSICAL_RELATIVE_NEED_CLEARED',physical_remeasurement_used=True,
            max_source_requested_db=float(source_depth.max()),max_confirmed_db=0.)
    # Keep the source clock as the authority; physical time is mapped only once
    # by the coordinator. Include exact protected-tail and event-end zeros.
    start=round((event.anchor_end_seconds+cfg.post_anchor_guard_seconds)*sr)
    end=round(event.end_seconds*sr);nodes={start:0.,end:0.}
    for t,d in zip(p['time'],permitted):
        frame=round(float(t)*sr)
        if start<frame<end:nodes[frame]=float(d)
    xs=tuple(sorted(nodes));ys=tuple(nodes[k] for k in xs)
    record.update(status='PHYSICALLY_CONFIRMED_TAIL_CANDIDATE',physical_remeasurement_used=True,
        max_source_requested_db=float(source_depth.max()),max_confirmed_db=peak,
        planned_source_interval=[start,end],mapped_event=asdict(pe),
        physical_metric='RELATIVE_COMPONENT_DECAY_NOT_TASTE_SCORE')
    evidence=digest(record)
    cut=NarrowCut('tail_'+evidence[:24],float(ff['fc'][event.target_band]),xs,ys,
        'SOURCE_AUTHORIZED_AND_PHYSICAL_RELATIVE_TAIL_EXCESS',evidence,snapshot.physical.file_sha256)
    cut.validate(snapshot);snapshot.verify(context.source_path,context.physical_path)
    return cut,record


class JointPlanner:
    """Compose an existing source-driven broad planner and a tail provider.

    Provider must return (NarrowCut list, unresolved reason list, detail). Its
    semantic acceptance is separate from this interface. No default empty tail
    provider masks a missing capability. New synthesis is not supported here.
    """
    def __init__(self,broad_planner,tail_provider):
        self.broad=broad_planner;self.tail=tail_provider;self.last_report=None
    def identity(self):
        from integration_contract_v40 import file_hash
        a=self.broad.identity();b=self.tail.identity()
        if a['evidence_scope']!=b['evidence_scope']:raise ValueError('Mixed provider evidence scopes')
        return dict(planner_id='joint-planner42',calibration_sha256=digest(dict(broad=a,tail=b)),
            evidence_scope=a['evidence_scope'],providers=dict(broad=a,tail=b),
            adapter_sha256=file_hash(__file__))
    def preflight(self):
        self.identity();self.broad.preflight();self.tail.preflight()
    def build(self,context,progress=None):
        from joint_lowend_v42 import compile_plan
        self.preflight();pid=self.identity();bp=self.broad.build(context,progress)
        cuts,unresolved,detail=self.tail.build(context,progress)
        changed=bool(cuts) or bool(np.any(bp['low_cut_db']) or np.any(bp['lowmid_cut_db']))
        if changed:assessment='PARTIAL' if unresolved or bp['assessment'] in ('ABSTAIN','PARTIAL') else 'CANDIDATE'
        else:assessment='ABSTAIN' if unresolved or bp['assessment']=='ABSTAIN' else 'KEEP_SUPPORTED'
        p=compile_plan(context.snapshot,bp,cuts,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],
            assessment=assessment,evidence_scope=pid['evidence_scope'],unresolved=unresolved)
        self.last_report=dict(broad=self.broad.last_report if hasattr(self.broad,'last_report') else None,tail=detail,
            narrow_operations=len(cuts),assessment=assessment,sub_synthesis='NOT_CONNECTED')
        if pid!=self.identity():raise RuntimeError('Provider identity changed')
        return p
