"""Automatic peak policy for OPPO v3.4.

Order remains fixed: gain-only -> optimized OPPO -> conventional limiter only
when OPPO explicitly raises NotFeasible. Operational/integrity errors never
trigger limiter fallback.
"""
from __future__ import annotations
from pathlib import Path
import math
import offline_peak_stream_v34 as oppo
import offline_peak_lab as kernel
import distribution_peak as limiter
import note_sub_lab as io

VERSION='auto-peak-v3.4.0'
MAX_SECONDS=oppo.MAX_SECONDS
verify_kernel=oppo.verify_kernel
validate_source=oppo.validate_source
scaled_file=oppo.scaled_file
measure=oppo.measure
quality_report=oppo.quality_report
_shape=oppo._shape

def _verify(path,source,target,ceiling,progress=None):
    m=measure(path,progress,'AUTO_PEAK_QC');info=validate_source(source,kernel.Config())
    if (m['lufs_i'] is None or abs(m['lufs_i']-target)>.03 or m['true_peak_max_dbtp_estimate']>ceiling or
        (m['frames'],m['samplerate'],m['channels'])!=(info.frames,info.samplerate,info.channels)):
        raise RuntimeError('AUTO peak output failed LUFS/TP/shape verification')
    return m

def fit(source,dest,work,target,ceiling,*,progress=None,chunk_seconds=2.0,interrupt_after=None,**kwargs):
    source,dest,work=Path(source),Path(dest),Path(work);work.mkdir(parents=True,exist_ok=True)
    if not math.isfinite(target) or not -30<=target<=-8 or not math.isfinite(ceiling) or not -12<=ceiling<=-1:
        raise ValueError('Invalid automatic peak targets')
    before=io.file_hash(source)
    identity=dict(version=VERSION,source_sha256=before,code_sha256=io.file_hash(__file__),
        oppo_code=io.file_hash(oppo.__file__),limiter_code=io.file_hash(limiter.__file__),
        target=float(target),ceiling=float(ceiling),chunk_seconds=float(chunk_seconds))
    marker=dest.with_suffix('.auto.json')
    if dest.exists() and marker.exists():
        saved=io.read_json(marker)
        if saved.get('identity')==identity and saved.get('sha256')==io.file_hash(dest):
            metrics=_verify(dest,source,target,ceiling,progress)
            return dict(saved['report'],output_metrics=metrics,output_lufs=metrics['lufs_i'],
                output_tp=metrics['true_peak_max_dbtp_estimate'],rerun_status='IDEMPOTENT_SKIP')
        raise RuntimeError('Unknown/modified AUTO peak output; nothing overwritten')
    if dest.exists():raise RuntimeError('AUTO peak destination exists without its receipt; nothing overwritten')
    try:
        report=oppo.fit(source,dest,work/'oppo',target,ceiling,progress=progress,
            chunk_seconds=chunk_seconds,interrupt_after=interrupt_after)
        route='GAIN_ONLY' if not report.get('optimizer_used') else 'OPPO'
        report=dict(report,auto_route=route,automatic_policy='GAIN_ONLY -> OPPO -> LIMITER_IF_OPPO_NOT_FEASIBLE',
            conventional_limiter_used=False,limiter_fallback_reason=None)
    except kernel.NotFeasible as exc:
        if dest.exists():raise RuntimeError('OPPO refusal unexpectedly left a destination; fallback aborted') from exc
        ff=io.ffmpeg_path()
        if not ff:raise RuntimeError('FFmpeg unavailable for safety fallback') from exc
        limiter.check_ffmpeg(ff)
        if progress:progress.set('LIMITER_FALLBACK',0,1)
        lim=limiter.fit(source,dest,work/'limiter',target,ceiling,ff,progress)
        metrics=_verify(dest,source,target,ceiling,progress)
        report=dict(status='LIMITER_FALLBACK',output_lufs=metrics['lufs_i'],output_tp=metrics['true_peak_max_dbtp_estimate'],
            output_metrics=metrics,optimizer_used=False,conventional_limiter_used=bool(lim.get('limiter_engaged')),
            auto_route='LIMITER_FALLBACK',limiter_fallback_reason=str(exc),limiter_report=lim,source_unchanged=True,
            automatic_policy='GAIN_ONLY -> OPPO -> LIMITER_IF_OPPO_NOT_FEASIBLE')
    if io.file_hash(source)!=before:raise RuntimeError('Source changed during automatic peak processing')
    metrics=_verify(dest,source,target,ceiling,progress)
    report['output_metrics']=metrics;report['output_lufs']=metrics['lufs_i'];report['output_tp']=metrics['true_peak_max_dbtp_estimate']
    io.atomic_json(marker,dict(identity=identity,sha256=io.file_hash(dest),report=report));return report
