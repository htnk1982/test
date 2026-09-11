"""PDRM automatic joint planner v50.

v49 remains the primary event/reduction planner, but v50 revalidates *every*
same-fundamental candidate through physical_add_bridge_v50. Thus original-source
weak-f0 and spectral-brightness vetoes also apply to candidates that the legacy
bass gate would otherwise allow. A grouped bass+other fallback is available only
for the narrow legacy-local-role/pitch abstention case. No octave/missing-f0
request can be rescued.
"""
from __future__ import annotations
from pathlib import Path
import json
import automatic_joint_v49 as primary
import automatic_joint_v48 as base
import physical_add_bridge_v50 as samef0
import joint_lowend_v46 as joint
from integration_contract_v40 import file_hash

VERSION='automatic-joint-lab-0.3.1'
SYNTHETIC_PROVIDER=base.SYNTHETIC_PROVIDER
SPLEETER_PROVIDER=base.SPLEETER_PROVIDER
make_calibration=primary.make_calibration
validate_calibration=primary.validate_calibration


def _state(changed,unresolved,reduction_state):
    if changed:return 'PARTIAL' if unresolved or reduction_state in ('PARTIAL','ABSTAIN') else 'CANDIDATE'
    return 'ABSTAIN' if unresolved or reduction_state=='ABSTAIN' else 'KEEP_SUPPORTED'


def _keep_reduction_unresolved(values):
    return [v for v in values if v=='BROAD_REPAIR_UNRESOLVED' or v=='RELATIVE_LOW_DOMINANCE_UNRESOLVED']


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
        snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path);pid=self.identity();adds=[];unresolved=_keep_reduction_unresolved(initial.get('unresolved',[]));records=[];suppressed=[]
        # Re-evaluate every source-proven same-f0 event. Do not inherit v49 audio
        # additions directly, because v50's source-shape veto must apply even to
        # legacy-strict ALLOW decisions (e.g. deep voice mislabelled as bass).
        for row in report.get('addition_records',[]):
            proof=row.get('same_f0')
            if not isinstance(proof,dict):continue
            start=float(row['start_seconds']);end=float(row['end_seconds']);duration=end-start;guard=min(.35,max(.15,duration*.08));core_start=max(0.,start-guard);core_end=min(snapshot.source.frames/snapshot.source.samplerate,end+guard)
            arrays,meta=self.observer.observe(context.source_path,core_start,core_end,progress)
            event=dict(start=start,end=end,source_f0_hz=float(proof['f0_hz']),target_hz=float(proof['f0_hz']))
            proposal,ev=samef0.confirm(context,event,arrays,meta,proof);rec=dict(event_id=row.get('event_id'),start_seconds=start,end_seconds=end,source_detector_hz=row.get('source_detector_hz'),source_proof=proof,evidence=ev)
            if proposal is None:
                rec['planner_resolution']='V50_SAME_F0_DENIED';records.append(rec)
                if ev.get('status') in base.UNRESOLVED_ADD_STATUSES:unresolved.append(ev['status']+':'+str(row.get('event_id')))
                continue
            broad_plan=initial['reduction_plan']['broad_plan']
            if base._conflicts_with_reduction(proposal,broad_plan,snapshot):rec['planner_resolution']='V50_SUPPRESSED_BY_REDUCTION';suppressed.append(proposal.proposal_id);records.append(rec);continue
            if any(base._overlap(proposal,p) for p in adds):rec['planner_resolution']='V50_SUPPRESSED_OVERLAP';unresolved.append('OVERLAPPING_V50_ADDITION:'+str(row.get('event_id')));records.append(rec);continue
            adds.append(proposal);rec['planner_resolution']='V50_ADD_ACCEPTED';records.append(rec)
        changed=bool(adds) or initial['reduction_plan']['assessment'] in ('CANDIDATE','PARTIAL');state=_state(changed,unresolved,initial['reduction_plan']['assessment'])
        result=joint.compile_plan(snapshot,initial['reduction_plan'],adds,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state,unresolved=unresolved);snapshot.verify(context.source_path,context.physical_path)
        paths=[r.get('evidence',{}).get('source_decision',{}).get('permission_path') for r in records if r.get('planner_resolution')=='V50_ADD_ACCEPTED']
        self.last_report=dict(report,version=VERSION,planner_sha256=result['sha256'],same_f0_v50_policy='ALL_ADDS_REQUIRE_ORIGINAL_WEAK_F0_AND_SOURCE_BRIGHTNESS_VETO;_GROUPED_FALLBACK_ONLY_FOR_LOCAL_ROLE_PITCH_ABSTAIN',
            v50_same_f0_records=records,v50_accepted=len(adds),v50_permission_paths=paths,fallback_accepted=sum(p=='EXISTING_WEAK_F0_FALLBACK' for p in paths),v50_suppressed_ids=suppressed,
            accepted_additions=len(adds),final_assessment=state,unresolved=unresolved,subjective_quality='NOT_EVALUATED')
        return result
