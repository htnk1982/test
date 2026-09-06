"""Gain-only input conditioning with a separate -14 LUFS analysis reference.

Reuse the adopted Note-Sub observations/targets/amounts/phase functions. The
reference is floating point and may exceed 0 dBFS for ANALYSIS only. Amplitudes
are mapped back to a safe physical rendering level; no limiter is called.
"""
from __future__ import annotations
from collections import Counter
from copy import deepcopy
from pathlib import Path
import os
import shutil
import accepted_finish as legacy
import note_sub_lab as io
import note_sub_lab_v02 as ns
import offline_peak_stream as stream

VERSION='note-sub-conditioned-1.0.0'
REFERENCE_LUFS=-14.0
INPUT_TP=-2.5


def run(source, work, progress=None, *, interrupt_after=None):
    source,work=Path(source),Path(work);work.mkdir(parents=True,exist_ok=True)
    identity=dict(source=io.file_hash(source),version=VERSION,code=io.file_hash(__file__),
                  frozen=legacy.verify_dsp(),target=REFERENCE_LUFS,prep_tp=INPUT_TP)
    job=work/('condition_'+io.obj_hash(identity)[:20]);job.mkdir(exist_ok=True)
    result=job/'NOTE_CONDITIONED.wav';marker=job/'COMPLETE.json'
    with legacy._RUNTIME_LOCK,io.job_lock(job/'job.lock'):
        if result.exists() and marker.exists():
            saved=io.read_json(marker)
            if saved.get('identity')==identity and saved.get('sha256')==io.file_hash(result):
                return result,dict(saved['report'],rerun_status='IDEMPOTENT_SKIP')
            raise RuntimeError('Modified conditioned output; nothing overwritten')
        baseline=stream.measure(source,progress,'PREP_INPUT')
        if baseline['lufs_i'] is None:raise ValueError('Silent source')
        target=min(REFERENCE_LUFS,baseline['lufs_i']+INPUT_TP-baseline['true_peak_max_dbtp_estimate'])
        safe=stream.scaled_file(source,job/'SAFE_GAIN.wav',target-baseline['lufs_i'],progress)
        safe_qc=stream.measure(safe,progress,'SAFE_GAIN_QC')
        if safe_qc['true_peak_max_dbtp_estimate']>INPUT_TP+1e-8 or abs(safe_qc['lufs_i']-target)>.01:
            raise RuntimeError('Gain-only preparation verification failed')
        analysis_gain=REFERENCE_LUFS-safe_qc['lufs_i']
        anchor=stream.scaled_file(safe,job/'ANALYSIS_REFERENCE.wav',analysis_gain,progress)
        (job/'analysis').mkdir(exist_ok=True)
        rows,cache=ns.collect_frames(anchor,job,progress or io.Progress())
        anchored_events,rejected=ns.make_events(rows,anchor)
        reasons=dict(Counter(r['reason'] for r in rows));del rows
        events=deepcopy(anchored_events)
        amplitude_scale=10**(-analysis_gain/20)
        for event in events:
            event['amplitudes']=[a*amplitude_scale for a in event['amplitudes']]
        io.atomic_json(job/'EVENTS.json',dict(analysis_events=anchored_events,render_events=events,
            analysis_to_render_gain=amplitude_scale,rejected=rejected))
        if interrupt_after=='analysis':raise InterruptedError('TEST_CONDITIONED_AFTER_ANALYSIS')
        delta,dcache=ns.render(safe,job,events,progress or io.Progress(),1.,label='delta')
        dm=io.measure(delta,progress,'NOTE_LAYER_QC')
        chosen=None;selected_scale=0.;choices=[]
        if events:
            if (dm['above_110_energy_db'] is None or dm['above_110_energy_db']>ns.CONFIG['leakage_above_110_limit_db'] or
                dm['below_20_energy_db']>ns.CONFIG['layer_below_20_limit_db']):
                raise RuntimeError('Note-Sub layer frequency leakage gate failed')
            for i,scale in enumerate(ns.CONFIG['scales']):
                raw,_=ns.render(safe,job,events,progress or io.Progress(),scale,label=f'raw_{i}')
                met=stream.measure(raw,progress,'NOTE_RAW_QC')
                match=target-met['lufs_i']
                allowed=(abs(match)<=ns.CONFIG['max_matching_gain_change_db'] and
                    met['true_peak_max_dbtp_estimate']+match<=ns.CONFIG['pcm_tp_ceiling'])
                choices.append(dict(scale=scale,gain_db=match,allowed=allowed))
                if not allowed:continue
                p=stream.scaled_file(raw,job/f'MATCHED_{i}.wav',match,progress)
                cm=stream.measure(p,progress,'NOTE_MATCHED_QC')
                if abs(cm['lufs_i']-target)>.05 or cm['true_peak_max_dbtp_estimate']>ns.CONFIG['pcm_tp_ceiling']:
                    choices[-1]['allowed']=False;continue
                chosen=p;selected_scale=scale;break
        candidate=chosen or safe
        if io.file_hash(source)!=identity['source']:raise RuntimeError('Source changed')
        report=dict(version=VERSION,prep_limiter_used=False,physical_target_lufs=target,
            preparation_gain_db=target-baseline['lufs_i'],analysis_gain_db=analysis_gain,
            analysis_anchor_lufs=REFERENCE_LUFS,analysis_to_render_gain=amplitude_scale,
            baseline_metrics=baseline,prepared_metrics=safe_qc,
            status='ADDITION_RENDERED' if chosen else ('NO_ELIGIBLE_ADDITION' if not events else 'NO_ADDITION_WITHIN_GATES'),
            selected_scale=selected_scale,selected_events=len(events) if chosen else 0,
            selected_seconds=sum(e['end']-e['start'] for e in events) if chosen else 0.,
            choices=choices,reasons=reasons,analysis_cache=cache,delta_cache=dcache,
            source_unchanged=True,output_metrics=stream.measure(candidate,progress,'NOTE_FINAL'))
        tmp=job/'NOTE_CONDITIONED.partial.wav';shutil.copyfile(candidate,tmp);io.sync_owned_file(tmp)
        os.replace(tmp,result)
        io.atomic_json(marker,dict(identity=identity,sha256=io.file_hash(result),report=report))
        return result,report
