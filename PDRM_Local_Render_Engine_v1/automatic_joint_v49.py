"""PDRM automatic joint planner v49.

v48 supplies source-driven events and physically-confirmed same-fundamental
addition. v49 fixes an identified whole-song normalization blind spot: broad
attenuation is authorized by positive-reference low-vs-mid dominance, for which
common loudness gain cancels. Observer role evidence is still required. This
prevents sparse/long-but-acceptable bass from being cut solely by absolute level
while allowing low-dominant mixes to be corrected.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import copy,json
import numpy as np
from scipy.ndimage import distance_transform_edt
import auto_peak_v34 as auto
import automatic_joint_v48 as base
import automatic_lowend_v41 as broad41
import source_events_v41 as events
import relative_low_dominance_v49 as dominance
import lowend_coordinator_v40 as common
import joint_lowend_v42 as reduction_joint
import joint_lowend_v46 as joint
from physical_add_bridge_v46 import SameFundamentalAdd
from integration_contract_v40 import digest,file_hash

VERSION='automatic-joint-lab-0.2.0'
SYNTHETIC_PROVIDER=base.SYNTHETIC_PROVIDER
SPLEETER_PROVIDER=base.SPLEETER_PROVIDER


def make_calibration(reference_specs,progress=None):
    bundle=broad41.make_calibration(reference_specs,progress)
    bundle['relative_low']=dominance.calibrate(reference_specs,progress)
    old=bundle.pop('sha256');bundle['sha256']=digest(bundle)
    return bundle


def validate_calibration(bundle):
    broad41.validate_calibration(bundle)
    dominance.validate(bundle.get('relative_low',{}),bundle['source_groups'])
    return bundle


def _disabled_legacy(bundle):
    """Keep v48 event/addition logic but prevent absolute-level actuation.

    The original calibration remains the final plan identity. We do not delete
    legacy evidence; the final report records what it would have proposed.
    """
    b=copy.deepcopy(bundle)
    caps=b['broad']['caps']
    for k in ('hit_q90_db','low_floor_q20_db','lowmid_floor_q20_db'):caps[k]+=80.
    caps['low_contrast_min_db']-=80.;caps['low_hit_supported_min_db']-=80.
    b['context']['floor_cap_db']+=80.
    b.pop('sha256');b['sha256']=digest(b)
    broad41.validate_calibration(b);return b


def _as_add(raw):
    row=dict(raw);row['source_frames']=tuple(row['source_frames']);row['envelope']=tuple(row['envelope']);return SameFundamentalAdd(**row)


def _assessment(changed,unresolved,reduction_state):
    if changed:return 'PARTIAL' if unresolved or reduction_state in ('PARTIAL','ABSTAIN') else 'CANDIDATE'
    return 'ABSTAIN' if unresolved or reduction_state=='ABSTAIN' else 'KEEP_SUPPORTED'


class AutomaticJointPlanner:
    def __init__(self,calibration,observer,*,allow_fixture=False):
        self.bundle=json.loads(json.dumps(calibration,allow_nan=False));self.observer=observer;self.allow_fixture=allow_fixture;self.last_report=None
    def identity(self):
        oid=self.observer.identity()
        return dict(planner_id=VERSION,calibration_sha256=self.bundle['sha256'],evidence_scope=oid['evidence_scope'],observer=oid,
            code={n:file_hash(Path(__file__).with_name(n)) for n in ('automatic_joint_v49.py','automatic_joint_v48.py','relative_low_dominance_v49.py','physical_add_bridge_v46.py','joint_lowend_v46.py')})
    def preflight(self):
        validate_calibration(self.bundle)
        # v48 owns strict observer provenance/preflight.
        base.AutomaticJointPlanner(_disabled_legacy(self.bundle),self.observer,allow_fixture=self.allow_fixture).preflight()
    def build(self,context,progress=None):
        self.preflight();snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path);pid=self.identity();oid=self.observer.identity()
        # First obtain source-driven same-fundamental decisions with absolute
        # broad actuation disabled. No manual event times enter this delegate.
        delegated=base.AutomaticJointPlanner(_disabled_legacy(self.bundle),self.observer,allow_fixture=self.allow_fixture)
        base_plan=delegated.build(context,progress);base_report=delegated.last_report
        met=auto.measure(context.physical_path,progress,'RELATIVE_PHYSICAL_MEASURE')
        if met['lufs_i'] is None:raise ValueError('Physical source silent')
        physical=events.extract_features(context.physical_path,anchor_gain_db=-14-met['lufs_i'],progress=progress)
        rel=dominance.analyze(physical,self.bundle['relative_low'])
        times=np.asarray(physical['time'],float);sr=snapshot.source.samplerate;n=snapshot.source.frames;clock=snapshot.clock
        render_positions=times*snapshot.physical.samplerate;delay=clock.delay_numerator/clock.delay_denominator;source_time=(render_positions-delay)/snapshot.physical.samplerate
        raw=np.asarray(rel['low_cut_db'],float);spans=events.ranges_from_depth(source_time,raw,sr,n);schedule=events.schedule(spans,rate=sr,length=n)
        permission=np.zeros(len(times),bool);obs=[]
        for i,w in enumerate(schedule['windows']):
            if progress:progress.set('RELATIVE_ROLE_OBSERVER_WINDOW',i,len(schedule['windows']))
            arrays,meta=self.observer.observe(context.source_path,w['core_start_frame']/sr,w['core_stop_frame']/sr,progress)
            ot,valid,summary=base.verify_observation(arrays,meta,snapshot.source,w,oid,allow_fixture=self.allow_fixture)
            permission|=np.interp(source_time,ot,valid.astype(float),left=0,right=0)>.999;obs.append(dict(window=w,**summary))
        distance=distance_transform_edt(np.r_[False,permission,False])[1:-1]*.01
        depth=raw*np.clip(distance/.08,0,1)
        proposals=broad41.AutomaticRepairPlanner._proposals(source_time,depth,snapshot)
        start_error=dominance.score(physical,self.bundle['relative_low']);trials=[];best=None;selected=0.
        def compile_broad(items,state):return common.compile_plan(snapshot,items,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state)
        reduction_state='CANDIDATE' if proposals else ('ABSTAIN' if rel['candidate'] else 'KEEP_SUPPORTED')
        if proposals:
            with TemporaryDirectory(prefix='relative49_',dir=context.physical_path.parent) as td:
                for strength in (.5,1.):
                    scaled=[common.CutProposal(p.proposal_id,p.branch,p.source_frames,tuple(float(v*strength) for v in p.depth_db),'RELATIVE_LOW_DOMINANCE') for p in proposals]
                    plan=compile_broad(scaled,'CANDIDATE');dest=Path(td)/(f'rel_{strength}.wav')
                    common.render(context.source_path,context.physical_path,dest,snapshot,plan,progress=progress)
                    qm=auto.measure(dest,progress,'RELATIVE_CANDIDATE_MEASURE');f=events.extract_features(dest,anchor_gain_db=-14-qm['lufs_i'],progress=progress);end=dominance.score(f,self.bundle['relative_low']);improved=end<start_error-.05
                    trials.append(dict(strength=strength,initial_excess_db=start_error,remaining_excess_db=end,improved=improved))
                    if improved and (best is None or end<best[0]):best=(end,scaled,strength)
                    if improved and end<=.25:break
            if best is None:proposals=[];reduction_state='ABSTAIN'
            else:proposals=best[1];selected=best[2];reduction_state='CANDIDATE' if best[0]<=.25 else 'PARTIAL'
        broad_plan=compile_broad(proposals,reduction_state)
        reduction_plan=reduction_joint.compile_plan(snapshot,broad_plan,[],planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=reduction_state,unresolved=[])
        additions=[];suppressed=[]
        for raw_add in base_plan['additions']:
            add=_as_add(raw_add)
            if base._conflicts_with_reduction(add,broad_plan,snapshot):suppressed.append(add.proposal_id)
            else:additions.append(add)
        unresolved=list(base_plan.get('unresolved',[]))
        if rel['candidate'] and not proposals:unresolved.append('RELATIVE_LOW_DOMINANCE_UNRESOLVED')
        changed=bool(additions) or reduction_state in ('CANDIDATE','PARTIAL');state=_assessment(changed,unresolved,reduction_state)
        result=joint.compile_plan(snapshot,reduction_plan,additions,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state,unresolved=unresolved)
        snapshot.verify(context.source_path,context.physical_path)
        self.last_report=dict(base_report,version=VERSION,planner_sha256=result['sha256'],relative_low=dict(q90_db=rel['q90_db'],q97_db=rel['q97_db'],cap_q90_db=rel['cap_q90_db'],cap_q97_db=rel['cap_q97_db'],candidate=rel['candidate'],raw_candidate_seconds=float(np.count_nonzero(raw)*.01),supported_candidate_seconds=float(np.count_nonzero(depth)*.01),selected_strength=selected,trials=trials,observer_windows=obs),
            legacy_absolute_candidate_seconds=base_report.get('raw_candidate_seconds',0.),reduction_assessment=reduction_state,accepted_additions=len(additions),suppressed_addition_ids=suppressed,final_assessment=state,unresolved=unresolved,
            broad_authorization_policy='RELATIVE_LOW_VS_MID_REQUIRED;_ROLE_EVIDENCE_REQUIRED',conflict_policy='RELATIVE_REDUCTION_PRIORITY;_NO_ADD_CUT_SELF_CANCELLATION',subjective_quality='NOT_EVALUATED')
        return result
