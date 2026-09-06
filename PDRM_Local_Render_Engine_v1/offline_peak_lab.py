"""Offline Peak Lab 0.1: fixed-reference, constrained additive waveform residual.

RESEARCH CANDIDATE, NOT A TRANSPARENCY GUARANTEE. This is not a reproduction
of Jeannerot et al.'s auditory model. Spectral weights are an uncalibrated proxy.
No alimiter, sample clipping post-process, phase rotator, or fallback in optimizer.
Existing production entry points are never imported or changed by this module.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from pathlib import Path
import argparse, hashlib, json, math, os, tempfile, time
import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy import signal, fft
from scipy.ndimage import uniform_filter1d

VERSION = 'offline-peak-lab-0.1.0'

class NotFeasible(RuntimeError):
    pass

@dataclass(frozen=True)
class Config:
    frame_ms: float = 42.6666666667
    oversample: int = 4
    iterations: int = 160
    max_outer: int = 5
    tp_margin_db: float = .12
    spectral_condition: float = 48.0
    stereo_penalty: float = 6.0
    quiet_penalty: float = 6.0
    residual_fraction: float = .80
    residual_budget_db: float = -24.0
    band_level_budget_db: float = .50
    envelope_p95_budget_db: float = .35
    ms_budget_db: float = .30
    max_drive_db: float = 24.0

    def validate(self, sr):
        if sr not in (44100,48000,88200,96000): raise ValueError('Unsupported sample rate')
        for v in asdict(self).values():
            if isinstance(v,bool) or not math.isfinite(v): raise ValueError('Non-finite config')
        if self.oversample != 4 or not 8 <= self.frame_ms <= 100: raise ValueError('Invalid frame')
        if not isinstance(self.iterations,int) or not 10 <= self.iterations <= 1000: raise ValueError('Invalid iterations')
        if not isinstance(self.max_outer,int) or not 1<=self.max_outer<=8: raise ValueError('Invalid outer limit')
        if not .02<=self.tp_margin_db<=.5 or not 1<=self.spectral_condition<=128: raise ValueError('Invalid numerical budget')
        if not 0<=self.stereo_penalty<=100 or not 0<=self.quiet_penalty<=100: raise ValueError('Invalid penalty')
        if not 0<self.residual_fraction<=1 or not -80<self.residual_budget_db<0: raise ValueError('Invalid residual budget')
        if min(self.band_level_budget_db,self.envelope_p95_budget_db,self.ms_budget_db,self.max_drive_db)<=0: raise ValueError('Invalid QA budget')


def validate_audio(x, sr, cfg):
    cfg.validate(sr)
    x=np.asarray(x,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=2 or len(x)<int(sr*.5): raise ValueError('Stereo, at least .5 seconds required')
    if not np.all(np.isfinite(x)): raise ValueError('Non-finite audio')
    return x


def db(v): return float(20*np.log10(max(float(v),1e-15)))


def loudness(x,sr):
    v=float(pyln.Meter(sr).integrated_loudness(x))
    if not math.isfinite(v): raise ValueError('Silence has no finite loudness target')
    return v


def true_peak(x,sr,factors=(4,8)):
    maximum=0.
    for a in range(0,len(x),sr*2):
        b=min(len(x),a+sr*2);l=max(0,a-256);r=min(len(x),b+256)
        for q in factors:
            up=signal.resample_poly(x[l:r],q,1,axis=0,window=('kaiser',10.5))
            maximum=max(maximum,float(np.max(np.abs(up[(a-l)*q:(b-l)*q]))))
    return db(maximum)


def spectral_weights(r,sr,cfg):
    """Fixed original-window spectral protection, not a calibrated masking model."""
    n=len(r)
    z=fft.rfft(r*np.hanning(n)[:,None],axis=0)
    power=np.mean(abs(z)**2,axis=1)
    width=max(3,int(150*n/sr)|1)
    p=uniform_filter1d(power,width,mode='nearest')
    top=max(float(p.max()),1e-20)
    w=(top/(p+top*.0001))**.35
    f=fft.rfftfreq(n,1/sr)
    w *= 1+3/(1+(f/180)**4)  # expensive LF alteration
    w[f>20000] *= 8         # discourage unrepresentable/ultrasonic residual
    return np.clip(w,1,cfg.spectral_condition)


def solve_block(r,sr,ceiling,cfg,locked=None):
    """Convex quadratic objective + sample box on 4x analysis lattice.

    Projected accelerated gradient; the box projection is an inner numerical
    step, not an independent clipper applied to the published waveform.
    The weights and pan vectors are frozen from r throughout all iterations.
    """
    n=len(r)
    if np.max(abs(r))<=ceiling: return r.copy(),dict(active=False,iterations=0)
    w=spectral_weights(r,sr,cfg)
    energy=np.mean(r*r,axis=1)
    local=np.maximum(uniform_filter1d(energy,max(3,round(.001*sr)),mode='constant'),0)
    presence=np.sqrt(local)
    allowance=cfg.residual_fraction*presence[:,None]
    low=np.maximum(-ceiling-r,-allowance)
    high=np.minimum(ceiling-r,allowance)
    if locked is not None:
        low[locked]=0.;high[locked]=0.
    if np.any(low>high+1e-12): raise NotFeasible('Residual budget cannot fit this peak')
    local_max=max(float(local.max()),1e-20)
    time_w=1+cfg.quiet_penalty*np.clip(1-local/(local_max*.08),0,1)
    norm=np.sqrt(np.sum(r*r,axis=1)+1e-18)
    # Unit vector orthogonal to original stereo direction. Penalize pan changes.
    perp=np.column_stack((-r[:,1],r[:,0]))/norm[:,None]
    L=cfg.spectral_condition+float(time_w.max())+cfg.stereo_penalty
    def gradient(d):
        g=fft.irfft(w[:,None]*fft.rfft(d,axis=0),n=n,axis=0)
        g+=time_w[:,None]*d
        g+=cfg.stereo_penalty*np.sum(d*perp,axis=1)[:,None]*perp
        return g
    d=np.minimum(np.maximum(np.zeros_like(r),low),high)
    initial=d.copy();z=d.copy();t=1.
    for i in range(cfg.iterations):
        nxt=np.minimum(np.maximum(z-gradient(z)/L,low),high)
        nt=.5*(1+math.sqrt(1+4*t*t))
        # Adaptive restart removes oscillations without changing the objective.
        extrap=nxt+(t-1)/nt*(nxt-d)
        if np.sum((z-nxt)*(nxt-d))>0: extrap=nxt.copy();nt=1.
        step=float(np.max(abs(nxt-d)));d=nxt;z=extrap;t=nt
        if step<2e-8: break
    pg=float(np.max(abs(d-np.minimum(np.maximum(d-gradient(d)/L,low),high))))
    if not np.isfinite(pg) or pg>2e-5: raise NotFeasible(f'Quadratic solver not converged: {pg:.3g}')
    obj=lambda v: float(.5*np.sum(v*gradient(v)))
    return r+d,dict(active=True,iterations=i+1,projected_gradient=pg,
        objective=obj(d),initial_box_objective=obj(initial))


def render_fixed_gain(x,sr,ceiling,cfg,progress=None):
    """Original fixed frames; complementary windows; final waveform rechecked.

    Work in overlapping 4x lattices and retain native sample positions. The
    lattice is a surrogate, not an exact bandlimited-TP constraint; 4x/8x
    verification AFTER overlap-add determines whether it can be published.
    """
    n=max(128,int(round(cfg.frame_ms*sr/1000)))
    n += n%2;hop=n//2;half=hop;q=cfg.oversample
    padded=np.pad(x,((n,n),(0,0)))
    # Periodic Hann overlap-add adds to exactly one in the interior.
    win=signal.windows.hann(n,sym=False)
    accum=np.zeros_like(padded);den=np.zeros(len(padded))
    active=0;max_pg=0.;iterations=0;frames=0
    for a in range(0,len(padded)-n+1,hop):
        native=padded[a:a+n]
        # Interpolation uses neighboring context, not zero pad at each frame edge.
        l=max(0,a-64);rr=min(len(padded),a+n+64)
        up=signal.resample_poly(padded[l:rr],q,1,axis=0,window=('kaiser',10.5))[(a-l)*q:(a+n-l)*q]
        # Pin exact native silence. Also protect fractionally interpolated quiet
        # regions according to their fixed original local-energy allowance.
        locked=np.zeros_like(up,dtype=bool);locked[::q]=native==0
        y,stat=solve_block(up,sr*q,ceiling,cfg,locked)
        # Keep an additive residual rather than SRC-roundtripping the input.
        d=(y-up)[::q]
        accum[a:a+n]+=d*win[:,None];den[a:a+n]+=win
        active+=int(stat['active']);frames+=1;iterations+=stat['iterations']
        max_pg=max(max_pg,stat.get('projected_gradient',0.))
        if progress and frames%128==0: progress(frames,active)
    sl=slice(n,n+len(x));d=accum[sl]/den[sl,None]
    d[x==0]=0.
    out=x+d
    return out,dict(frames=frames,active_frames=active,total_iterations=iterations,max_projected_gradient=max_pg)


def quality_report(reference,y,sr,cfg):
    """Independent engineering vetoes. None is an inaudibility/fatigue score."""
    d=y-reference
    rms=lambda a:float(np.sqrt(np.mean(a*a)))
    residual_db=db(rms(d)/max(rms(reference),1e-15))
    band_changes={}
    for lo,hi in ((20,180),(180,1200),(1200,4000),(4000,8000),(8000,16000)):
        sos=signal.butter(3,[lo,hi],btype='bandpass',fs=sr,output='sos')
        a=signal.sosfilt(sos,reference,axis=0);b=signal.sosfilt(sos,y,axis=0)
        band_changes[f'{lo}_{hi}']=db(rms(b)/max(rms(a),1e-15)) if rms(a)>1e-9 else 0.
    power=lambda a:uniform_filter1d(np.mean(a*a,axis=1),max(3,round(sr*.02)),mode='constant')[::max(1,sr//100)]
    p,py=power(reference),power(y);active=p>max(float(p.max())*1e-4,1e-20)
    env=10*np.log10(np.maximum(py[active],1e-20)/np.maximum(p[active],1e-20))
    ms=lambda a: db(rms((a[:,0]+a[:,1])*.5)/max(rms((a[:,0]-a[:,1])*.5),1e-15))
    ms_change=ms(y)-ms(reference)
    # Degenerate exact mono/antiphase ratios are not useful numerical scores.
    exact_relation=(np.array_equal(reference[:,0],reference[:,1]) or np.array_equal(reference[:,0],-reference[:,1]))
    if exact_relation: ms_change=0.
    zeros=reference==0
    silent_max=float(np.max(abs(y[zeros]))) if np.any(zeros) else 0.
    gates=dict(residual= residual_db<=cfg.residual_budget_db,
        band_levels=max(abs(v) for v in band_changes.values())<=cfg.band_level_budget_db,
        envelope_p95=float(np.percentile(abs(env),95))<=cfg.envelope_p95_budget_db,
        ms_relation=abs(ms_change)<=cfg.ms_budget_db,
        exact_silence=silent_max==0.)
    return dict(residual_relative_db=residual_db,band_level_changes_db=band_changes,
        envelope_20ms_abs_p95_db=float(np.percentile(abs(env),95)),
        envelope_20ms_abs_max_db=float(np.max(abs(env))),ms_ratio_change_db=ms_change,
        exact_silence_max=silent_max,gates=gates,
        engineering_pass=all(gates.values()),naturalness='NOT_LISTENING_VALIDATED',
        scope='Fixed engineering budgets; not a calibrated auditory masking model')


def optimize(x,sr,target_lufs=-12.,ceiling_dbtp=-2.,cfg=Config(),progress=None):
    x=validate_audio(x,sr,cfg)
    if not math.isfinite(target_lufs) or not -30<=target_lufs<=-8:raise ValueError('Invalid LUFS')
    if not math.isfinite(ceiling_dbtp) or not -12<=ceiling_dbtp<=-1:raise ValueError('Invalid TP')
    base_l=loudness(x,sr);base_tp=true_peak(x,sr)
    drive=target_lufs-base_l
    if abs(drive)>cfg.max_drive_db:raise NotFeasible('Gain budget exceeded')
    if base_tp+drive<=ceiling_dbtp-.02:
        y=x*10**(drive/20)
        return y,dict(status='GAIN_ONLY',target_lufs=target_lufs,ceiling_dbtp=ceiling_dbtp,
            output_lufs=loudness(y,sr),output_tp=true_peak(y,sr),gain_db=drive,
            optimizer_used=False,conventional_limiter_used=False,trials=[])
    trials=[];internal=ceiling_dbtp-cfg.tp_margin_db
    for attempt in range(cfg.max_outer):
        if abs(drive)>cfg.max_drive_db:raise NotFeasible('Gain budget exceeded')
        reference=x*10**(drive/20)
        y,stats=render_fixed_gain(reference,sr,10**(internal/20),cfg,progress)
        lev=loudness(y,sr);tp=true_peak(y,sr)
        trials.append(dict(attempt=attempt,drive_db=drive,internal_ceiling=internal,lufs=lev,tp=tp,**stats))
        error=target_lufs-lev
        if abs(error)<=.03 and tp<=ceiling_dbtp:
            qa=quality_report(reference,y,sr,cfg)
            if not qa['engineering_pass']:raise NotFeasible('Waveform engineering veto: '+json.dumps(qa))
            return y,dict(status='WAVEFORM_CANDIDATE',target_lufs=target_lufs,ceiling_dbtp=ceiling_dbtp,
                output_lufs=lev,output_tp=tp,gain_db=drive,optimizer_used=True,
                conventional_limiter_used=False,trials=trials,quality=qa,config=asdict(cfg))
        drive+=error
        if tp>ceiling_dbtp:internal-=tp-ceiling_dbtp+.04
    raise NotFeasible('Finite LUFS/TP iteration budget exhausted; no fallback')


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def run_file(source,out_root,target_lufs=-12.,ceiling_dbtp=-2.,cfg=Config()):
    src=Path(source).resolve(strict=True);root=Path(out_root).resolve()
    if root==src.parent or src.parent in root.parents:raise ValueError('Lab outputs must be outside source folder')
    digest=file_hash(src);x,sr=sf.read(src,dtype='float64',always_2d=True)
    identity=dict(source_sha256=digest,version=VERSION,code_sha256=file_hash(__file__),
        target_lufs=target_lufs,ceiling_dbtp=ceiling_dbtp,config=asdict(cfg))
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()[:16]
    final=root/('oppo_'+key)
    if final.exists():raise FileExistsError('Existing experiment is preserved: '+str(final))
    root.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.oppo_',dir=root))
    try:
        y,report=optimize(x,sr,target_lufs,ceiling_dbtp,cfg,
            lambda n,a:print(f'frames={n}, active={a}',flush=True))
        path=stage/'CANDIDATE.wav';sf.write(path,y,sr,subtype='FLOAT')
        saved,saved_sr=sf.read(path,dtype='float64',always_2d=True)
        ql=loudness(saved,sr);qt=true_peak(saved,sr)
        if saved.shape!=x.shape or saved_sr!=sr or abs(ql-target_lufs)>.03 or qt>ceiling_dbtp:raise NotFeasible('Saved file verification failed')
        if file_hash(src)!=digest:raise RuntimeError('Source changed')
        report.update(identity=identity,saved_lufs=ql,saved_tp=qt,source_unchanged=True,
            output_sha256=file_hash(path),naturalness='NOT_LISTENING_VALIDATED')
        (stage/'REPORT.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        os.rename(stage,final)
        return report,final
    except Exception as e:
        # Diagnostic evidence only. A failed candidate is not published as audio.
        for p in stage.glob('*.wav'):p.unlink()
        (stage/'FAILURE.txt').write_text(str(e),encoding='utf-8')
        raise

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('output_root',type=Path)
    p.add_argument('--lufs',type=float,default=-12);p.add_argument('--tp',type=float,default=-2)
    a=p.parse_args();r,f=run_file(a.source,a.output_root,a.lufs,a.tp);print(f)
