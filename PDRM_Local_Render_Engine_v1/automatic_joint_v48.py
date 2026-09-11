"""Automatic joint low-end planner: original 2mix -> one joint-v46 plan.

No handwritten event times. Source events come from source_events_v41. A role
observer may permit actuation but never contributes audio. Broad reduction is
selected on the prepared 2mix; same-fundamental addition is re-confirmed on the
same prepared 2mix. When reduction and addition conflict, reduction wins.

A dominant harmonic is never divided blindly. For same-fundamental repair only,
a lower f0 candidate must itself be measurably present in the original 2mix and
have harmonic support. Pure 110 Hz therefore does not become 55 Hz; a real but
weak 55 Hz beneath strong 110/165 Hz may be re-identified as the existing f0.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import json,math
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import distance_transform_edt
import auto_peak_v34 as auto
import lowend_boundary_lab as boundary
import context_occupancy_lab as occupancy
import lowend_coordinator_v40 as common
import joint_lowend_v42 as reduction_joint
import joint_lowend_v46 as joint
import physical_add_bridge_v46 as add_bridge
import automatic_lowend_v41 as broad41
import source_events_v41 as events
from integration_contract_v40 import Span,digest,file_hash

VERSION='automatic-joint-lab-0.1.1'
SYNTHETIC_PROVIDER='synthetic_joint48'
SPLEETER_PROVIDER='spleeter_runtime48'
UNRESOLVED_ADD_STATUSES={
    'ABSTAIN_MISSING_FUNDAMENTAL_REPAIR_UNIMPLEMENTED','ABSTAIN_INSUFFICIENT_PHYSICAL_HARMONICS',
    'ABSTAIN_NO_SUPPORTED_PHYSICAL_ENVELOPE','ABSTAIN_PHYSICAL_PEAK','ABSTAIN_COLLAPSED_PHYSICAL_EVENT',
    'ABSTAIN_EMPTY_COMPACT_ENVELOPE'
}


def verify_observation(arrays,meta,source_id,window,provider_id,*,allow_fixture=False):
    if meta.get('source_sha256')!=source_id.file_sha256 or meta.get('source_frames')!=source_id.frames or meta.get('source_samplerate')!=source_id.samplerate:raise ValueError('Observation source mismatch')
    if meta.get('source_order')!=['mix','drums','bass','other','vocals']:raise ValueError('Wrong source order')
    provider=meta.get('provider')
    if provider!=provider_id.get('provider'):raise ValueError('Wrong observer provider')
    if provider==SYNTHETIC_PROVIDER:
        if allow_fixture is not True or provider_id.get('evidence_scope')!='engineering_fixture':raise ValueError('Synthetic roles prohibited outside explicit fixture')
    elif provider==SPLEETER_PROVIDER:
        if provider_id.get('evidence_scope')!='research_observer' or provider_id.get('private_audio_calibrated') is not False or provider_id.get('product_release') is not False:raise ValueError('Spleeter adapter scope was silently promoted')
        if (meta.get('version')!='role-observer-0.2.0' or meta.get('model_sha256')!=provider_id.get('model_asset_sha256') or meta.get('runtime_manifest_sha256')!=provider_id.get('runtime_manifest_sha256') or meta.get('preprocessing_sha256')!=provider_id.get('preprocessing_sha256')):raise ValueError('Spleeter model/runtime/preprocessing mismatch')
        if meta.get('output_audio_uses_stems') is not False or meta.get('stem_audio_persisted') is not False or meta.get('network_downloads_allowed') is not False:raise ValueError('Observer crossed analysis-only/offline boundary')
    else:raise ValueError('Unsupported observer provider')
    rate=source_id.samplerate;start=window['core_start_frame']/rate;end=window['core_stop_frame']/rate
    if abs(float(meta['start_seconds'])-start)>1/rate or abs(float(meta['end_seconds'])-end)>1/rate:raise ValueError('Wrong observed interval')
    t=np.asarray(arrays['time'],float);low=np.asarray(arrays['low_power'],float)
    if len(t)<2 or low.shape!=(2,len(t),5) or not np.isfinite(low).all() or np.any(low<0):raise ValueError('Invalid role powers')
    if not np.isfinite(t).all() or not np.allclose(np.diff(t),.01,atol=1e-8) or abs(t[0]-start)>.011 or abs(t[-1]+.01-end)>.011:raise ValueError('Observer clock/grid mismatch')
    for key in ('body_power','focus_power'):
        p=np.asarray(arrays[key],float)
        if p.shape!=low.shape or not np.isfinite(p).all() or np.any(p<0):raise ValueError('Invalid observer '+key)
    for key in ('bass_f0_hz','bass_periodicity'):
        p=np.asarray(arrays[key],float)
        if p.shape!=(2,len(t)) or not np.isfinite(p).all() or np.any(p<0):raise ValueError('Invalid observer '+key)
    shares=low[:,:,1:]/np.maximum(low[:,:,1:].sum(axis=2,keepdims=True),1e-24);grouped=shares[:,:,0]+shares[:,:,1];disagreement=np.sum(abs(shares[0]-shares[1]),axis=1)/2;instrument=(low[:,:,1]+low[:,:,2]).min(axis=0)
    ok=(grouped.min(axis=0)>=.75)&(shares[:,:,3].max(axis=0)<=.15)&(disagreement<=.25);ok&=(low[:,:,0].min(axis=0)>1e-12)&(instrument>=.05*low[:,:,0].min(axis=0));ok&=(t>=start+.4)&(t<=end-.4)
    return t,ok,dict(provider=provider,frames=len(t),supported_frames=int(ok.sum()),supported_fraction=float(ok.mean()),context_disagreement_p95=float(np.percentile(disagreement,95)),probabilities_calibrated=False,neural_inference=provider==SPLEETER_PROVIDER,stem_audio_in_output=False)


def _event_span(event):return Span(int(event['start_frame']),int(event['stop_frame']))


def _present_fundamental(source,event):
    """Return a 30–70 Hz f0 only if that component exists in original audio."""
    if event.get('pitch_status')!='PERIODIC_CANDIDATE' or event.get('pitch_hz') is None:return None
    base=float(event['pitch_hz']);duration=float(event['end_seconds'])-float(event['start_seconds'])
    if not .12<=duration<=3.:return None
    candidates=[]
    for divisor in (1,2,3,4):
        f=base/divisor
        if 30<=f<=70 and all(abs(1200*math.log2(f/x))>35 for x in candidates):candidates.append(f)
    if not candidates:return None
    with sf.SoundFile(source) as handle:
        sr=handle.samplerate;a=int(event['start_frame']);b=int(event['stop_frame']);length=min(b-a,round(1.2*sr));first=a+max(0,(b-a-length)//2);handle.seek(first);x=handle.read(length,dtype='float64',always_2d=True)
    if len(x)<round(.12*sr) or not np.isfinite(x).all():return None
    power=np.mean(x*x,axis=0);mono=x[:,int(np.argmax(power))];mono=mono-mono.mean();rms=float(np.sqrt(np.mean(mono*mono)))
    if rms<1e-7:return None
    w=signal.windows.tukey(len(mono),alpha=.2);t=np.arange(len(mono))/sr;accepted=[]
    for f0 in candidates:
        cols=[]
        for h in range(1,7):
            if h*f0>=min(750,sr/2-50):break
            cols.extend((np.cos(2*np.pi*f0*h*t),np.sin(2*np.pi*f0*h*t)))
        if len(cols)<4:continue
        design=np.column_stack(cols);coef=np.linalg.lstsq(design*w[:,None],mono*w,rcond=None)[0];amps=np.hypot(coef[::2],coef[1::2]);upper=float(max(amps[1:]));fund=float(amps[0]);support=int(np.sum(amps[1:]>=max(upper*.12,1e-9)))
        present=fund>=max(upper*.02,rms*.003,1e-7)
        if present and support>=1:accepted.append(dict(f0_hz=float(f0),fundamental_amplitude=fund,upper_max=upper,fundamental_to_upper_ratio=float(fund/max(upper,1e-24)),harmonic_support=support,original_detector_hz=base))
    if not accepted:return None
    best=min(accepted,key=lambda r:r['f0_hz']);best['method']='ORIGINAL_COMPONENT_PRESENT;_HARMONIC_SUPPORTED;_NO_MISSING_FUNDAMENTAL';return best


def _addition_event(event):
    f=float(event['same_f0']['f0_hz']);return dict(start=float(event['start_seconds']),end=float(event['end_seconds']),source_f0_hz=f,target_hz=f)


def _observation_for(event,observed):
    a=float(event['start_seconds']);b=float(event['end_seconds']);candidates=[row for row in observed if a>=row['meta']['start_seconds']+.001 and b<=row['meta']['end_seconds']-.001]
    return None if not candidates else min(candidates,key=lambda r:(r['meta']['end_seconds']-r['meta']['start_seconds'],r['meta']['start_seconds']))


def _conflicts_with_reduction(add,broad_plan,snapshot):
    frames=np.asarray(broad_plan['physical_frames'],float);depth=np.asarray(broad_plan['low_cut_db'],float);source=np.asarray(add.source_frames,float);env=np.asarray(add.envelope,float);active=source[env>1e-6]
    if not len(active):return False
    physical=np.array([snapshot.clock.nearest(int(v)) for v in active],float);return bool(np.max(np.interp(physical,frames,depth,left=0,right=0))>joint.CONFLICT_DB)


def _overlap(a,b):return max(a.source_frames[0],b.source_frames[0])<min(a.source_frames[-1],b.source_frames[-1])


class AutomaticJointPlanner:
    def __init__(self,calibration,observer,*,allow_fixture=False):self.bundle=json.loads(json.dumps(calibration,allow_nan=False));self.observer=observer;self.allow_fixture=allow_fixture;self.last_report=None
    def identity(self):
        oid=self.observer.identity();return dict(planner_id=VERSION,calibration_sha256=self.bundle['sha256'],evidence_scope=oid['evidence_scope'],observer=oid,code={n:file_hash(Path(__file__).with_name(n)) for n in ('automatic_joint_v48.py','automatic_lowend_v41.py','source_events_v41.py','physical_add_bridge_v46.py','joint_lowend_v46.py')})
    def preflight(self):
        broad41.validate_calibration(self.bundle);oid=self.observer.identity();provider=oid.get('provider')
        if provider==SYNTHETIC_PROVIDER:
            if self.allow_fixture is not True or oid.get('evidence_scope')!='engineering_fixture':raise ValueError('Synthetic observer requires explicit fixture mode')
        elif provider==SPLEETER_PROVIDER:
            required=('model_asset_sha256','runtime_manifest_sha256','worker_sha256','preprocessing_sha256')
            if oid.get('evidence_scope')!='research_observer' or any(not isinstance(oid.get(k),str) or len(oid[k])!=64 for k in required):raise ValueError('Incomplete deployable observer identity')
            if oid.get('stem_audio_in_master') is not False or oid.get('runtime_model_download') is not False:raise ValueError('Observer runtime policy mismatch')
        else:raise ValueError('Unknown observer')
        self.observer.preflight()
    def build(self,context,progress=None):
        self.preflight();snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path);oid=self.observer.identity();source_features,catalog=events.analyze_source(context.source_path,progress)
        refined=[]
        for e in catalog['events']:
            proof=_present_fundamental(context.source_path,e)
            if proof is not None:
                row=dict(e);row['same_f0']=proof;refined.append(row)
        met=auto.measure(context.physical_path,progress,'PLANNER_PHYSICAL_MEASURE')
        if met['lufs_i'] is None:raise ValueError('Physical source silent')
        physical=events.extract_features(context.physical_path,anchor_gain_db=-14-met['lufs_i'],progress=progress);bp=boundary.plan(physical,self.bundle['broad']);cp=occupancy.plan(physical,self.bundle['context'])
        times=np.asarray(physical['time']);raw=np.maximum(bp['low_cut_db'],cp['low_cut_db']);sr=snapshot.source.samplerate;n=snapshot.source.frames;clock=snapshot.clock;render_positions=times*snapshot.physical.samplerate;delay=clock.delay_numerator/clock.delay_denominator;source_time=(render_positions-delay)/snapshot.physical.samplerate
        broad_spans=events.ranges_from_depth(source_time,raw,sr,n);schedule=events.schedule(broad_spans+[_event_span(e) for e in refined],rate=sr,length=n);permission=np.zeros(len(times),bool);observed=[];observation_summaries=[]
        for index,w in enumerate(schedule['windows']):
            if progress:progress.set('ROLE_OBSERVER_WINDOW',index,len(schedule['windows']))
            arrays,meta=self.observer.observe(context.source_path,w['core_start_frame']/sr,w['core_stop_frame']/sr,progress);ot,valid,summary=verify_observation(arrays,meta,snapshot.source,w,oid,allow_fixture=self.allow_fixture);permission|=np.interp(source_time,ot,valid.astype(float),left=0,right=0)>.999;observed.append(dict(window=w,arrays=arrays,meta=meta));observation_summaries.append(dict(window=w,**summary))
        distance=distance_transform_edt(np.r_[False,permission,False])[1:-1]*.01;depth=raw*np.clip(distance/.08,0,1);proposals=broad41.AutomaticRepairPlanner._proposals(source_time,depth,snapshot);assessment='CANDIDATE' if proposals else ('ABSTAIN' if raw.any() or bp.get('deferred_reason_codes',[]) else 'KEEP_SUPPORTED');pid=self.identity()
        def compile_broad(items,state):return common.compile_plan(snapshot,items,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state)
        trials=[];selected=0.;best=None
        def error(f):
            sig=boundary.signature(f);values=[]
            if 'EXCESS_HIT_LEVEL' in bp['reason_codes']:values.append(max(0.,sig['hit_q90_db']-self.bundle['broad']['caps']['hit_q90_db']))
            if 'EXCESS_LOW_FLOOR' in bp['reason_codes']:values.append(max(0.,sig['low_floor_q20_db']-self.bundle['broad']['caps']['low_floor_q20_db']))
            if cp['selected_windows']:values.append(occupancy.score(f,cp))
            return float(sum(values))
        initial=error(physical)
        if proposals:
            with TemporaryDirectory(prefix='plan48_',dir=context.physical_path.parent) as tmp:
                for strength in (.5,1.):
                    scaled=[common.CutProposal(p.proposal_id,p.branch,p.source_frames,tuple(float(d*strength) for d in p.depth_db),p.reason) for p in proposals];candidate=compile_broad(scaled,'CANDIDATE');dest=Path(tmp)/f'broad_{strength}.wav';common.render(context.source_path,context.physical_path,dest,snapshot,candidate,progress=progress);qm=auto.measure(dest,progress,'LOWEND_CANDIDATE_MEASURE');ff=events.extract_features(dest,anchor_gain_db=-14-qm['lufs_i'],progress=progress);e=error(ff);improved=e<initial-.05;trials.append(dict(strength=strength,initial_error_db=initial,remaining_error_db=e,improved=improved))
                    if improved and (best is None or e<best[0]):best=(e,scaled,strength)
                    if improved and e<=.25:break
                if best:proposals=best[1];selected=best[2];assessment='CANDIDATE' if best[0]<=.25 else 'PARTIAL'
                else:proposals=[];assessment='ABSTAIN'
        broad_plan=compile_broad(proposals,assessment);reduction_plan=reduction_joint.compile_plan(snapshot,broad_plan,[],planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=assessment,unresolved=[])
        additions=[];addition_records=[];unresolved=[]
        for e in refined:
            row=_observation_for(e,observed)
            if row is None:addition_records.append(dict(event_id=e['event_id'],status='ABSTAIN_NO_CONTAINING_OBSERVATION',source_pitch=e.get('pitch_hz'),same_f0=e['same_f0']));unresolved.append('NO_OBSERVATION_FOR_TONAL_EVENT:'+e['event_id']);continue
            proposal,evidence=add_bridge.confirm(context,_addition_event(e),row['arrays'],row['meta']);record=dict(event_id=e['event_id'],source_detector_hz=e.get('pitch_hz'),same_f0=e['same_f0'],start_seconds=e['start_seconds'],end_seconds=e['end_seconds'],evidence=evidence)
            if proposal is None:
                if evidence['status'] in UNRESOLVED_ADD_STATUSES:unresolved.append(evidence['status']+':'+e['event_id'])
                addition_records.append(record);continue
            if _conflicts_with_reduction(proposal,broad_plan,snapshot):record['planner_resolution']='SUPPRESSED_SAME_FUNDAMENTAL_ADD;_BROAD_REDUCTION_PRIORITY';addition_records.append(record);continue
            if any(_overlap(proposal,p) for p in additions):record['planner_resolution']='SUPPRESSED_OVERLAPPING_ADDITION;_MONOPHONIC_POLICY';addition_records.append(record);unresolved.append('OVERLAPPING_ADDITION:'+e['event_id']);continue
            additions.append(proposal);record['planner_resolution']='ADD_ACCEPTED';addition_records.append(record)
        if broad_plan['assessment']=='ABSTAIN' and (raw.any() or bp.get('deferred_reason_codes',[])):unresolved.append('BROAD_REPAIR_UNRESOLVED')
        changed=bool(additions) or reduction_plan['assessment'] in ('CANDIDATE','PARTIAL');final_assessment=('PARTIAL' if unresolved or reduction_plan['assessment'] in ('PARTIAL','ABSTAIN') else 'CANDIDATE') if changed else ('ABSTAIN' if unresolved or reduction_plan['assessment']=='ABSTAIN' else 'KEEP_SUPPORTED')
        result=joint.compile_plan(snapshot,reduction_plan,additions,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=final_assessment,unresolved=unresolved);snapshot.verify(context.source_path,context.physical_path)
        self.last_report=dict(version=VERSION,source_identity=asdict(snapshot.source),physical_identity=asdict(snapshot.physical),source_catalog=catalog,source_same_f0_refinements=[dict(event_id=e['event_id'],source_detector_hz=e.get('pitch_hz'),same_f0=e['same_f0']) for e in refined],observation_schedule=schedule,observations=observation_summaries,automatically_discovered_events=len(catalog['events']),tonal_same_f0_candidates=len(refined),manual_event_times_used=False,raw_candidate_seconds=float(np.count_nonzero(raw)*.01),supported_candidate_seconds=float(np.count_nonzero(depth)*.01),selected_reduction_strength=selected,reduction_trials=trials,reduction_assessment=broad_plan['assessment'],addition_records=addition_records,accepted_additions=len(additions),final_assessment=final_assessment,unresolved=unresolved,conflict_policy='BROAD_REDUCTION_PRIORITY;_NO_ADD_CUT_SELF_CANCELLATION',weak_fundamental_policy='LOWER_F0_ONLY_IF_COMPONENT_PRESENT_IN_ORIGINAL;_NO_BLIND_DIVISION',old_note_sub_called=False,sub_synthesis='SAME_FUNDAMENTAL_ONLY_CONNECTED',output_pcm_uses_stems=False,observer_provider=oid['provider'],observer_identity=oid,calibration_scope='WEAK_TRACK_ROLE_MIXTURE_ENVELOPE',subjective_quality='NOT_EVALUATED',planner_sha256=result['sha256'])
        return result
