"""PDRM automatic joint planner v50.

v49 remains the primary automatic planner. v50 only revisits SAME-FUNDAMENTAL
candidates that v37 rejected solely for local role/pitch ambiguity. The rescue
uses physical_add_bridge_v50, which requires an existing weak f0 in the original
2mix, low source brightness, drum/vocal vetoes, stable pitch and prepared-2mix
physical deficiency. It never rescues octave-down/missing-fundamental requests.
"""
from __future__ import annotations
from pathlib import Path
import json
import automatic_joint_v49 as primary
import automatic_joint_v48 as base
import physical_add_bridge_v50 as fallback
import joint_lowend_v46 as joint
from integration_contract_v40 import file_hash

VERSION='automatic-joint-lab-0.3.0'
SYNTHETIC_PROVIDER=base.SYNTHETIC_PROVIDER
SPLEETER_PROVIDER=base.SPLEETER_PROVIDER
make_calibration=primary.make_calibration
validate_calibration=primary.validate_calibration


def _state(changed,unresolved,reduction_state):
    if changed:return 'PARTIAL' if unresolved or reduction_state in ('PARTIAL','ABSTAIN') else 'CANDIDATE'
    return 'ABSTAIN' if unresolved or reduction_state=='ABSTAIN' else 'KEEP_SUPPORTED'


class AutomaticJointPlanner:
    def __init__(self,calibration,observer,*,allow_fixture=False):
        self.bundle=json.loads(json.dumps(calibration,allow_nan=False));self.observer=observer;self.allow_fixture=allow_fixture;self.last_report=None
    def identity(self):
        oid=self.observer.identity()
        return dict(planner_id=VERSION,calibration_sha256=self.bundle['sha256'],evidence_scope=oid['evidence_scope'],observer=oid,
            code={n:file_hash(Path(__file__).with_name(n)) for n in ('automatic_joint_v50.py','automatic_joint_v49.py','automatic_joint_v48.py','physical_add_bridge_v50.py','same_f0_permission_v50.py','joint_lowend_v46.py')})
    def preflight(self):
        primary.AutomaticJointPlanner(self.bundle,self.observer,allow_fixture=self.allow_fixture).preflight()
    def build(self,context,progress=None):
        self.preflight();delegate=primary.AutomaticJointPlanner(self.bundle,self.observer,allow_fixture=self.allow_fixture);initial=delegate.build(context,progress);report=delegate.last_report
        snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path);pid=self.identity();adds=[primary._as_add(x) for x in initial['additions']];unresolved=list(initial.get('unresolved',[]));rescues=[];suppressed=[]
        for row in report.get('addition_records',[]):
            evidence=row.get('evidence') or {};decision=evidence.get('source_decision') or {}
            if decision.get('allowed') or decision.get('reason_codes')!=['ABSTAIN_LOCAL_ROLE_OR_PITCH']:continue
            proof=row.get('same_f0')
            if not isinstance(proof,dict):continue
            start=float(row['start_seconds']);end=float(row['end_seconds']);duration=end-start
            # Observer core is derived from the automatically discovered event,
            # not a human timestamp. Keep a small surrounding core so the event
            # is never on the observer boundary; the worker adds two larger pads.
            guard=min(.35,max(.15,duration*.08));core_start=max(0.,start-guard);core_end=min(snapshot.source.frames/snapshot.source.samplerate,end+guard)
            arrays,meta=self.observer.observe(context.source_path,core_start,core_end,progress)
            event=dict(start=start,end=end,source_f0_hz=float(proof['f0_hz']),target_hz=float(proof['f0_hz']))
            proposal,ev=fallback.confirm(context,event,arrays,meta,proof)
            rec=dict(event_id=row.get('event_id'),start_seconds=start,end_seconds=end,source_proof=proof,evidence=ev)
            if proposal is None:rec['planner_resolution']='FALLBACK_DENIED';rescues.append(rec);continue
            reduction_plan=initial['reduction_plan'];broad_plan=reduction_plan['broad_plan']
            if base._conflicts_with_reduction(proposal,broad_plan,snapshot):rec['planner_resolution']='FALLBACK_SUPPRESSED_BY_REDUCTION';suppressed.append(proposal.proposal_id);rescues.append(rec);continue
            if any(base._overlap(proposal,p) for p in adds):rec['planner_resolution']='FALLBACK_SUPPRESSED_OVERLAP';unresolved.append('OVERLAPPING_FALLBACK_ADDITION:'+str(row.get('event_id')));rescues.append(rec);continue
            adds.append(proposal);rec['planner_resolution']='FALLBACK_ADD_ACCEPTED';rescues.append(rec)
        changed=bool(adds) or initial['reduction_plan']['assessment'] in ('CANDIDATE','PARTIAL');state=_state(changed,unresolved,initial['reduction_plan']['assessment'])
        result=joint.compile_plan(snapshot,initial['reduction_plan'],adds,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state,unresolved=unresolved)
        snapshot.verify(context.source_path,context.physical_path)
        self.last_report=dict(report,version=VERSION,planner_sha256=result['sha256'],same_f0_fallback_policy='ONLY_LEGACY_LOCAL_ROLE_PITCH_ABSTAIN;_ORIGINAL_WEAK_F0;_SOURCE_BRIGHTNESS_VETO;_DRUM_VOCAL_VETO;_STABLE_PITCH',
            fallback_records=rescues,fallback_accepted=sum(r.get('planner_resolution')=='FALLBACK_ADD_ACCEPTED' for r in rescues),fallback_suppressed_ids=suppressed,
            accepted_additions=len(adds),final_assessment=state,unresolved=unresolved,subjective_quality='NOT_EVALUATED')
        return result
