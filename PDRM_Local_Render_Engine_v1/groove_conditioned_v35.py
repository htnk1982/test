"""PDRM v3.5 lab: groove-first low-end conditioning with conservative observer."""
from __future__ import annotations
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
import os,shutil
import accepted_finish as legacy
import note_sub_lab as io
import note_sub_lab_v02 as ns
import offline_peak_stream_v34 as stream
import auto_peak_v34 as auto
import groove_lowend_lab as groove

VERSION='groove-conditioned-3.5-lab-0.1'
REFERENCE_LUFS=-14.0
INPUT_TP=-2.5
_SEMANTIC_SOURCE=None

@contextmanager
def semantic_source(path):
    global _SEMANTIC_SOURCE
    old=_SEMANTIC_SOURCE;_SEMANTIC_SOURCE=Path(path).resolve()
    try:yield
    finally:_SEMANTIC_SOURCE=old

def run(source,work,progress=None,*,interrupt_after=None):
    source,work=Path(source),Path(work);work.mkdir(parents=True,exist_ok=True)
    semantic=Path(_SEMANTIC_SOURCE).resolve() if _SEMANTIC_SOURCE is not None else source.resolve()
    identity=dict(source=io.file_hash(source),semantic_source=io.file_hash(semantic),version=VERSION,
        code=io.file_hash(__file__),groove_code=io.file_hash(groove.__file__),auto_code=io.file_hash(auto.__file__),
        frozen=legacy.verify_dsp(),target=REFERENCE_LUFS,prep_tp=INPUT_TP,groove_config=groove.asdict(groove.Config()))
    job=work/('groove_'+io.obj_hash(identity)[:20]);job.mkdir(exist_ok=True)
    result=job/'GROOVE_CONDITIONED.wav';marker=job/'COMPLETE.json'
    with legacy._RUNTIME_LOCK,io.job_lock(job/'job.lock'):
        if result.exists() and marker.exists():
            saved=io.read_json(marker)
            if saved.get('identity')==identity and saved.get('sha256')==io.file_hash(result):
                return result,dict(saved['report'],rerun_status='IDEMPOTENT_SKIP')
            raise RuntimeError('Modified groove-conditioned output; nothing overwritten')
        baseline=stream.measure(source,progress,'PREP_INPUT')
        if baseline['lufs_i'] is None:raise ValueError('Silent source')
        anchor=stream.scaled_file(source,job/'ANALYSIS_REFERENCE.wav',REFERENCE_LUFS-baseline['lufs_i'],progress)
        physical=job/'PHYSICAL_PREP.wav';prep=auto.fit(source,physical,job/'auto_prepare',REFERENCE_LUFS,INPUT_TP,progress=progress)
        pq=stream.measure(physical,progress,'PREP_PHYSICAL_QC')
        if abs(pq['lufs_i']-REFERENCE_LUFS)>.03 or pq['true_peak_max_dbtp_estimate']>INPUT_TP:
            raise RuntimeError('Automatic physical preparation verification failed')

        features=groove.analyze_mix(physical);trim_plan=groove.plan_trim(features)
        trimmed=job/'LOWEND_TRIMMED.wav';groove.render_trim(physical,trimmed,trim_plan,progress=progress)
        tm=stream.measure(trimmed,progress,'GROOVE_TRIM_QC')
        if tm['lufs_i'] is None or tm['true_peak_max_dbtp_estimate']>INPUT_TP+.05:
            raise RuntimeError('Groove trim QC failed')

        observer=groove.analyze_proxy_observer(semantic)
        (job/'analysis').mkdir(exist_ok=True)
        rows,cache=ns.collect_frames(anchor,job,progress or io.Progress())
        raw_events,rejected=ns.make_events(rows,anchor);reasons=dict(Counter(r['reason'] for r in rows));del rows
        events,decisions=groove.gate_and_shape_events(raw_events,trimmed,observer)
        amplitude_scale=10**((pq['lufs_i']-REFERENCE_LUFS)/20)
        for event in events:event['amplitudes']=[a*amplitude_scale for a in event['amplitudes']]
        io.atomic_json(job/'GROOVE_EVENTS.json',dict(raw_events=raw_events,render_events=events,decisions=decisions,
            observer=dict(mode=observer['mode'],claim=observer['claim']),trim_plan={k:v for k,v in trim_plan.items() if k not in ('times','depth_db')},
            rejected=rejected,prep_route=prep['auto_route']))
        if interrupt_after=='analysis':raise InterruptedError('TEST_GROOVE_AFTER_ANALYSIS')

        chosen=trimmed;selected_scale=0.;dcache={};deep_before=groove.band_rms_db(trimmed,groove.Config().deep_lo_hz,groove.Config().deep_hi_hz)
        add_report=dict(global_deep_delta_db=0.,budget_db=groove.Config().global_deep_rms_budget_db)
        if events:
            delta,dcache=ns.render(trimmed,job,events,progress or io.Progress(),1.,label='delta')
            dm=io.measure(delta,progress,'GROOVE_SUB_LAYER_QC')
            if (dm['above_110_energy_db'] is None or dm['above_110_energy_db']>ns.CONFIG['leakage_above_110_limit_db'] or
                dm['below_20_energy_db']>ns.CONFIG['layer_below_20_limit_db']):
                raise RuntimeError('Groove sub layer frequency leakage gate failed')
            for scale in (1.0,.5,.25):
                raw,_=ns.render(trimmed,job,events,progress or io.Progress(),scale,label='groove_raw_'+str(scale).replace('.','_'))
                deep_after=groove.band_rms_db(raw,groove.Config().deep_lo_hz,groove.Config().deep_hi_hz)
                delta_db=deep_after-deep_before
                if delta_db>groove.Config().global_deep_rms_budget_db+1e-6:continue
                met=stream.measure(raw,progress,'GROOVE_RAW_QC');match=REFERENCE_LUFS-met['lufs_i']
                if abs(match)>ns.CONFIG['max_matching_gain_change_db'] or met['true_peak_max_dbtp_estimate']+match>ns.CONFIG['pcm_tp_ceiling']:continue
                p=stream.scaled_file(raw,job/'GROOVE_MATCHED.wav',match,progress);cm=stream.measure(p,progress,'GROOVE_MATCHED_QC')
                if abs(cm['lufs_i']-REFERENCE_LUFS)>.05 or cm['true_peak_max_dbtp_estimate']>ns.CONFIG['pcm_tp_ceiling']:continue
                chosen=p;selected_scale=scale;add_report=dict(global_deep_delta_db=delta_db,budget_db=groove.Config().global_deep_rms_budget_db);break

        if io.file_hash(source)!=identity['source'] or io.file_hash(semantic)!=identity['semantic_source']:raise RuntimeError('Source changed')
        report=dict(version=VERSION,prep_route=prep['auto_route'],prep_oppo_used=prep['auto_route']=='OPPO',
            prep_limiter_used=bool(prep.get('conventional_limiter_used')),preparation_auto_report=prep,
            physical_target_lufs=REFERENCE_LUFS,analysis_anchor_lufs=REFERENCE_LUFS,baseline_metrics=baseline,prepared_metrics=pq,
            status='GROOVE_LOWEND_RENDERED',observer_mode=observer['mode'],trim_max_db=trim_plan['max_trim_db'],
            trim_mean_db=trim_plan['mean_trim_db'],trim_active_fraction=trim_plan['active_fraction'],
            raw_note_events=len(raw_events),selected_events=len(events) if selected_scale else 0,selected_scale=selected_scale,
            selected_seconds=sum(e['end']-e['start'] for e in events) if selected_scale else 0.,event_decisions=decisions,
            addition=add_report,reasons=reasons,analysis_cache=cache,delta_cache=dcache,source_unchanged=True,
            output_metrics=stream.measure(chosen,progress,'GROOVE_FINAL_QC'))
        tmp=job/'GROOVE_CONDITIONED.partial.wav';shutil.copyfile(chosen,tmp);io.sync_owned_file(tmp);os.replace(tmp,result)
        io.atomic_json(marker,dict(identity=identity,sha256=io.file_hash(result),report=report));return result,report
