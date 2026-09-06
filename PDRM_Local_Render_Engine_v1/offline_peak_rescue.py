"""OPPO v3.1 feasibility rescue for windows rejected only by the old pointwise budget.

The listening-selected v0.1 solver remains first choice and is not modified.
This module is called ONLY when that solver reports `Residual budget cannot fit
this peak`. It keeps the same fixed spectral/time/stereo quadratic objective but
replaces the artificial 1 ms-RMS pointwise allowance with a minimum-feasible,
short-context allowance. Independent local and whole-track QA remain hard gates.
No conventional limiter, clipper, target lowering, or automatic legacy fallback.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np
from scipy import fft
from scipy.ndimage import maximum_filter1d, uniform_filter1d
import offline_peak_lab as kernel

VERSION = 'offline-peak-rescue-0.1.0'

@dataclass(frozen=True)
class RescueConfig:
    support_ms: float = 2.5
    support_fraction: float = 0.55
    context_cap_fraction: float = 0.40
    required_margin: float = 1.03
    max_peak_rewrite_fraction: float = 0.60
    local_residual_budget_db: float = -15.0
    local_energy_change_budget_db: float = 0.50
    iterations: int = 240

    def validate(self, sr: int) -> None:
        values = asdict(self)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                   for v in values.values()):
            raise ValueError('Non-finite rescue configuration')
        if not 0.5 <= self.support_ms <= 8.0:
            raise ValueError('Invalid rescue support')
        if not 0 < self.support_fraction <= 1 or not 0 < self.context_cap_fraction <= 1:
            raise ValueError('Invalid rescue support fractions')
        if not 1 <= self.required_margin <= 1.2:
            raise ValueError('Invalid rescue required margin')
        if not 0.05 <= self.max_peak_rewrite_fraction <= 0.75:
            raise ValueError('Invalid rescue rewrite cap')
        if not -60 <= self.local_residual_budget_db <= -6:
            raise ValueError('Invalid rescue residual gate')
        if not 0.05 <= self.local_energy_change_budget_db <= 2:
            raise ValueError('Invalid rescue energy gate')
        if not isinstance(self.iterations, int) or not 20 <= self.iterations <= 1000:
            raise ValueError('Invalid rescue iterations')
        if sr <= 0:
            raise ValueError('Invalid sample rate')


def _db(value: float) -> float:
    return float(20 * np.log10(max(float(value), 1e-15)))


def _energy_db(value: float) -> float:
    return float(10 * np.log10(max(float(value), 1e-20)))


def solve_block(r, sr, ceiling, cfg, locked=None, rescue=RescueConfig()):
    """Use the selected quadratic cost with a minimum-feasible local allowance.

    The old budget was `0.8 * 1 ms local RMS` at every sample. A sufficiently
    narrow crest can require more correction than that even when the correction
    is tiny in energy. Here the *minimum* correction needed to satisfy the peak
    box is always represented, but only when it is not a large fraction of the
    actual peak. A 2.5 ms context merely grants the optimizer room to shape that
    correction; it does not force pre/post energy into the result.
    """
    rescue.validate(sr)
    r = np.asarray(r, dtype=np.float64)
    if r.ndim != 2 or r.shape[1] != 2 or not len(r):
        raise ValueError('Nonempty stereo block required')
    if not np.all(np.isfinite(r)) or not math.isfinite(ceiling) or ceiling <= 0:
        raise ValueError('Invalid rescue input')
    if np.max(np.abs(r)) <= ceiling:
        return r.copy(), dict(active=False, rescue=True, iterations=0,
                              max_required_fraction=0.0)

    n = len(r)
    w = kernel.spectral_weights(r, sr, cfg)
    energy = np.mean(r * r, axis=1)
    local = np.maximum(uniform_filter1d(energy, max(3, round(.001 * sr)),
                                        mode='constant'), 0)
    presence = np.sqrt(local)
    old_allowance = cfg.residual_fraction * presence[:, None]

    required = np.maximum(np.abs(r) - ceiling, 0.0)
    fraction = required / np.maximum(np.abs(r), 1e-15)
    max_fraction = float(np.max(fraction))
    if max_fraction > rescue.max_peak_rewrite_fraction + 1e-12:
        raise kernel.NotFeasible(
            f'Rescue would rewrite {max_fraction:.3f} of an instantaneous peak; hard cap '
            f'{rescue.max_peak_rewrite_fraction:.3f}')

    support_n = max(3, int(round(rescue.support_ms * sr / 1000)) | 1)
    need_context = maximum_filter1d(required, size=support_n, axis=0, mode='constant')
    context_amp = maximum_filter1d(np.abs(r), size=support_n, axis=0, mode='constant')
    support = np.minimum(need_context * rescue.support_fraction,
                         context_amp * rescue.context_cap_fraction)
    allowance = np.maximum(np.maximum(old_allowance,
                                      required * rescue.required_margin), support)

    low = np.maximum(-ceiling - r, -allowance)
    high = np.minimum(ceiling - r, allowance)
    if locked is not None:
        locked = np.asarray(locked, dtype=bool)
        if locked.shape != r.shape:
            raise ValueError('Locked mask shape differs')
        low[locked] = 0.0
        high[locked] = 0.0
    if np.any(low > high + 1e-12):
        raise kernel.NotFeasible('Rescue cannot satisfy peak box without changing a locked sample')

    local_max = max(float(local.max()), 1e-20)
    time_w = 1 + cfg.quiet_penalty * np.clip(1 - local / (local_max * .08), 0, 1)
    norm = np.sqrt(np.sum(r * r, axis=1) + 1e-18)
    perp = np.column_stack((-r[:, 1], r[:, 0])) / norm[:, None]
    L = cfg.spectral_condition + float(time_w.max()) + cfg.stereo_penalty

    def gradient(d):
        g = fft.irfft(w[:, None] * fft.rfft(d, axis=0), n=n, axis=0)
        g += time_w[:, None] * d
        g += cfg.stereo_penalty * np.sum(d * perp, axis=1)[:, None] * perp
        return g

    d = np.minimum(np.maximum(np.zeros_like(r), low), high)
    initial = d.copy()
    z = d.copy()
    t = 1.0
    for i in range(rescue.iterations):
        nxt = np.minimum(np.maximum(z - gradient(z) / L, low), high)
        nt = .5 * (1 + math.sqrt(1 + 4 * t * t))
        extrap = nxt + (t - 1) / nt * (nxt - d)
        if np.sum((z - nxt) * (nxt - d)) > 0:
            extrap = nxt.copy(); nt = 1.0
        step = float(np.max(np.abs(nxt - d)))
        d, z, t = nxt, extrap, nt
        if step < 2e-8:
            break

    pg = float(np.max(np.abs(d - np.minimum(np.maximum(d - gradient(d) / L,
                                                   low), high))))
    if not np.isfinite(pg) or pg > 2e-5:
        raise kernel.NotFeasible(f'Rescue quadratic solver not converged: {pg:.3g}')
    y = r + d
    if float(np.max(np.abs(y))) > ceiling + 2e-10:
        raise kernel.NotFeasible('Rescue peak box failed after optimization')

    rms_r = float(np.sqrt(np.mean(r * r)))
    rms_d = float(np.sqrt(np.mean(d * d)))
    residual_db = _db(rms_d / max(rms_r, 1e-15))
    energy_change_db = _energy_db(np.mean(y * y) / max(np.mean(r * r), 1e-20))
    local_gates = dict(
        residual=residual_db <= rescue.local_residual_budget_db,
        energy=abs(energy_change_db) <= rescue.local_energy_change_budget_db,
    )
    if not all(local_gates.values()):
        raise kernel.NotFeasible(
            'Rescue local naturalness gate failed: ' + str(local_gates))

    obj = lambda v: float(.5 * np.sum(v * gradient(v)))
    return y, dict(active=True, rescue=True, iterations=i + 1,
                   projected_gradient=pg, objective=obj(d),
                   initial_box_objective=obj(initial),
                   max_required_fraction=max_fraction,
                   required_peak_delta=float(np.max(required)),
                   support_samples=support_n,
                   support_ms=rescue.support_ms,
                   local_residual_relative_db=residual_db,
                   local_energy_change_db=energy_change_db,
                   local_gates=local_gates,
                   reason='OLD_POINTWISE_1MS_RMS_BUDGET_INFEASIBLE')
