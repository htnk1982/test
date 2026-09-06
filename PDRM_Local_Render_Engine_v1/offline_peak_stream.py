"""Restartable whole-track wrapper of the listening-selected OPPO v0.1 kernel.

The frozen solve_block, weights, frame grid and engineering budgets are reused.
Chunks are I/O checkpoints, NOT independently normalized/optimized songs. Audio
buffers have bounded duration. Small envelope/annotation vectors grow with length;
a finite duration limit is imposed. No conventional limiter or silent fallback.
"""
from __future__ import annotations
import importlib.metadata
import math
import os
from dataclasses import asdict
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import uniform_filter1d
import offline_peak_lab as kernel
import note_sub_lab as io

VERSION = 'offline-peak-stream-0.2.0'
MAX_SECONDS = 1800.0
KERNEL_SHA256 = '839cec21b954a631bdcd7e9679a9082be0d7938c4bfa1d6d6462d555f96250f3'


def verify_kernel():
    import hashlib
    value = hashlib.sha256(Path(kernel.__file__).read_text(encoding='utf-8-sig').encode()).hexdigest()
    if value != KERNEL_SHA256:
        raise RuntimeError('The listening-selected OPPO kernel has changed')
    return value


def _shape(info): return (info.frames, info.samplerate, info.channels)


def validate_source(path, cfg):
    info = sf.info(path)
    cfg.validate(info.samplerate)
    if info.channels != 2 or not .5 <= info.duration <= MAX_SECONDS:
        raise ValueError(f'Stereo audio of 0.5 to {MAX_SECONDS:g} seconds required')
    return info


def read_padded(f, left, right, gain=1.0):
    """Zero outside the real file; integer positions remain on the global grid."""
    out = np.zeros((right-left, f.channels), dtype=np.float64)
    a, b = max(0, left), min(f.frames, right)
    if b > a:
        f.seek(a)
        out[a-left:b-left] = f.read(b-a, dtype='float64', always_2d=True) * gain
    io.finite(out)
    return out


def scaled_file(source, dest, gain_db, progress=None, subtype='DOUBLE'):
    """Deterministic constant gain, cached by actual source content and gain."""
    source, dest = Path(source), Path(dest)
    ident = dict(source=io.file_hash(source), gain_db=float(gain_db), subtype=subtype)
    marker = dest.with_suffix('.scale.json')
    if io.valid_audio_cache(dest, marker) and io.read_json(marker).get('identity') == ident:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix('.partial.wav')
    gain = 10 ** (gain_db/20)
    with sf.SoundFile(source) as src, sf.SoundFile(tmp, 'w', samplerate=src.samplerate,
            channels=src.channels, format='WAV', subtype=subtype) as dst:
        for x in src.blocks(blocksize=65536, dtype='float64', always_2d=True):
            y = x*gain
            io.finite(y)
            dst.write(y)
            if progress: progress.set('CONSTANT_GAIN', src.tell(), src.frames)
    io.sync_owned_file(tmp)
    os.replace(tmp, dest)
    io.atomic_json(marker, dict(identity=ident, sha256=io.file_hash(dest)))
    return dest


def measure(path, progress=None, label='OPPO_MEASURE'):
    """Streaming pyloudnorm-compatible gated LUFS and original 4x/8x TP.

    Global .4s K-weighted block energies, .1s hops, including the same fractional
    final block handling as the selected lab's pyloudnorm 0.2. No per-tile LUFS.
    """
    info = sf.info(path); sr = info.samplerate
    width, win, hop = 2*sr, round(.4*sr), round(.1*sr)
    coeff = io.k_filter(sr)
    zi = [np.zeros((max(len(a),len(b))-1,info.channels)) for b,a in coeff]
    tail = np.empty(0); blocks = []; tp = 0.; sp=0.; sums=0.; count=0
    with sf.SoundFile(path) as f:
        for start in range(0,info.frames,width):
            end=min(info.frames,start+width)
            l,r=max(0,start-256),min(info.frames,end+256)
            f.seek(l); xp=f.read(r-l,dtype='float64',always_2d=True); io.finite(xp)
            x=xp[start-l:end-l]; sp=max(sp,float(np.max(abs(x))))
            sums+=float(np.sum(x*x));count+=x.size
            for q in (4,8):
                up=signal.resample_poly(xp,q,1,axis=0,window=('kaiser',10.5))
                tp=max(tp,float(np.max(abs(up[(start-l)*q:(end-l)*q]))))
            weighted=x
            for k,(b,a) in enumerate(coeff):
                weighted,zi[k]=signal.lfilter(b,a,weighted,axis=0,zi=zi[k])
            power=np.r_[tail,np.sum(weighted*weighted,axis=1)]
            if len(power)>=win:
                starts=np.arange(0,len(power)-win+1,hop)
                cs=np.r_[0.,np.cumsum(power)]
                blocks.extend(((cs[starts+win]-cs[starts])/win).tolist())
                tail=power[int(starts[-1])+hop:]
            else: tail=power
            if progress: progress.set(label,end,info.frames)
    expected=max(0,int(np.round((info.duration-.4)/.1))+1)
    if len(blocks)<expected and len(tail): blocks.append(float(np.sum(tail)/win))
    z=np.asarray(blocks); level=-.691+10*np.log10(np.maximum(z,1e-24))
    good=z[level>=-70]; lufs=None
    if len(good):
        gate=-.691+10*np.log10(np.mean(good))-10
        good=z[(level>-70)&(level>gate)]
        if len(good): lufs=float(-.691+10*np.log10(np.mean(good)))
    return dict(lufs_i=lufs,true_peak_max_dbtp_estimate=kernel.db(tp),
                true_peak_dbtp_estimate=kernel.db(tp),sample_peak_dbfs=kernel.db(sp),
                rms_dbfs=10*math.log10(max(sums/max(count,1),1e-30)),
                frames=info.frames,samplerate=sr,channels=info.channels)


def render_fixed_gain(source, work, gain_db, ceiling, cfg=kernel.Config(), *,
                      chunk_seconds=2.0, progress=None, interrupt_after=None):
    """Global frame alignment and identical overlap-add regardless of I/O chunks."""
    info=validate_source(source,cfg)
    if not math.isfinite(gain_db) or not math.isfinite(ceiling) or ceiling<=0:
        raise ValueError('Invalid gain or peak ceiling')
    if not math.isfinite(chunk_seconds) or not .05<=chunk_seconds<=8:
        raise ValueError('I/O chunk duration must be 0.05 to 8 seconds')
    source,work=Path(source),Path(work)
    n=max(128,round(cfg.frame_ms*info.samplerate/1000));n+=n%2
    hop=n//2; q=cfg.oversample; length=info.frames; gain=10**(gain_db/20)
    width=max(hop,round(chunk_seconds*info.samplerate/hop)*hop)
    identity=dict(source=io.file_hash(source),kernel=verify_kernel(),code=io.file_hash(__file__),
                  config=asdict(cfg),gain_db=gain_db,ceiling=ceiling,width=width,
                  versions={p:importlib.metadata.version(p) for p in ('numpy','scipy','soundfile')})
    directory=work/('pass_'+io.obj_hash(identity)[:20]);directory.mkdir(parents=True,exist_ok=True)
    win=signal.windows.hann(n,sym=False)
    paths=[];computed=reused=active=total_iters=0;max_pg=0.
    with sf.SoundFile(source) as f:
        for i,a in enumerate(range(0,length,width)):
            b=min(length,a+width); path=directory/f'{i:06d}.wav'; mark=path.with_suffix('.json')
            context=dict(identity=identity,start=a,end=b)
            saved=None
            if io.valid_audio_cache(path,mark):
                record=io.read_json(mark)
                if record.get('context')==context: saved=record
            if saved is not None:
                reused+=1;stat=saved['stats']
            else:
                # Fetch a bounded contiguous region once; frame contexts retain
                # the same padding as the full-array v0.1 reference algorithm.
                first=max(-n,((a-n)//hop+1)*hop)
                last=min((length//hop)*hop,((b-1)//hop)*hop)
                left=max(-n,first-64); right=min(length+n,last+n+64)
                buf=read_padded(f,left,right,gain)
                accum=np.zeros((b-a,2));den=np.zeros(b-a)
                stat=dict(active_frames=0,total_iterations=0,max_projected_gradient=0.,frames=0)
                for s in range(first,last+1,hop):
                    l,r=max(-n,s-64),min(length+n,s+n+64)
                    native=buf[s-left:s+n-left]
                    up=signal.resample_poly(buf[l-left:r-left],q,1,axis=0,window=('kaiser',10.5))[(s-l)*q:(s+n-l)*q]
                    locked=np.zeros_like(up,dtype=bool);locked[::q]=native==0
                    try:
                        y,result=kernel.solve_block(up,info.samplerate*q,ceiling,cfg,locked)
                    except kernel.NotFeasible as exc:
                        raise kernel.NotFeasible(
                            f'{exc}; window {max(0,s)/info.samplerate:.3f}s to '
                            f'{min(length,s+n)/info.samplerate:.3f}s. No limiter fallback.') from exc
                    d=(y-up)[::q]
                    lo,hi=max(a,s),min(b,s+n)
                    sl=slice(lo-s,hi-s);dst=slice(lo-a,hi-a)
                    accum[dst]+=d[sl]*win[sl,None];den[dst]+=win[sl]
                    stat['active_frames']+=int(result['active'])
                    stat['total_iterations']+=result['iterations'];stat['frames']+=1
                    stat['max_projected_gradient']=max(stat['max_projected_gradient'],result.get('projected_gradient',0.))
                    if progress: progress.set('OPPO_WINDOW',max(a,s),length)
                if np.any(den<=0): raise RuntimeError('Uncovered overlap-add samples')
                dry=buf[a-left:b-left];d=accum/den[:,None];d[dry==0]=0.
                io.atomic_wav(path,dry+d,info.samplerate,'DOUBLE')
                io.atomic_json(mark,dict(context=context,stats=stat,sha256=io.file_hash(path)))
                computed+=1
                if interrupt_after is not None and computed>=interrupt_after:
                    raise InterruptedError('TEST_OPPO_CHUNK_INTERRUPTION')
            active+=stat['active_frames'];total_iters+=stat['total_iterations']
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
        audio_buffer_seconds=width/info.samplerate+2*n/info.samplerate+.003,
        chunk_width_frames=width,global_frame_length=n)


def quality_report(source, output, gain_db, cfg=kernel.Config(), progress=None):
    """Streaming counterpart of all five frozen v0.1 engineering vetoes."""
    info=sf.info(source)
    if _shape(info)!=_shape(sf.info(output)):raise ValueError('QA shape mismatch')
    sr=info.samplerate;gain=10**(gain_db/20);width=2*sr
    bands=((20,180),(180,1200),(1200,4000),(4000,8000),(8000,16000))
    filters=[signal.butter(3,[lo,hi],btype='bandpass',fs=sr,output='sos') for lo,hi in bands]
    states=[[np.zeros((len(s),2,2)),np.zeros((len(s),2,2))] for s in filters]
    sums=np.zeros(3);bs=np.zeros((5,2));ms=np.zeros((2,2));pvec=[];yvec=[]
    silent_max=0.;is_mono=is_anti=True;win=max(3,round(sr*.02));step=max(1,sr//100)
    with sf.SoundFile(source) as f,sf.SoundFile(output) as g:
        for a in range(0,info.frames,width):
            b=min(info.frames,a+width)
            f.seek(a);g.seek(a);r=f.read(b-a,dtype='float64',always_2d=True)*gain
            y=g.read(b-a,dtype='float64',always_2d=True);io.finite(r);io.finite(y)
            d=y-r;sums+=np.array([np.sum(r*r),np.sum(y*y),np.sum(d*d)])
            zero=r==0
            if np.any(zero):silent_max=max(silent_max,float(np.max(abs(y[zero]))))
            is_mono=is_mono and np.array_equal(r[:,0],r[:,1]);is_anti=is_anti and np.array_equal(r[:,0],-r[:,1])
            for j,sos in enumerate(filters):
                rr,states[j][0]=signal.sosfilt(sos,r,axis=0,zi=states[j][0])
                yy,states[j][1]=signal.sosfilt(sos,y,axis=0,zi=states[j][1])
                bs[j]+=np.sum(rr*rr),np.sum(yy*yy)
            for j,x in enumerate((r,y)):
                ms[j]+=np.sum(((x[:,0]+x[:,1])*.5)**2),np.sum(((x[:,0]-x[:,1])*.5)**2)
            l,rt=max(0,a-win),min(info.frames,b+win)
            pp=[]
            centers=np.arange(((a+step-1)//step)*step,b,step)
            for file,k in ((f,gain),(g,1.)):
                file.seek(l);x=file.read(rt-l,dtype='float64',always_2d=True)*k
                p=uniform_filter1d(np.mean(x*x,axis=1),win,mode='constant')
                pp.append(p[centers-l])
            pvec.append(pp[0]);yvec.append(pp[1])
            if progress:progress.set('OPPO_NATURALNESS_GATES',b,info.frames)
    p,py=np.concatenate(pvec),np.concatenate(yvec)
    mask=p>max(float(p.max())*1e-4,1e-20)
    if not np.any(mask):raise kernel.NotFeasible('No active audio for QA')
    env=10*np.log10(np.maximum(py[mask],1e-20)/np.maximum(p[mask],1e-20))
    rms=lambda power:math.sqrt(max(power,0)/max(info.frames*2,1))
    resid=kernel.db(rms(sums[2])/max(rms(sums[0]),1e-15))
    changes={f'{lo}_{hi}':kernel.db(rms(bb)/max(rms(aa),1e-15)) if rms(aa)>1e-9 else 0.
             for (lo,hi),(aa,bb) in zip(bands,bs)}
    ratio=lambda v:kernel.db(math.sqrt(v[0]/info.frames)/max(math.sqrt(v[1]/info.frames),1e-15))
    ms_change=0. if is_mono or is_anti else ratio(ms[1])-ratio(ms[0])
    p95=float(np.percentile(abs(env),95))
    gates=dict(residual=resid<=cfg.residual_budget_db,
        band_levels=max(abs(v) for v in changes.values())<=cfg.band_level_budget_db,
        envelope_p95=p95<=cfg.envelope_p95_budget_db,
        ms_relation=abs(ms_change)<=cfg.ms_budget_db,exact_silence=silent_max==0)
    return dict(residual_relative_db=resid,band_level_changes_db=changes,
        envelope_20ms_abs_p95_db=p95,envelope_20ms_abs_max_db=float(np.max(abs(env))),
        ms_ratio_change_db=ms_change,exact_silence_max=silent_max,gates=gates,
        engineering_pass=all(gates.values()),naturalness='NOT_A_PERCEPTUAL_GUARANTEE')


def fit(source, dest, work, target, ceiling, *, cfg=kernel.Config(), progress=None,
        chunk_seconds=2.0, interrupt_after=None):
    """Same selected outer search; restartable, locked, explicit infeasibility."""
    if not math.isfinite(target) or not -30<=target<=-8 or not math.isfinite(ceiling) or not -12<=ceiling<=-1:
        raise ValueError('Invalid output targets')
    source,dest,work=Path(source).resolve(),Path(dest).resolve(),Path(work).resolve()
    if source==dest:raise ValueError('Never overwrite source')
    info=validate_source(source,cfg); kernel_hash=verify_kernel()
    identity=dict(source=io.file_hash(source),kernel=kernel_hash,version=VERSION,
        code=io.file_hash(__file__),target=target,ceiling=ceiling,config=asdict(cfg),
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    job=work/('oppo_'+io.obj_hash(identity)[:20]);job.mkdir(parents=True,exist_ok=True)
    dest.parent.mkdir(parents=True,exist_ok=True)
    marker=dest.with_suffix('.oppo.json')
    with io.job_lock(job/'job.lock'):
        if dest.exists():
            if io.valid_audio_cache(dest,marker) and io.read_json(marker).get('identity')==identity:
                return dict(io.read_json(marker)['report'],rerun_status='IDEMPOTENT_SKIP')
            raise RuntimeError('Unknown/modified optimizer output; nothing overwritten')
        try:
            base=measure(source,progress,'OPPO_INPUT');lev=base['lufs_i']
            if lev is None:raise ValueError('Silence has no finite target')
            drive=target-lev;tp=base['true_peak_max_dbtp_estimate']
            if abs(drive)>cfg.max_drive_db:raise kernel.NotFeasible('Gain budget exceeded')
            trials=[];qa=None;gain_only=tp+drive<=ceiling-.02
            if gain_only:
                candidate=scaled_file(source,job/'GAIN_ONLY.wav',drive,progress)
            else:
                internal=ceiling-cfg.tp_margin_db;candidate=None
                for attempt in range(cfg.max_outer):
                    if abs(drive)>cfg.max_drive_db:raise kernel.NotFeasible('Gain budget exceeded')
                    raw,stats=render_fixed_gain(source,job,drive,10**(internal/20),cfg,
                        chunk_seconds=chunk_seconds,progress=progress,interrupt_after=interrupt_after)
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
            report=dict(status='GAIN_ONLY' if gain_only else 'WAVEFORM_CANDIDATE',
                output_lufs=metrics['lufs_i'],output_tp=metrics['true_peak_max_dbtp_estimate'],
                gain_db=drive,optimizer_used=not gain_only,conventional_limiter_used=False,
                output_metrics=metrics,quality=qa,trials=trials,config=asdict(cfg),
                source_unchanged=True,kernel_sha256=kernel_hash,scope='Global normalization; fixed v0.1 frame solver')
            import shutil
            tmp=dest.with_suffix('.partial.wav');shutil.copyfile(candidate,tmp);io.sync_owned_file(tmp)
            os.replace(tmp,dest)
            io.atomic_json(marker,dict(identity=identity,sha256=io.file_hash(dest),report=report))
            return report
        except Exception as exc:
            io.atomic_json(job/'FAILURE.json',dict(error=repr(exc),identity=identity))
            raise
