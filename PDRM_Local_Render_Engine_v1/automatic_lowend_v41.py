"""Source-driven low-end repair planner for the v40 integration API.

Scope: automatic broad low-cut proposals, source-clock observation scheduling,
verified role evidence, physical-snapshot measurement, bounded rendered choice.
No handwritten event times. No sub addition or narrow-cut substitution. Positive
track-role references remain weak mixture examples, NOT local taste labels.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import math
import importlib.metadata
import numpy as np
from scipy.ndimage import distance_transform_edt
import auto_peak_v34 as auto
import lowend_boundary_lab as boundary
import context_occupancy_lab as occupancy
import lowend_coordinator_v40 as common
import source_events_v41 as events
from integration_contract_v40 import capture, digest, valid_hash

VERSION='automatic-lowend-lab-0.1.0'
BANDS=('low','lowmid')


def make_calibration(reference_specs,progress=None):
    """Only explicit role-positive examples; preserve weak/global label scope."""
    if len(reference_specs)<4:raise ValueError('At least four independent references required')
    fs=[];ids=[];pcms=[];labels=[]
    for spec in reference_specs:
        if spec.get('role')!='bass' or spec.get('quality')!='positive':
            raise ValueError('Only explicit bass-positive references for this weak boundary')
        identity=capture(spec['path'])
        if identity.pcm_sha256 in pcms:raise ValueError('Repeated decoded reference is not an independent group')
        m=auto.measure(spec['path'],progress,'REFERENCE_MEASURE')
        if m['lufs_i'] is None:raise ValueError('Reference has no finite loudness')
        fs.append(events.extract_features(spec['path'],anchor_gain_db=-14-m['lufs_i'],progress=progress))
        ids.append(identity.file_sha256);pcms.append(identity.pcm_sha256)
        labels.append(dict(role='bass',quality='positive',scope='weak_track_role'))
    bundle=dict(schema=1,version=VERSION,extractor=events.VERSION,
        broad=boundary.calibrate(fs,ids),context=occupancy.calibrate(fs,ids),
        source_groups=ids,pcm_groups=pcms,labels=labels,
        target='empirical_low_occupancy_and_hit_envelope',subjective_certification=False)
    bundle['sha256']=digest(bundle);return bundle


def validate_calibration(bundle):
    p=dict(bundle);h=p.pop('sha256',None)
    if h!=digest(p) or bundle.get('version')!=VERSION or bundle.get('schema')!=1 or bundle.get('extractor')!=events.VERSION:
        raise ValueError('Calibration checksum/version mismatch')
    ids=bundle['source_groups'];pcms=bundle['pcm_groups']
    if len(ids)<4 or len(ids)!=len(set(ids)) or len(pcms)!=len(ids) or len(set(pcms))!=len(pcms) or not all(valid_hash(v) for v in ids+pcms):
        raise ValueError('Invalid independent reference identity')
    if bundle['labels']!=[dict(role='bass',quality='positive',scope='weak_track_role') for _ in ids]:
        raise ValueError('Weak labels cannot be promoted or substituted')
    for k in ('broad','context'):
        if bundle[k]['config']!=asdict(boundary.Config()) or bundle[k]['reference_ids']!=ids:
            raise ValueError('Calibration component configuration/group mismatch')
    if not all(math.isfinite(v) for v in bundle['broad']['caps'].values()) or not math.isfinite(bundle['context']['floor_cap_db']):
        raise ValueError('Nonfinite reference boundary')
    return bundle


class ResearchDemucsObserver:
    """Opt-in research adapter. No network access and no weights in product."""
    def __init__(self,checkpoint,*,research_use=False,threads=2):
        self.checkpoint=Path(checkpoint);self.research_use=research_use;self.threads=threads;self.model=None
    def identity(self):
        from stem_observer_lab import CHECKPOINT_SHA256
        return dict(provider='verified_hdemucs41',checkpoint_sha256=CHECKPOINT_SHA256,
                    research_only=True,evidence_scope='research_observer',
                    versions={k:importlib.metadata.version(k) for k in ('torch','torchaudio')},
                    preprocessing_sha256=digest({n:events.capture.__module__ if n=='contract' else
                        __import__('integration_contract_v40').file_hash(Path(__file__).with_name(n))
                        for n in ('role_observer_v38.py','role_observer_v37.py','stem_observer_lab.py')}))
    def preflight(self):
        from stem_observer_lab import Observer,CHECKPOINT_SHA256,sha
        if self.research_use is not True:raise RuntimeError('Research checkpoint not approved for distribution mastering')
        if not self.checkpoint.is_file() or sha(self.checkpoint)!=CHECKPOINT_SHA256:raise ValueError('Research checkpoint missing or changed')
        if type(self.threads) is not int or not 1<=self.threads<=8:raise ValueError('Invalid CPU worker count')
        if self.model is None:self.model=Observer(self.checkpoint,self.threads)
    def observe(self,source,start,end,progress=None):
        self.preflight()
        if progress:progress.set('ROLE_OBSERVER_INFERENCE',0,1)
        from role_observer_v38 import observe_bandwise
        arrays,meta=observe_bandwise(self.model,source,start,end)
        meta=dict(meta,provider='verified_hdemucs41')
        return arrays,meta


def verify_observation(arrays,meta,source_id,window,provider_id,*,allow_fixture=False):
    """Validate evidence BEFORE testing whether a correction is needed."""
    if meta.get('source_sha256')!=source_id.file_sha256 or meta.get('source_frames')!=source_id.frames or meta.get('source_samplerate')!=source_id.samplerate:
        raise ValueError('Observation source mismatch')
    if meta.get('source_order')!=['mix','drums','bass','other','vocals']:raise ValueError('Wrong source order')
    provider=meta.get('provider')
    if provider!=provider_id.get('provider'):raise ValueError('Wrong observer provider')
    if provider=='synthetic_roles41':
        if not allow_fixture:raise ValueError('Synthetic roles prohibited outside explicit test')
    elif provider=='verified_hdemucs41':
        from stem_observer_lab import CHECKPOINT_SHA256
        if meta.get('model_sha256')!=CHECKPOINT_SHA256 or meta.get('version')!='role-observer-0.3.0':
            raise ValueError('Wrong model/preprocessing')
    else:raise ValueError('Unsupported observer provider')
    rate=source_id.samplerate;start=window['core_start_frame']/rate;end=window['core_stop_frame']/rate
    if abs(meta['start_seconds']-start)>1/rate or abs(meta['end_seconds']-end)>1/rate:raise ValueError('Wrong observed interval')
    t=np.asarray(arrays['time']);p=np.asarray(arrays['low_power'])
    if len(t)<2 or p.shape!=(2,len(t),5) or not np.isfinite(p).all() or np.any(p<0):raise ValueError('Invalid role powers')
    if not np.isfinite(t).all() or not np.allclose(np.diff(t),.01,atol=1e-8) or abs(t[0]-start)>.011 or abs(t[-1]+.01-end)>.011:
        raise ValueError('Observer clock/grid mismatch')
    shares=p[:,:,1:]/np.maximum(p[:,:,1:].sum(axis=2,keepdims=True),1e-24)
    grouped=shares[:,:,0]+shares[:,:,1]
    disagreement=np.sum(abs(shares[0]-shares[1]),axis=1)/2
    instrument_power=(p[:,:,1]+p[:,:,2]).min(axis=0)
    ok=(grouped.min(axis=0)>=.75)&(shares[:,:,3].max(axis=0)<=.15)&(disagreement<=.25)
    ok&=(p[:,:,0].min(axis=0)>1e-12)&(instrument_power>=.05*p[:,:,0].min(axis=0))
    ok&=(t>=start+.4)&(t<=end-.4)
    return t,ok,dict(provider=provider,frames=len(t),supported_frames=int(ok.sum()),
        supported_fraction=float(ok.mean()),probabilities_calibrated=False,
        observation_scope='Estimated bass+drums low-band group; not exact mixture-source power',
        neural_inference=provider=='verified_hdemucs41')


class AutomaticRepairPlanner:
    """A real source-driven planner; all entry points stay explicitly LAB-only."""
    def __init__(self,calibration,observer,*,allow_fixture=False):
        self.bundle=json.loads(json.dumps(calibration,allow_nan=False));self.observer=observer
        self.allow_fixture=allow_fixture;self.last_report=None
    def identity(self):
        from integration_contract_v40 import file_hash
        return dict(planner_id=VERSION,calibration_sha256=self.bundle['sha256'],
            evidence_scope=self.observer.identity()['evidence_scope'],observer=self.observer.identity(),
            code={n:file_hash(Path(__file__).with_name(n)) for n in
                  ('automatic_lowend_v41.py','source_events_v41.py','context_occupancy_lab.py','lowend_boundary_lab.py')})
    def preflight(self):
        validate_calibration(self.bundle)
        identity=self.observer.identity()
        if identity.get('provider')=='synthetic_roles41' and self.allow_fixture is not True:
            raise ValueError('Test roles cannot be used silently')
        if identity.get('provider') not in ('synthetic_roles41','verified_hdemucs41'):raise ValueError('Unknown observer')
        self.observer.preflight()
    def build(self,context,progress=None):
        self.preflight();snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path)
        source_features,catalog=events.analyze_source(context.source_path,progress)
        met=auto.measure(context.physical_path,progress,'PLANNER_PHYSICAL_MEASURE')
        if met['lufs_i'] is None:raise ValueError('Physical source silent')
        physical=events.extract_features(context.physical_path,anchor_gain_db=-14-met['lufs_i'],progress=progress)
        # Measurement uses the *actual* prepared mix. Original analysis never
        # masquerades as prepared samples by substituting a hash or one gain.
        bp=boundary.plan(physical,self.bundle['broad']);cp=occupancy.plan(physical,self.bundle['context'])
        times=np.asarray(physical['time']);raw=np.maximum(bp['low_cut_db'],cp['low_cut_db'])
        sr=snapshot.source.samplerate;n=snapshot.source.frames;clock=snapshot.clock
        render_positions=times*snapshot.physical.samplerate
        delay=clock.delay_numerator/clock.delay_denominator
        source_time=(render_positions-delay)/snapshot.physical.samplerate
        spans=events.ranges_from_depth(source_time,raw,sr,n)
        schedule=events.schedule(spans,rate=sr,length=n)
        permission=np.zeros(len(times),bool);observations=[]
        for index,w in enumerate(schedule['windows']):
            if progress:progress.set('ROLE_OBSERVER_WINDOW',index,len(schedule['windows']))
            arrays,meta=self.observer.observe(context.source_path,w['core_start_frame']/sr,w['core_stop_frame']/sr,progress)
            ot,valid,summary=verify_observation(arrays,meta,snapshot.source,w,self.observer.identity(),allow_fixture=self.allow_fixture)
            permission|=np.interp(source_time,ot,valid.astype(float),left=0,right=0)>.999
            observations.append(dict(window=w,**summary))
        # Never smooth a control across a region with missing permission.
        distance=distance_transform_edt(np.r_[False,permission,False])[1:-1]*.01
        depth=raw*np.clip(distance/.08,0,1)
        proposals=self._proposals(source_time,depth,snapshot)
        deferred=bp.get('deferred_reason_codes',[])
        assessment='CANDIDATE' if proposals else ('ABSTAIN' if raw.any() or deferred else 'KEEP_SUPPORTED')
        pid=self.identity()
        def compile_with(items,state):
            return common.compile_plan(snapshot,items,planner_id=pid['planner_id'],
                calibration_sha256=pid['calibration_sha256'],evidence_scope=pid['evidence_scope'],assessment=state)
        trials=[];selected=0.;best=None
        def error(f):
            sig=boundary.signature(f);errors=[]
            if 'EXCESS_HIT_LEVEL' in bp['reason_codes']:errors.append(max(0.,sig['hit_q90_db']-self.bundle['broad']['caps']['hit_q90_db']))
            if 'EXCESS_LOW_FLOOR' in bp['reason_codes']:errors.append(max(0.,sig['low_floor_q20_db']-self.bundle['broad']['caps']['low_floor_q20_db']))
            if cp['selected_windows']:errors.append(occupancy.score(f,cp))
            return float(sum(errors))
        initial_error=error(physical)
        if proposals:
            # Finite candidates always read the same physical snapshot. These
            # provisional error goals are engineering boundaries, not preference.
            with TemporaryDirectory(prefix='plan41_',dir=context.physical_path.parent) as tmp:
                for strength in (.5,1.):
                    scaled=[common.CutProposal(p.proposal_id,p.branch,p.source_frames,
                        tuple(float(d*strength) for d in p.depth_db),p.reason) for p in proposals]
                    candidate_plan=compile_with(scaled,'CANDIDATE');dest=Path(tmp)/f'candidate_{strength}.wav'
                    common.render(context.source_path,context.physical_path,dest,snapshot,candidate_plan,progress=progress)
                    qm=auto.measure(dest,progress,'LOWEND_CANDIDATE_MEASURE')
                    ff=events.extract_features(dest,anchor_gain_db=-14-qm['lufs_i'],progress=progress)
                    e=error(ff);improved=e<initial_error-.05
                    trials.append(dict(strength=strength,initial_error_db=initial_error,remaining_error_db=e,improved=improved))
                    if improved and (best is None or e<best[0]):best=(e,scaled,strength)
                    if improved and e<=.25:break
                if best:
                    proposals=best[1];selected=best[2];assessment='CANDIDATE' if best[0]<=.25 else 'PARTIAL'
                else:proposals=[];assessment='ABSTAIN'
        result=compile_with(proposals,assessment)
        snapshot.verify(context.source_path,context.physical_path)
        self.last_report=dict(version=VERSION,source_identity=asdict(snapshot.source),physical_identity=asdict(snapshot.physical),
            source_catalog=catalog,observation_schedule=schedule,observations=observations,
            automatically_discovered_events=len(catalog['events']),manual_event_times_used=False,
            raw_candidate_seconds=float(np.count_nonzero(raw)*.01),supported_candidate_seconds=float(np.count_nonzero(depth)*.01),
            selected_strength=selected,trials=trials,assessment=assessment,
            deferred_reason_codes=deferred,old_note_sub_called=False,sub_synthesis='NOT_CONNECTED',
            narrow_component_correction='NOT_SUBSTITUTED_WITH_BROAD_CUT',
            calibration_scope='WEAK_TRACK_ROLE_MIXTURE_ENVELOPE',subjective_quality='NOT_EVALUATED',
            output_pcm_uses_stems=False,planner_sha256=result['sha256'])
        return result
    @staticmethod
    def _proposals(time,depth,snapshot):
        # Complete source-clock curve, with explicit zero outside support.
        sr=snapshot.source.samplerate;n=snapshot.source.frames
        nodes={0:0.,n:0.}
        for t,d in zip(time,depth):
            frame=round(float(t)*sr)
            if 0<frame<n:nodes[frame]=max(nodes.get(frame,0.),float(d))
        xs=tuple(sorted(nodes));ys=tuple(nodes[k] for k in xs)
        if not any(ys):return []
        return [common.CutProposal('auto-low-repair','low',xs,ys,'OBSERVED_PHYSICAL_HIT_OR_CONTEXT_EXCESS')]
