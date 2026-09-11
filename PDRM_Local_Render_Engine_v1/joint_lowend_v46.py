"""Joint broad/narrow reduction plus same-fundamental addition LAB.

Reduction rendering is delegated to joint_lowend_v42. Additions are generated
from compact controls previously confirmed on the SAME prepared 2mix. A plan
that asks to cut the low band while adding sub in the same supported interval is
rejected instead of allowing processors to fight. No stem samples enter output.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json,math,os,tempfile
import numpy as np
import soundfile as sf
import joint_lowend_v42 as base
from physical_add_bridge_v46 import SameFundamentalAdd
from integration_contract_v40 import capture,digest,integer,valid_hash

VERSION='joint-lowend-lab-0.2.1'
MAX_ACTIVE_ADDS=1
CONFLICT_DB=.02


def compile_plan(snapshot,reduction_plan,additions,*,planner_id,calibration_sha256,evidence_scope,assessment,unresolved=()):
    snapshot.validate();base.validate_plan(reduction_plan,snapshot)
    if not isinstance(planner_id,str) or not planner_id or not valid_hash(calibration_sha256):raise ValueError('Planner/calibration identity required')
    if evidence_scope not in ('engineering_fixture','research_observer') or reduction_plan['evidence_scope']!=evidence_scope:raise ValueError('Evidence scope mismatch')
    if assessment not in ('CANDIDATE','PARTIAL','KEEP_SUPPORTED','ABSTAIN'):raise ValueError('Invalid assessment')
    adds=sorted(tuple(additions),key=lambda p:p.proposal_id)
    if len({a.proposal_id for a in adds})!=len(adds):raise ValueError('Duplicate addition ID')
    for a in adds:a.validate(snapshot)
    # Bass/sub additions are currently monophonic by design. Overlapping events
    # must be resolved by the musical planner rather than silently summed.
    intervals=[]
    for add in adds:
        start=snapshot.clock.nearest(add.source_frames[0]);stop=snapshot.clock.nearest(add.source_frames[-1]);intervals.append((start,stop,add))
    intervals=sorted(intervals,key=lambda row:(row[0],row[1],row[2].proposal_id))
    for (a,b,_),(c,d,_) in zip(intervals,intervals[1:]):
        if c<b:raise ValueError('Overlapping same-fundamental additions require planner resolution')
    # Explicit no-fight rule: broad low-band attenuation and sub addition cannot
    # coexist during positive addition support. Narrow cuts start >=120 Hz.
    bt=np.asarray(reduction_plan['broad_plan']['physical_frames'],float);bd=np.asarray(reduction_plan['broad_plan']['low_cut_db'],float)
    for add in adds:
        frames=np.array([snapshot.clock.nearest(v) for v in add.source_frames],float);env=np.asarray(add.envelope)
        query=frames[env>1e-6]
        if len(query) and np.max(np.interp(query,bt,bd,left=0,right=0))>CONFLICT_DB:
            raise ValueError('Conflicting low-cut and same-fundamental addition; planner must choose one')
    if not isinstance(unresolved,(list,tuple)) or any(not isinstance(x,str) or not x for x in unresolved):raise ValueError('Explicit unresolved strings required')
    changed=bool(adds) or reduction_plan['assessment'] in ('CANDIDATE','PARTIAL')
    if changed!=(assessment in ('CANDIDATE','PARTIAL')):raise ValueError('Assessment disagrees with requested audio change')
    if changed and (unresolved or reduction_plan['assessment'] in ('PARTIAL','ABSTAIN')) and assessment!='PARTIAL':raise ValueError('Unresolved work requires PARTIAL')
    if not changed and (unresolved or reduction_plan['assessment']=='ABSTAIN') and assessment!='ABSTAIN':raise ValueError('Uncertainty cannot become KEEP')
    result=dict(schema=1,version=VERSION,snapshot_sha256=snapshot.token,source_sha256=snapshot.source.file_sha256,
        physical_sha256=snapshot.physical.file_sha256,planner_id=planner_id,calibration_sha256=calibration_sha256,evidence_scope=evidence_scope,
        assessment=assessment,reduction_plan=reduction_plan,additions=[asdict(a) for a in adds],unresolved=list(unresolved),
        addition_policy='SAME_FUNDAMENTAL_ONLY;_NO_OVERLAP;_NO_LOW_CUT_CONFLICT',stem_samples_in_output=False,
        subjective_quality='NOT_EVALUATED')
    result=json.loads(json.dumps(result,ensure_ascii=False,allow_nan=False));result['sha256']=digest(result);return result


def validate_plan(plan,snapshot):
    p=dict(plan);seal=p.pop('sha256',None)
    if seal!=digest(p) or plan.get('schema')!=1 or plan.get('version')!=VERSION:raise ValueError('Plan seal/version mismatch')
    adds=[]
    for raw in plan['additions']:
        row=dict(raw);row['source_frames']=tuple(row['source_frames']);row['envelope']=tuple(row['envelope']);adds.append(SameFundamentalAdd(**row))
    rebuilt=compile_plan(snapshot,plan['reduction_plan'],adds,planner_id=plan['planner_id'],calibration_sha256=plan['calibration_sha256'],
        evidence_scope=plan['evidence_scope'],assessment=plan['assessment'],unresolved=plan['unresolved'])
    if rebuilt!=plan:raise ValueError('Plan does not rebuild from declared operations')
    return plan


def _addition_block(start,stop,snapshot,adds):
    sr=snapshot.physical.samplerate;pos=np.arange(start,stop,dtype=np.float64);delta=np.zeros((stop-start,2));active=0
    for row in adds:
        frames=np.array([snapshot.clock.nearest(v) for v in row['source_frames']],dtype=np.float64);env=np.asarray(row['envelope'],dtype=float)
        if frames[-1]<=start or frames[0]>=stop:continue
        active+=1
        if active>MAX_ACTIVE_ADDS:raise RuntimeError('Unresolved overlapping additions reached renderer')
        e=np.interp(pos,frames,env,left=0,right=0)
        if not np.any(e):continue
        phase=row['phase_radians']+2*np.pi*row['target_hz']*(pos-frames[0])/sr
        d=row['amplitude']*e*np.cos(phase)
        delta+=np.repeat(d[:,None],2,axis=1)
    return delta


def render(source,physical,destination,snapshot,plan,*,progress=None,chunk_frames=None):
    source,physical,destination=map(Path,(source,physical,destination));snapshot.verify(source,physical);validate_plan(plan,snapshot)
    if not plan['additions']:
        r=base.render(source,physical,destination,snapshot,plan['reduction_plan'],progress=progress,chunk_frames=chunk_frames)
        return dict(r,version=VERSION,plan_sha256=plan['sha256'],same_fundamental_additions=0,addition_delegate_exact=True)
    if destination.exists() or destination.is_symlink():raise FileExistsError('Existing destination preserved')
    if destination.resolve() in (source.resolve(),physical.resolve()):raise ValueError('Immutable input')
    sr=snapshot.physical.samplerate;length=snapshot.physical.frames;width=chunk_frames or 2*sr
    integer(width,'chunk frames',sr//2)
    if width>8*sr:raise ValueError('Unbounded render block')
    # Generate the reduction path into one owned temporary file, then stream the
    # addition. The temp is removed on success/failure and never published.
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,tmpname=tempfile.mkstemp(prefix='.joint46_',suffix='.wav',dir=destination.parent);os.close(fd);tmp=Path(tmpname);tmp.unlink()
    partial=destination.with_name(destination.name+'.partial.wav')
    if partial.exists() or partial.is_symlink():raise FileExistsError('Foreign partial preserved')
    try:
        base_report=base.render(source,physical,tmp,snapshot,plan['reduction_plan'],progress=progress,chunk_frames=min(width,2*sr))
        with sf.SoundFile(tmp) as src,sf.SoundFile(physical) as dry,sf.SoundFile(partial,'w',samplerate=sr,channels=2,format='WAV',subtype='DOUBLE') as dst:
            for start in range(0,length,width):
                stop=min(length,start+width);src.seek(start);x=src.read(stop-start,dtype='float64',always_2d=True);dry.seek(start);original=dry.read(stop-start,dtype='float64',always_2d=True)
                if len(x)!=stop-start or len(original)!=stop-start or not np.isfinite(x).all() or not np.isfinite(original).all():raise ValueError('Invalid render read')
                add=_addition_block(start,stop,snapshot,plan['additions']);add[np.all(original==0,axis=1)]=0
                y=x+add
                if not np.isfinite(y).all():raise RuntimeError('Nonfinite addition result')
                dst.write(y)
                if progress:progress.set('SAME_FUNDAMENTAL_RENDER',stop,length)
        snapshot.verify(source,physical);out=capture(partial)
        if (out.samplerate,out.frames,out.channels)!=(sr,length,2):raise RuntimeError('Output geometry changed')
        if destination.exists():raise FileExistsError('Destination appeared')
        os.rename(partial,destination)
        return dict(version=VERSION,plan_sha256=plan['sha256'],snapshot_sha256=snapshot.token,assessment=plan['assessment'],
            waveform_changed=out.pcm_sha256!=snapshot.physical.pcm_sha256,output_identity=asdict(out),old_note_sub_called=False,
            same_fundamental_additions=len(plan['additions']),addition_delegate_exact=False,stem_samples_in_output=False,
            reduction_report=base_report,subjective_quality='NOT_EVALUATED')
    finally:
        if tmp.exists() and not tmp.is_symlink():tmp.unlink()
        if partial.exists() and not partial.is_symlink():partial.unlink()
