"""OPPO v3.4 sparse exact long-context solver.

This is an execution optimization of the v3.2 long-context rescue. The feasible
residual is still zero outside the same context allowance, so the spectral
quadratic is restricted to the smallest contiguous variable interval. Its
Toeplitz action is mathematically the same principal submatrix of the original
full-context FFT Hessian; only the FFT work size is reduced.

The v3.2 ContextConfig, gates, envelope redistribution and selected v0.1 path are
not loosened. Progress pulses make long context work visible and cancellable.
"""
from __future__ import annotations
from contextlib import contextmanager
import math
import numpy as np
from scipy import fft
from scipy.ndimage import maximum_filter1d,uniform_filter1d
import offline_peak_context as legacy
import offline_peak_lab as kernel

VERSION='offline-peak-context-0.2.0-sparse-exact'
ContextConfig=legacy.ContextConfig
_metrics=legacy._metrics
_restore_envelope=legacy._restore_envelope

_PROGRESS=None
_CALL_INDEX=0

@contextmanager
def bind_progress(progress):
    global _PROGRESS,_CALL_INDEX
    old=(_PROGRESS,_CALL_INDEX);_PROGRESS=progress;_CALL_INDEX=0
    try:yield
    finally:_PROGRESS,_CALL_INDEX=old

def _pulse(stage,done,total):
    if _PROGRESS is not None:_PROGRESS.set(stage,int(done),int(total))

def _toeplitz_spectral_operator(weights,n,lo,hi):
    """Exact spectral Hessian action on a contiguous active principal block."""
    m=int(hi-lo)
    if not 1<=m<=n:raise ValueError('Invalid sparse interval')
    h=fft.irfft(weights,n=n)
    c=h[:m].copy();r=np.empty(m,dtype=np.float64);r[0]=h[0]
    if m>1:r[1:]=h[n-np.arange(1,m)]
    size=fft.next_fast_len(2*m-1)
    embed=np.zeros(size,dtype=np.float64);embed[:m]=c
    if m>1:embed[size-(m-1):]=r[:0:-1]
    spectrum=fft.rfft(embed)
    def apply(x):
        x=np.asarray(x,dtype=np.float64)
        pad=np.zeros((size,x.shape[1]),dtype=np.float64);pad[:m]=x
        return fft.irfft(spectrum[:,None]*fft.rfft(pad,axis=0),n=size,axis=0)[:m]
    return apply,size

def _active_interval(low,high):
    variable=np.any((np.abs(low)>1e-18)|(np.abs(high)>1e-18),axis=1)
    idx=np.flatnonzero(variable)
    if not len(idx):return None
    return int(idx[0]),int(idx[-1]+1)

def solve_context(r,sr,ceiling,kernel_cfg,*,locked=None,cfg=ContextConfig()):
    global _CALL_INDEX
    cfg.validate(sr);r=np.asarray(r,dtype=np.float64)
    if r.ndim!=2 or r.shape[1]!=2 or not len(r):raise ValueError('Nonempty stereo context required')
    if not np.all(np.isfinite(r)) or not math.isfinite(ceiling) or ceiling<=0:raise ValueError('Invalid context input')
    required=np.maximum(np.abs(r)-ceiling,0.)
    if not np.any(required>0):return r.copy(),dict(active=False,context=True,iterations=0,solver_total_samples=len(r),solver_active_samples=0,solver_fft_samples=0)
    fraction=required/np.maximum(np.abs(r),1e-15);max_fraction=float(np.max(fraction))
    if max_fraction>cfg.max_peak_rewrite_fraction+1e-12:raise kernel.NotFeasible(f'Context rescue would rewrite {max_fraction:.3f} of a peak; hard cap {cfg.max_peak_rewrite_fraction:.3f}')
    n=len(r);weights=kernel.spectral_weights(r,sr,kernel_cfg);energy=np.mean(r*r,axis=1)
    local=np.maximum(uniform_filter1d(energy,max(3,round(.001*sr)),mode='constant'),0);local_max=max(float(local.max()),1e-20)
    time_w=1+kernel_cfg.quiet_penalty*np.clip(1-local/(local_max*.08),0,1)
    norm=np.sqrt(np.sum(r*r,axis=1)+1e-18);perp=np.column_stack((-r[:,1],r[:,0]))/norm[:,None]
    support_n=max(3,int(round(cfg.support_ms*sr/1000))|1)
    need=maximum_filter1d(required,size=support_n,axis=0,mode='constant');amp=maximum_filter1d(np.abs(r),size=support_n,axis=0,mode='constant')
    allowance=np.maximum(required*cfg.required_margin,np.minimum(need*.75,amp*cfg.context_cap_fraction))
    guard=max(1,round(cfg.edge_guard_ms*sr/1000));taper=np.ones(n)
    if 2*guard>=n:raise kernel.NotFeasible('Context too short for boundary guard')
    ramp=np.sin(np.linspace(0,np.pi/2,guard,endpoint=False))**2;taper[:guard]=ramp;taper[-guard:]=ramp[::-1];allowance*=taper[:,None]
    if np.any(required>allowance+1e-12):raise kernel.NotFeasible('Required peak lies too close to context boundary or exceeds context allowance')
    low=np.maximum(-ceiling-r,-allowance);high=np.minimum(ceiling-r,allowance)
    edge=np.zeros_like(r,dtype=bool);edge[:2]=True;edge[-2:]=True
    if locked is not None:
        locked=np.asarray(locked,dtype=bool)
        if locked.shape!=r.shape:raise ValueError('Locked mask shape differs')
        edge|=locked
    low[edge]=0.;high[edge]=0.
    if np.any(low>high+1e-12):raise kernel.NotFeasible('Context rescue cannot satisfy peak box without changing locked samples')
    interval=_active_interval(low,high)
    if interval is None:raise kernel.NotFeasible('Context rescue has no legal residual variables')
    lo,hi=interval;m=hi-lo
    spectral,fft_size=_toeplitz_spectral_operator(weights,n,lo,hi)
    lw=time_w[lo:hi];pp=perp[lo:hi];low_s=low[lo:hi];high_s=high[lo:hi]
    L=kernel_cfg.spectral_condition+float(time_w.max())+kernel_cfg.stereo_penalty
    def grad(d):
        g=spectral(d);g+=lw[:,None]*d;g+=kernel_cfg.stereo_penalty*np.sum(d*pp,axis=1)[:,None]*pp;return g
    d=np.minimum(np.maximum(np.zeros((m,2),dtype=np.float64),low_s),high_s);z=d.copy();t=1.
    _CALL_INDEX+=1;ctx_ms=int(round(n/sr*1000));stage=f'OPPO_CONTEXT_SOLVE_{ctx_ms}MS_P{_CALL_INDEX}'
    _pulse(stage,0,cfg.iterations)
    for i in range(cfg.iterations):
        nxt=np.minimum(np.maximum(z-grad(z)/L,low_s),high_s);nt=.5*(1+math.sqrt(1+4*t*t));ex=nxt+(t-1)/nt*(nxt-d)
        if np.sum((z-nxt)*(nxt-d))>0:ex=nxt.copy();nt=1.
        step=float(np.max(abs(nxt-d)));d,z,t=nxt,ex,nt
        if i%8==7:_pulse(stage,i+1,cfg.iterations)
        if step<2e-8:break
    _pulse(stage,i+1,cfg.iterations)
    pg=float(np.max(abs(d-np.minimum(np.maximum(d-grad(d)/L,low_s),high_s))))
    if not np.isfinite(pg) or pg>2e-5:raise kernel.NotFeasible(f'Context rescue solver not converged: {pg:.3g}')
    full=np.zeros_like(r);full[lo:hi]=d;y=r+full
    if float(np.max(abs(y)))>ceiling+2e-10:raise kernel.NotFeasible('Context rescue peak box failed')
    _pulse(f'OPPO_CONTEXT_ENVELOPE_{ctx_ms}MS',0,max(1,cfg.envelope_restore_iterations))
    y,max_beta=_restore_envelope(r,y,sr,ceiling,taper,cfg)
    if locked is not None:y[locked]=r[locked]
    metrics=_metrics(r,y,sr,cfg)
    if not all(metrics['gates'].values()):raise kernel.NotFeasible('Context naturalness gate failed: '+str(metrics['gates']))
    return y,dict(active=True,context=True,iterations=i+1,projected_gradient=pg,max_required_fraction=max_fraction,
        required_peak_delta=float(np.max(required)),support_ms=cfg.support_ms,envelope_restore_max_beta=max_beta,local_metrics=metrics,
        solver='SPARSE_EXACT_TOEPLITZ',solver_total_samples=n,solver_active_samples=m,solver_fft_samples=fft_size,
        solver_active_fraction=float(m/n),solver_context_ms=float(n/sr*1000))
