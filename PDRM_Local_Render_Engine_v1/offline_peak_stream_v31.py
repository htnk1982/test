"""OPPO v3.1 whole-track wrapper.

The listening-selected v0.1 kernel remains first choice for every frame. Only
frames rejected specifically because the old 1 ms-RMS pointwise allowance is
insufficient are routed to `offline_peak_rescue`. All existing whole-track QA,
LUFS/TP verification, restartability and no-limiter/no-fallback behavior remain.
"""
from __future__ import annotations
import importlib.metadata, math, os, shutil
from dataclasses import asdict
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal
import offline_peak_lab as kernel
import offline_peak_stream as base
import offline_peak_rescue as rescue
import note_sub_lab as io

VERSION='offline-peak-stream-0.3.0'
MAX_SECONDS=base.MAX_SECONDS
verify_kernel=base.verify_kernel
validate_source=base.validate_source
read_padded=base.read_padded
scaled_file=base.scaled_file
measure=base.measure
quality_report=base.quality_report
_shape=base._shape


def render_fixed_gain(source, work, gain_db, ceiling, cfg=kernel.Config(), *,
                      rescue_cfg=rescue.RescueConfig(), chunk_seconds=2.0,
                      progress=None, interrupt_after=None):
    info=validate_source(source,cfg);rescue_cfg.validate(info.samplerate*cfg.oversample)
    if not math.isfinite(gain_db) or not math.isfinite(ceiling) or ceiling<=0:
        raise ValueError('Invalid gain or peak ceiling')
    if not math.isfinite(chunk_seconds) or not .05<=chunk_seconds<=8:
        raise ValueError('I/O chunk duration must be 0.05 to 8 seconds')
    source,work=Path(source),Path(work)
    n=max(128,round(cfg.frame_ms*info.samplerate/1000));n+=n%2
    hop=n//2;q=cfg.oversample;length=info.frames;gain=10**(gain_db/20)
    width=max(hop,round(chunk_seconds*info.samplerate/hop)*hop)
    identity=dict(source=io.file_hash(source),kernel=verify_kernel(),version=VERSION,
        code=io.file_hash(__file__),rescue_code=io.file_hash(rescue.__file__),
        config=asdict(cfg),rescue_config=asdict(rescue_cfg),gain_db=gain_db,
        ceiling=ceiling,width=width,
        versions={p:importlib.metadata.version(p) for p in ('numpy','scipy','soundfile')})
    directory=work/('pass_'+io.obj_hash(identity)[:20]);directory.mkdir(parents=True,exist_ok=True)
    win=signal.windows.hann(n,sym=False)
    paths=[];computed=reused=active=total_iters=rescue_frames=0;max_pg=max_fraction=0.
    with sf.SoundFile(source) as f:
        for i,a in enumerate(range(0,length,width)):
            b=min(length,a+width);path=directory/f'{i:06d}.wav';mark=path.with_suffix('.json')
            context=dict(identity=identity,start=a,end=b);saved=None
            if io.valid_audio_cache(path,mark):
                record=io.read_json(mark)
                if record.get('context')==context:saved=record
            if saved is not None:
                reused+=1;stat=saved['stats']
            else:
                first=max(-n,((a-n)//hop+1)*hop)
                last=min((length//hop)*hop,((b-1)//hop)*hop)
                left=max(-n,first-64);right=min(length+n,last+n+64)
                buf=read_padded(f,left,right,gain)
                accum=np.zeros((b-a,2));den=np.zeros(b-a)
                stat=dict(active_frames=0,total_iterations=0,max_projected_gradient=0.,frames=0,
                          rescue_frames=0,max_rescue_required_fraction=0.)
                for s in range(first,last+1,hop):
                    l,rr=max(-n,s-64),min(length+n,s+n+64)
                    native=buf[s-left:s+n-left]
                    up=signal.resample_poly(buf[l-left:rr-left],q,1,axis=0,
                        window=('kaiser',10.5))[(s-l)*q:(s+n-l)*q]
                    locked=np.zeros_like(up,dtype=bool);locked[::q]=native==0
                    try:
                        y,result=kernel.solve_block(up,info.samplerate*q,ceiling,cfg,locked)
                        result=dict(result,rescue=False)
                    except kernel.NotFeasible as exc:
                        if str(exc)!='Residual budget cannot fit this peak':
                            raise kernel.NotFeasible(
                                f'{exc}; window {max(0,s)/info.samplerate:.3f}s to '
                                f'{min(length,s+n)/info.samplerate:.3f}s. No limiter fallback.') from exc
                        try:
                            y,result=rescue.solve_block(up,info.samplerate*q,ceiling,cfg,locked,rescue_cfg)
                        except kernel.NotFeasible as rex:
                            raise kernel.NotFeasible(
                                f'{rex}; rescue after old pointwise-budget failure; window '
                                f'{max(0,s)/info.samplerate:.3f}s to '
                                f'{min(length,s+n)/info.samplerate:.3f}s. No limiter fallback.') from rex
                    d=(y-up)[::q]
                    lo,hi=max(a,s),min(b,s+n);sl=slice(lo-s,hi-s);dst=slice(lo-a,hi-a)
                    accum[dst]+=d[sl]*win[sl,None];den[dst]+=win[sl]
                    stat['active_frames']+=int(result['active']);stat['frames']+=1
                    stat['total_iterations']+=result['iterations']
                    stat['max_projected_gradient']=max(stat['max_projected_gradient'],result.get('projected_gradient',0.))
                    if result.get('rescue'):
                        stat['rescue_frames']+=1
                        stat['max_rescue_required_fraction']=max(stat['max_rescue_required_fraction'],
                            result.get('max_required_fraction',0.))
                    if progress:progress.set('OPPO_WINDOW',max(a,s),length)
                if np.any(den<=0):raise RuntimeError('Uncovered overlap-add samples')
                dry=buf[a-left:b-left];d=accum/den[:,None];d[dry==0]=0.
                io.atomic_wav(path,dry+d,info.samplerate,'DOUBLE')
                io.atomic_json(mark,dict(context=context,stats=stat,sha256=io.file_hash(path)))
                computed+=1
                if interrupt_after is not None and computed>=interrupt_after:
                    raise InterruptedError('TEST_OPPO_CHUNK_INTERRUPTION')
            active+=stat['active_frames'];total_iters+=stat['total_iterations']
            rescue_frames+=stat.get('rescue_frames',0)
            max_fraction=max(max_fraction,stat.get('max_rescue_required_fraction',0.))
            max_pg=max(max_pg,stat['max_projected_gradient']);paths.append(path)
            if progress:progress.set('OPPO_CHUNK_COMMITTED',b,length)
    output=directory/'ASSEMBLED.wav';marker=directory/'ASSEMBLED.json'
    parts={p.name:io.file_hash(p) for p in paths}
    if not (io.valid_audio_cache(output,marker) and io.read_json(marker).get('parts')==parts):
        tmp=directory/'ASSEMBLED.partial.wav'
        with sf.SoundFile(tmp,'w',samplerate=info.samplerate,channels=2,format='WAV',subtype='DOUBLE') as dst:
            for path in paths:
                with sf.SoundFile(path) as src:
                    for x in src.blocks(blocksize=65536,dtype='float64',always_2d=True):dst.write(x)
        io.sync_owned_file(tmp);os.replace(tmp,output)
        io.atomic_json(marker,dict(parts=parts,sha256=io.file_hash(output)))
    return output,dict(computed_chunks=computed,reused_chunks=reused,
        active_frame_evaluations=active,total_iterations=total_iters,max_projected_gradient=max_pg,
        rescue_frame_evaluations=rescue_frames,max_rescue_required_fraction=max_fraction,
        audio_buffer_seconds=width/info.samplerate+2*n/info.samplerate+.003,
        chunk_width_frames=width,global_frame_length=n)


def fit(source,dest,work,target,ceiling,*,cfg=kernel.Config(),rescue_cfg=rescue.RescueConfig(),
        progress=None,chunk_seconds=2.0,interrupt_after=None):
    if not math.isfinite(target) or not -30<=target<=-8 or not math.isfinite(ceiling) or not -12<=ceiling<=-1:
        raise ValueError('Invalid output targets')
    source,dest,work=Path(source).resolve(),Path(dest).resolve(),Path(work).resolve()
    if source==dest:raise ValueError('Never overwrite source')
    info=validate_source(source,cfg);kernel_hash=verify_kernel();rescue_cfg.validate(info.samplerate*cfg.oversample)
    identity=dict(source=io.file_hash(source),kernel=kernel_hash,version=VERSION,
        code=io.file_hash(__file__),rescue_code=io.file_hash(rescue.__file__),
        target=target,ceiling=ceiling,config=asdict(cfg),rescue_config=asdict(rescue_cfg),
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    job=work/('oppo_'+io.obj_hash(identity)[:20]);job.mkdir(parents=True,exist_ok=True)
    dest.parent.mkdir(parents=True,exist_ok=True);marker=dest.with_suffix('.oppo.json')
    with io.job_lock(job/'job.lock'):
        if dest.exists():
            if io.valid_audio_cache(dest,marker) and io.read_json(marker).get('identity')==identity:
                return dict(io.read_json(marker)['report'],rerun_status='IDEMPOTENT_SKIP')
            raise RuntimeError('Unknown/modified optimizer output; nothing overwritten')
        try:
            base_metrics=measure(source,progress,'OPPO_INPUT');lev=base_metrics['lufs_i']
            if lev is None:raise ValueError('Silence has no finite target')
            drive=target-lev;tp=base_metrics['true_peak_max_dbtp_estimate']
            if abs(drive)>cfg.max_drive_db:raise kernel.NotFeasible('Gain budget exceeded')
            trials=[];qa=None;gain_only=tp+drive<=ceiling-.02
            if gain_only:
                candidate=scaled_file(source,job/'GAIN_ONLY.wav',drive,progress)
            else:
                internal=ceiling-cfg.tp_margin_db;candidate=None
                for attempt in range(cfg.max_outer):
                    if abs(drive)>cfg.max_drive_db:raise kernel.NotFeasible('Gain budget exceeded')
                    raw,stats=render_fixed_gain(source,job,drive,10**(internal/20),cfg,
                        rescue_cfg=rescue_cfg,chunk_seconds=chunk_seconds,progress=progress,
                        interrupt_after=interrupt_after)
                    m=measure(raw,progress,'OPPO_FULL_TRACK_QC')
                    if m['lufs_i'] is None:raise kernel.NotFeasible('Optimizer returned silence')
                    error=target-m['lufs_i'];outtp=m['true_peak_max_dbtp_estimate']
                    trials.append(dict(attempt=attempt,drive_db=drive,internal_ceiling=internal,
                        lufs=m['lufs_i'],tp=outtp,**stats))
                    io.atomic_json(job/'SEARCH.json',dict(identity=identity,trials=trials))
                    if abs(error)<=.03 and outtp<=ceiling:
                        qa=quality_report(source,raw,drive,cfg,progress)
                        if not qa['engineering_pass']:
                            raise kernel.NotFeasible('Waveform engineering veto: '+str(qa['gates']))
                        candidate=raw;break
                    drive+=error
                    if outtp>ceiling:internal-=outtp-ceiling+.04
                if candidate is None:raise kernel.NotFeasible('Finite LUFS/TP budget exhausted; no limiter fallback')
            metrics=measure(candidate,progress,'OPPO_SAVED_QC')
            if (metrics['lufs_i'] is None or abs(metrics['lufs_i']-target)>.03 or
                metrics['true_peak_max_dbtp_estimate']>ceiling or
                (metrics['frames'],metrics['samplerate'],metrics['channels'])!=_shape(info)):
                raise kernel.NotFeasible('Saved full-track LUFS/TP/shape verification failed')
            if io.file_hash(source)!=identity['source']:raise RuntimeError('Source changed')
            rescue_count=sum(t.get('rescue_frame_evaluations',0) for t in trials)
            report=dict(status='GAIN_ONLY' if gain_only else 'WAVEFORM_CANDIDATE',
                output_lufs=metrics['lufs_i'],output_tp=metrics['true_peak_max_dbtp_estimate'],
                gain_db=drive,optimizer_used=not gain_only,conventional_limiter_used=False,
                rescue_used=rescue_count>0,rescue_frame_evaluations=rescue_count,
                output_metrics=metrics,quality=qa,trials=trials,config=asdict(cfg),
                rescue_config=asdict(rescue_cfg),source_unchanged=True,kernel_sha256=kernel_hash,
                scope='Selected v0.1 solver first; bounded feasibility rescue only for old pointwise-budget failures')
            tmp=dest.with_suffix('.partial.wav');shutil.copyfile(candidate,tmp);io.sync_owned_file(tmp)
            os.replace(tmp,dest)
            io.atomic_json(marker,dict(identity=identity,sha256=io.file_hash(dest),report=report))
            return report
        except Exception as exc:
            io.atomic_json(job/'FAILURE.json',dict(error=repr(exc),identity=identity))
            raise
