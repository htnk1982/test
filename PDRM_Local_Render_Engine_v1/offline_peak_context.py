"""OPPO v3.2 long-context rescue.

Used only after the listening-selected v0.1 frame solver rejects a frame because
its old pointwise residual budget is infeasible. The rescue operates on a wider
context of the provisional v0.1 whole-track output and adds the smallest
spectrally/time/stereo-weighted residual needed to satisfy the peak box.

No conventional limiter, clipper, target lowering, or automatic legacy fallback.
Local and whole-track engineering gates remain vetoes. This is not a calibrated
psychoacoustic model and does not claim inaudibility.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
from scipy import fft
from scipy.ndimage import maximum_filter1d, uniform_filter1d
import offline_peak_lab as kernel

VERSION='offline-peak-context-0.1.0'

@dataclass(frozen=True)
class ContextConfig:
    contexts_ms: tuple = (128.0, 256.0, 512.0, 1024.0)
    edge_guard_ms: float = 12.0
    support_ms: float = 18.0
    context_cap_fraction: float = 0.38
    required_margin: float = 1.025
    max_peak_rewrite_fraction: float = 0.60
    residual_budget_db: float = -18.0
    energy_change_budget_db: float = 0.45
    envelope_p95_budget_db: float = 0.35
    envelope_max_budget_db: float = 0.85
    ms_budget_db: float = 0.30
    iterations: int = 320

    def validate(self,sr:int):
        if sr<=0: raise ValueError('Invalid sample rate')
        if not self.contexts_ms or any((not math.isfinite(float(v)) or v<64 or v>1500) for v in self.contexts_ms):
            raise ValueError('Invalid context sequence')
        if tuple(sorted(self.contexts_ms))!=tuple(self.contexts_ms): raise ValueError('Contexts must grow')
        vals=(self.edge_guard_ms,self.support_ms,self.context_cap_fraction,self.required_margin,
              self.max_peak_rewrite_fraction,self.residual_budget_db,self.energy_change_budget_db,
              self.envelope_p95_budget_db,self.envelope_max_budget_db,self.ms_budget_db)
        if not all(math.isfinite(float(v)) for v in vals): raise ValueError('Non-finite context config')
        if not 4<=self.edge_guard_ms<=40 or not 3<=self.support_ms<=80: raise ValueError('Invalid context timing')
        if not .05<=self.context_cap_fraction<=.8 or not 1<=self.required_margin<=1.15: raise ValueError('Invalid context allowance')
        if not .05<=self.max_peak_rewrite_fraction<=.75: raise ValueError('Invalid rewrite cap')
        if not -60<=self.residual_budget_db<=-6 or not .05<=self.energy_change_budget_db<=2: raise ValueError('Invalid local gates')
        if not .05<=self.envelope_p95_budget_db<=2 or not .1<=self.envelope_max_budget_db<=3: raise ValueError('Invalid envelope gates')
        if not .05<=self.ms_budget_db<=2: raise ValueError('Invalid stereo gate')
        if not isinstance(self.iterations,int) or not 40<=self.iterations<=1200: raise ValueError('Invalid iteration budget')


def _db(v): return float(20*np.log10(max(float(v),1e-15)))
def _edb(v): return float(10*np.log10(max(float(v),1e-20)))


def _metrics(r,y,sr,cfg):
    d=y-r
    rms=lambda a:float(np.sqrt(np.mean(a*a)))
    resid=_db(rms(d)/max(rms(r),1e-15))
    energy=_edb(np.mean(y*y)/max(np.mean(r*r),1e-20))
    w=max(3,round(.020*sr))
    pr=uniform_filter1d(np.mean(r*r,axis=1),w,mode='constant')
    py=uniform_filter1d(np.mean(y*y,axis=1),w,mode='constant')
    active=pr>max(float(pr.max())*1e-4,1e-20)
    env=10*np.log10(np.maximum(py[active],1e-20)/np.maximum(pr[active],1e-20)) if np.any(active) else np.zeros(1)
    def ratio(a):
        m=(a[:,0]+a[:,1])*.5;s=(a[:,0]-a[:,1])*.5
        return _db(np.sqrt(np.mean(m*m))/max(np.sqrt(np.mean(s*s)),1e-15))
    exact=np.array_equal(r[:,0],r[:,1]) or np.array_equal(r[:,0],-r[:,1])
    ms=0. if exact else ratio(y)-ratio(r)
    gates=dict(residual=resid<=cfg.residual_budget_db,
        energy=abs(energy)<=cfg.energy_change_budget_db,
        envelope_p95=float(np.percentile(abs(env),95))<=cfg.envelope_p95_budget_db,
        envelope_max=float(np.max(abs(env)))<=cfg.envelope_max_budget_db,
        ms=abs(ms)<=cfg.ms_budget_db)
    return dict(residual_relative_db=resid,energy_change_db=energy,
        envelope_20ms_abs_p95_db=float(np.percentile(abs(env),95)),
        envelope_20ms_abs_max_db=float(np.max(abs(env))),ms_ratio_change_db=ms,gates=gates)


def solve_context(r,sr,ceiling,kernel_cfg,*,locked=None,cfg=ContextConfig()):
    """Solve a wider residual field with zero-valued boundary guards.

    The peak box applies to the entire supplied context. The quadratic objective
    is the same family used by the selected kernel, but the old 1 ms pointwise
    allowance is replaced only here by a context-shaped hard cap. The output is
    accepted only if independent local envelope/energy/stereo gates pass.
    """
    cfg.validate(sr);r=np.asarray(r,dtype=np.float64)
    if r.ndim!=2 or r.shape[1]!=2 or not len(r): raise ValueError('Nonempty stereo context required')
    if not np.all(np.isfinite(r)) or not math.isfinite(ceiling) or ceiling<=0: raise ValueError('Invalid context input')
    required=np.maximum(np.abs(r)-ceiling,0.)
    if not np.any(required>0): return r.copy(),dict(active=False,context=True,iterations=0)
    fraction=required/np.maximum(np.abs(r),1e-15);max_fraction=float(np.max(fraction))
    if max_fraction>cfg.max_peak_rewrite_fraction+1e-12:
        raise kernel.NotFeasible(f'Context rescue would rewrite {max_fraction:.3f} of a peak; hard cap {cfg.max_peak_rewrite_fraction:.3f}')
    n=len(r);weights=kernel.spectral_weights(r,sr,kernel_cfg)
    energy=np.mean(r*r,axis=1);local=np.maximum(uniform_filter1d(energy,max(3,round(.001*sr)),mode='constant'),0)
    local_max=max(float(local.max()),1e-20)
    time_w=1+kernel_cfg.quiet_penalty*np.clip(1-local/(local_max*.08),0,1)
    norm=np.sqrt(np.sum(r*r,axis=1)+1e-18);perp=np.column_stack((-r[:,1],r[:,0]))/norm[:,None]
    support_n=max(3,int(round(cfg.support_ms*sr/1000))|1)
    need=maximum_filter1d(required,size=support_n,axis=0,mode='constant')
    amp=maximum_filter1d(np.abs(r),size=support_n,axis=0,mode='constant')
    allowance=np.maximum(required*cfg.required_margin,np.minimum(need*.75,amp*cfg.context_cap_fraction))
    guard=max(1,round(cfg.edge_guard_ms*sr/1000));taper=np.ones(n)
    if 2*guard>=n: raise kernel.NotFeasible('Context too short for boundary guard')
    ramp=np.sin(np.linspace(0,np.pi/2,guard,endpoint=False))**2
    taper[:guard]=ramp;taper[-guard:]=ramp[::-1]
    allowance*=taper[:,None]
    # A requested correction must never be hidden in the boundary guard; callers
    # are expected to enlarge/recenter the context instead.
    if np.any(required>allowance+1e-12): raise kernel.NotFeasible('Required peak lies too close to context boundary or exceeds context allowance')
    low=np.maximum(-ceiling-r,-allowance);high=np.minimum(ceiling-r,allowance)
    edge=np.zeros_like(r,dtype=bool);edge[:2]=True;edge[-2:]=True
    if locked is not None:
        locked=np.asarray(locked,dtype=bool)
        if locked.shape!=r.shape: raise ValueError('Locked mask shape differs')
        edge|=locked
    low[edge]=0.;high[edge]=0.
    if np.any(low>high+1e-12): raise kernel.NotFeasible('Context rescue cannot satisfy peak box without changing locked samples')
    L=kernel_cfg.spectral_condition+float(time_w.max())+kernel_cfg.stereo_penalty
    def grad(d):
        g=fft.irfft(weights[:,None]*fft.rfft(d,axis=0),n=n,axis=0)
        g+=time_w[:,None]*d
        g+=kernel_cfg.stereo_penalty*np.sum(d*perp,axis=1)[:,None]*perp
        return g
    d=np.minimum(np.maximum(np.zeros_like(r),low),high);z=d.copy();t=1.
    for i in range(cfg.iterations):
        nxt=np.minimum(np.maximum(z-grad(z)/L,low),high)
        nt=.5*(1+math.sqrt(1+4*t*t));ex=nxt+(t-1)/nt*(nxt-d)
        if np.sum((z-nxt)*(nxt-d))>0: ex=nxt.copy();nt=1.
        step=float(np.max(abs(nxt-d)));d,z,t=nxt,ex,nt
        if step<2e-8: break
    pg=float(np.max(abs(d-np.minimum(np.maximum(d-grad(d)/L,low),high))))
    if not np.isfinite(pg) or pg>2e-5: raise kernel.NotFeasible(f'Context rescue solver not converged: {pg:.3g}')
    y=r+d
    if float(np.max(abs(y)))>ceiling+2e-10: raise kernel.NotFeasible('Context rescue peak box failed')
    metrics=_metrics(r,y,sr,cfg)
    if not all(metrics['gates'].values()): raise kernel.NotFeasible('Context naturalness gate failed: '+str(metrics['gates']))
    return y,dict(active=True,context=True,iterations=i+1,projected_gradient=pg,
        max_required_fraction=max_fraction,required_peak_delta=float(np.max(required)),
        support_ms=cfg.support_ms,local_metrics=metrics)
