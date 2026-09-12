"""PDRM automatic joint planner v51: preserve v50 audio policy, prune neural work.

v51 changes *when* Spleeter is asked, not what evidence is required for an
audible action. It removes three classes of observer calls that cannot change
v50's final audio decision:

1. v48's legacy base observer stage. v50 discards inherited additions and
   revalidates every source-proven same-f0 candidate itself.
2. v49 relative-low role observation when the non-negative reduction score is
   <= the 0.05 dB improvement margin. The old acceptance test requires
   end_score < start_score - 0.05, which is then mathematically impossible.
3. v50 same-f0 observation when source-only vetoes already guarantee denial.

All accepted additions still pass the same v50 source proof, source brightness,
role/pitch, physical-fundamental, peak and quantity gates. Stem audio remains
analysis-only and never enters the master.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import numpy as np
from scipy.ndimage import distance_transform_edt

import auto_peak_v34 as auto
import automatic_joint_v48 as base
import automatic_joint_v49 as v49
import automatic_joint_v50 as v50
import automatic_lowend_v41 as broad41
import joint_lowend_v42 as reduction_joint
import joint_lowend_v46 as joint
import lowend_coordinator_v40 as common
import physical_add_bridge_v50 as samef0
import relative_low_dominance_v49 as dominance
import same_f0_permission_v50 as permission
import source_events_v41 as events
from integration_contract_v40 import file_hash

VERSION='automatic-joint-lab-0.4.0'
SYNTHETIC_PROVIDER=base.SYNTHETIC_PROVIDER
SPLEETER_PROVIDER=base.SPLEETER_PROVIDER
make_calibration=v49.make_calibration
validate_calibration=v49.validate_calibration
IMPROVEMENT_MARGIN_DB=.05


def _assessment(changed,unresolved,reduction_state):
    if changed:return 'PARTIAL' if unresolved or reduction_state in ('PARTIAL','ABSTAIN') else 'CANDIDATE'
    return 'ABSTAIN' if unresolved or reduction_state=='ABSTAIN' else 'KEEP_SUPPORTED'


def _source_candidates(source,catalog):
    out=[]
    for e in catalog['events']:
        proof=base._present_fundamental(source,e)
        if proof is not None:
            row=dict(e);row['same_f0']=proof;out.append(row)
    return out


def _source_veto(source,event,proof):
    """Return source-only veto evidence. No separator output is consulted."""
    shape=samef0.source_shape(source,event['start_seconds'],event['end_seconds'])
    reasons,ratio,upper=permission._source_vetoes(proof,shape,permission.Config())
    return shape,list(reasons),float(ratio),float(upper)


def _compile_relative(context,bundle,observer,oid,pid,physical,rel,source_time,snapshot,progress=None):
    """v49 relative reduction with a proof-based zero-opportunity fast path."""
    times=np.asarray(physical['time'],float);sr=snapshot.source.samplerate;n=snapshot.source.frames
    raw=np.asarray(rel['low_cut_db'],float)
    spans=events.ranges_from_depth(source_time,raw,sr,n)
    schedule=events.schedule(spans,rate=sr,length=n)
    start_error=dominance.score(physical,bundle['relative_low'])
    trials=[];selected=0.;obs=[];observer_calls=0

    def compile_broad(items,state):
        return common.compile_plan(snapshot,items,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state)

    # dominance.score is max(0, ...). The legacy acceptance is
    # end < start - .05. At/below .05 no non-negative end can ever pass.
    if start_error<=IMPROVEMENT_MARGIN_DB:
        proposals=[]
        reduction_state='ABSTAIN' if rel['candidate'] else 'KEEP_SUPPORTED'
        return dict(
            broad_plan=compile_broad(proposals,reduction_state),
            reduction_state=reduction_state,trials=trials,selected=selected,obs=obs,
            start_error=float(start_error),schedule=schedule,observer_calls=0,
            zero_score_short_circuit=True,
        )

    permission_mask=np.zeros(len(times),bool)
    for i,w in enumerate(schedule['windows']):
        if progress:progress.set('RELATIVE_ROLE_OBSERVER_WINDOW',i,len(schedule['windows']))
        arrays,meta=observer.observe(context.source_path,w['core_start_frame']/sr,w['core_stop_frame']/sr,progress)
        observer_calls+=1
        ot,valid,summary=base.verify_observation(arrays,meta,snapshot.source,w,oid,allow_fixture=False if oid.get('provider')==SPLEETER_PROVIDER else True)
        permission_mask|=np.interp(source_time,ot,valid.astype(float),left=0,right=0)>.999
        obs.append(dict(window=w,**summary))
    distance=distance_transform_edt(np.r_[False,permission_mask,False])[1:-1]*.01
    depth=raw*np.clip(distance/.08,0,1)
    proposals=broad41.AutomaticRepairPlanner._proposals(source_time,depth,snapshot)
    reduction_state='CANDIDATE' if proposals else ('ABSTAIN' if rel['candidate'] else 'KEEP_SUPPORTED')
    best=None
    if proposals:
        with TemporaryDirectory(prefix='relative51_',dir=context.physical_path.parent) as td:
            for strength in (.5,1.):
                scaled=[common.CutProposal(p.proposal_id,p.branch,p.source_frames,tuple(float(v*strength) for v in p.depth_db),'RELATIVE_LOW_DOMINANCE') for p in proposals]
                plan=compile_broad(scaled,'CANDIDATE');dest=Path(td)/(f'rel_{strength}.wav')
                common.render(context.source_path,context.physical_path,dest,snapshot,plan,progress=progress)
                qm=auto.measure(dest,progress,'RELATIVE_CANDIDATE_MEASURE')
                f=events.extract_features(dest,anchor_gain_db=-14-qm['lufs_i'],progress=progress)
                end=dominance.score(f,bundle['relative_low']);improved=end<start_error-IMPROVEMENT_MARGIN_DB
                trials.append(dict(strength=strength,initial_excess_db=float(start_error),remaining_excess_db=float(end),improved=bool(improved)))
                if improved and (best is None or end<best[0]):best=(end,scaled,strength)
                if improved and end<=.25:break
        if best is None:proposals=[];reduction_state='ABSTAIN'
        else:proposals=best[1];selected=best[2];reduction_state='CANDIDATE' if best[0]<=.25 else 'PARTIAL'
    return dict(
        broad_plan=compile_broad(proposals,reduction_state),reduction_state=reduction_state,
        trials=trials,selected=selected,obs=obs,start_error=float(start_error),schedule=schedule,
        observer_calls=observer_calls,zero_score_short_circuit=False,
    )


class AutomaticJointPlanner:
    def __init__(self,calibration,observer,*,allow_fixture=False):
        self.bundle=json.loads(json.dumps(calibration,allow_nan=False));self.observer=observer;self.allow_fixture=allow_fixture;self.last_report=None

    def identity(self):
        oid=self.observer.identity()
        names=('automatic_joint_v51.py','automatic_joint_v50.py','automatic_joint_v49.py','automatic_joint_v48.py','relative_low_dominance_v49.py','physical_add_bridge_v50.py','same_f0_permission_v50.py','joint_lowend_v46.py')
        return dict(planner_id=VERSION,calibration_sha256=self.bundle['sha256'],evidence_scope=oid['evidence_scope'],observer=oid,code={n:file_hash(Path(__file__).with_name(n)) for n in names})

    def preflight(self):
        validate_calibration(self.bundle)
        # Reuse v50's accepted observer provenance and safety gates; this does
        # not execute neural inference.
        v50.AutomaticJointPlanner(self.bundle,self.observer,allow_fixture=self.allow_fixture).preflight()

    def build(self,context,progress=None):
        self.preflight();snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path)
        pid=self.identity();oid=self.observer.identity();sr=snapshot.source.samplerate;n=snapshot.source.frames

        source_features,catalog=events.analyze_source(context.source_path,progress)
        refined=_source_candidates(context.source_path,catalog)
        # Counterfactual old v48 source-event schedule. Computing the schedule is
        # cheap and lets the report state how many now-obsolete neural calls were
        # removed without executing them.
        old_base_schedule=events.schedule([base._event_span(e) for e in refined],rate=sr,length=n)

        met=auto.measure(context.physical_path,progress,'RELATIVE_PHYSICAL_MEASURE')
        if met['lufs_i'] is None:raise ValueError('Physical source silent')
        physical=events.extract_features(context.physical_path,anchor_gain_db=-14-met['lufs_i'],progress=progress)
        rel=dominance.analyze(physical,self.bundle['relative_low'])
        times=np.asarray(physical['time'],float);clock=snapshot.clock
        render_positions=times*snapshot.physical.samplerate;delay=clock.delay_numerator/clock.delay_denominator
        source_time=(render_positions-delay)/snapshot.physical.samplerate
        relative=_compile_relative(context,self.bundle,self.observer,oid,pid,physical,rel,source_time,snapshot,progress)
        broad_plan=relative['broad_plan'];reduction_state=relative['reduction_state']
        reduction_plan=reduction_joint.compile_plan(snapshot,broad_plan,[],planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=reduction_state,unresolved=[])

        unresolved=[]
        if rel['candidate'] and not any(broad_plan['low_cut_db']):unresolved.append('RELATIVE_LOW_DOMINANCE_UNRESOLVED')
        adds=[];records=[];suppressed=[];source_veto_avoided=0;candidate_observer_calls=0
        for row in refined:
            proof=row['same_f0'];start=float(row['start_seconds']);end=float(row['end_seconds'])
            shape,source_reasons,ratio,upper=_source_veto(context.source_path,row,proof)
            rec=dict(event_id=row.get('event_id'),start_seconds=start,end_seconds=end,source_detector_hz=row.get('pitch_hz'),same_f0=proof,source_proof=proof,source_shape=shape)
            if source_reasons:
                source_veto_avoided+=1
                decision=dict(allowed=False,reason_codes=source_reasons,permission_version=permission.VERSION,permission_path='PREOBSERVER_SOURCE_VETO',source_shape=shape,source_proof=proof,source_veto_reasons=source_reasons,envelope_role_indices=[2])
                rec['evidence']=dict(version=samef0.VERSION,status=source_reasons[0],source_decision=decision,source_sha256=snapshot.source.file_sha256,physical_sha256=snapshot.physical.file_sha256,snapshot_sha256=snapshot.token,source_shape=shape,source_proof=proof,stem_samples_in_output=False,new_octave_allowed=False,subjective_quality='NOT_EVALUATED')
                rec['planner_resolution']='V51_PREOBSERVER_SOURCE_VETO';records.append(rec);continue

            duration=end-start;guard=min(.35,max(.15,duration*.08));core_start=max(0.,start-guard);core_end=min(n/sr,end+guard)
            arrays,meta=self.observer.observe(context.source_path,core_start,core_end,progress);candidate_observer_calls+=1
            event=dict(start=start,end=end,source_f0_hz=float(proof['f0_hz']),target_hz=float(proof['f0_hz']))
            proposal,ev=samef0.confirm(context,event,arrays,meta,proof);rec['evidence']=ev
            if proposal is None:
                rec['planner_resolution']='V51_SAME_F0_DENIED';records.append(rec)
                if ev.get('status') in base.UNRESOLVED_ADD_STATUSES:unresolved.append(ev['status']+':'+str(row.get('event_id')))
                continue
            if base._conflicts_with_reduction(proposal,broad_plan,snapshot):
                rec['planner_resolution']='V51_SUPPRESSED_BY_REDUCTION';suppressed.append(proposal.proposal_id);records.append(rec);continue
            if any(base._overlap(proposal,p) for p in adds):
                rec['planner_resolution']='V51_SUPPRESSED_OVERLAP';unresolved.append('OVERLAPPING_V51_ADDITION:'+str(row.get('event_id')));records.append(rec);continue
            adds.append(proposal);rec['planner_resolution']='V51_ADD_ACCEPTED';records.append(rec)

        changed=bool(adds) or reduction_state in ('CANDIDATE','PARTIAL');state=_assessment(changed,unresolved,reduction_state)
        result=joint.compile_plan(snapshot,reduction_plan,adds,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state,unresolved=unresolved)
        snapshot.verify(context.source_path,context.physical_path)

        paths=[r.get('evidence',{}).get('source_decision',{}).get('permission_path') for r in records if r.get('planner_resolution')=='V51_ADD_ACCEPTED']
        old_relative_calls=len(relative['schedule']['windows'])
        executed=relative['observer_calls']+candidate_observer_calls
        theoretical=len(old_base_schedule['windows'])+old_relative_calls+len(refined)
        avoided_base=len(old_base_schedule['windows'])
        avoided_zero=old_relative_calls if relative['zero_score_short_circuit'] else 0
        avoided=avoided_base+avoided_zero+source_veto_avoided
        self.last_report=dict(
            version=VERSION,planner_sha256=result['sha256'],manual_event_times_used=False,
            automatically_discovered_events=len(catalog['events']),tonal_same_f0_candidates=len(refined),
            source_same_f0_refinements=[dict(event_id=e.get('event_id'),start_seconds=e['start_seconds'],end_seconds=e['end_seconds'],source_detector_hz=e.get('pitch_hz'),same_f0=e['same_f0']) for e in refined],
            addition_records=records,v50_same_f0_records=records,v51_same_f0_records=records,
            accepted_additions=len(adds),v50_accepted=len(adds),v51_accepted=len(adds),fallback_accepted=sum(p=='EXISTING_WEAK_F0_FALLBACK' for p in paths),
            v50_permission_paths=paths,v51_permission_paths=paths,v50_suppressed_ids=suppressed,v51_suppressed_ids=suppressed,
            same_f0_v50_policy='ALL_ADDS_REQUIRE_ORIGINAL_WEAK_F0_AND_SOURCE_BRIGHTNESS_VETO;_GROUPED_FALLBACK_ONLY_FOR_LOCAL_ROLE_PITCH_ABSTAIN',
            same_f0_v51_policy='V50_AUDIO_GATES_UNCHANGED;_SOURCE_VETO_BEFORE_NEURAL_INFERENCE;_OBSOLETE_BASE_OBSERVER_REMOVED;_NONIMPROVABLE_RELATIVE_SCORE_SHORT_CIRCUITED',
            relative_low=dict(q90_db=rel['q90_db'],q97_db=rel['q97_db'],cap_q90_db=rel['cap_q90_db'],cap_q97_db=rel['cap_q97_db'],candidate=rel['candidate'],raw_candidate_seconds=float(np.count_nonzero(np.asarray(rel['low_cut_db']))*.01),supported_candidate_seconds=float(sum(len(p.depth_db) for p in [])) if False else 0.0,selected_strength=relative['selected'],trials=relative['trials'],observer_windows=relative['obs'],initial_excess_db=relative['start_error'],zero_score_short_circuit=relative['zero_score_short_circuit']),
            reduction_assessment=reduction_state,legacy_absolute_candidate_seconds=0.0,
            broad_authorization_policy='RELATIVE_LOW_VS_MID_REQUIRED;_ROLE_EVIDENCE_REQUIRED',conflict_policy='RELATIVE_REDUCTION_PRIORITY;_NO_ADD_CUT_SELF_CANCELLATION',
            observer_optimization=dict(strategy='EVIDENCE_PRESERVING_PRUNING',theoretical_v50_observer_calls=theoretical,observer_calls_executed=executed,observer_calls_avoided=avoided,observer_calls_avoided_obsolete_base_stage=avoided_base,observer_calls_avoided_zero_reduction_score=avoided_zero,observer_calls_avoided_source_veto=source_veto_avoided,candidate_observer_calls=candidate_observer_calls,relative_observer_calls=relative['observer_calls']),
            final_assessment=state,unresolved=unresolved,old_note_sub_called=False,sub_synthesis='SAME_FUNDAMENTAL_ONLY_CONNECTED',observer_provider=oid.get('provider'),observer_identity=oid,subjective_quality='NOT_EVALUATED')
        return result
