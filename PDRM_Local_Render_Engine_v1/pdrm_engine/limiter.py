from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
from scipy.ndimage import maximum_filter1d

from .analysis import db_to_lin, ensure_2d

EPS = 1e-18


@dataclass
class LimiterStats:
    max_gr_db: float
    p95_active_gr_db: float
    mean_active_gr_db: float
    active_ratio: float
    lookahead_ms: float
    release_ms: float
    internal_margin_db: float

    def to_dict(self) -> dict:
        return asdict(self)


def release_max_envelope(desired: np.ndarray, release_coeff: float, block_size: int = 65536) -> np.ndarray:
    """Vectorized equivalent of state=max(desired, state*release_coeff).

    Processing in finite blocks avoids under/overflow in r**n on long tracks,
    while preserving the exact recurrence up to floating-point roundoff.
    """
    d = np.asarray(desired, dtype=np.float64)
    if len(d) == 0:
        return d.copy()
    r = float(np.clip(release_coeff, 0.0, 1.0))
    if r <= 0.0:
        return np.maximum(d, 0.0)
    if r >= 1.0:
        return np.maximum.accumulate(np.maximum(d, 0.0))

    out = np.empty_like(d)
    prev = 0.0
    block_size = max(256, int(block_size))
    for start in range(0, len(d), block_size):
        chunk = np.maximum(d[start:start+block_size], 0.0)
        idx = np.arange(len(chunk), dtype=np.float64)
        decay = np.power(r, idx)
        # state[k] = max(prev*r**(k+1), max_j<=k d[j]*r**(k-j))
        transformed = chunk / np.maximum(decay, np.finfo(np.float64).tiny)
        base = prev * r
        cumulative = np.maximum.accumulate(np.maximum(transformed, base))
        state = decay * cumulative
        out[start:start+len(chunk)] = state
        prev = float(state[-1])
    return out


def offline_limiter(
    audio: np.ndarray,
    sr: int,
    ceiling_db: float,
    lookahead_ms: float = 2.0,
    release_ms: float = 85.0,
    internal_margin_db: float = 0.30,
) -> tuple[np.ndarray, dict]:
    """Conservative linked-channel offline limiter.

    This is intentionally a baseline / safety mechanism, not the advanced PDRM
    research renderer. It anticipates peaks with a centered future-aware hold
    and releases exponentially. L/R share one gain envelope.
    """
    x = ensure_2d(audio).astype(np.float64, copy=False)
    if len(x) == 0:
        return x.copy(), LimiterStats(0, 0, 0, 0, lookahead_ms, release_ms, internal_margin_db).to_dict()

    sample_ceiling = db_to_lin(float(ceiling_db) - float(internal_margin_db))
    linked_peak = np.max(np.abs(x), axis=1) + EPS
    required_gr_db = np.maximum(0.0, 20.0 * np.log10(linked_peak / sample_ceiling))

    la = max(1, int(round(sr * float(lookahead_ms) / 1000.0)))
    # Centered max is acceptable in an offline/noncausal finalizer and provides
    # anticipation without adding a separate delayed signal path.
    desired = maximum_filter1d(required_gr_db, size=2 * la + 1, mode="nearest")

    release_seconds = max(0.001, float(release_ms) / 1000.0)
    release_coeff = float(np.exp(-1.0 / (release_seconds * sr)))
    gr = release_max_envelope(desired, release_coeff)

    gain = np.power(10.0, -gr / 20.0)
    out = x * gain[:, None]

    active = gr > 0.01
    stats = LimiterStats(
        max_gr_db=float(np.max(gr)) if len(gr) else 0.0,
        p95_active_gr_db=float(np.percentile(gr[active], 95)) if np.any(active) else 0.0,
        mean_active_gr_db=float(np.mean(gr[active])) if np.any(active) else 0.0,
        active_ratio=float(np.mean(active)) if len(gr) else 0.0,
        lookahead_ms=float(lookahead_ms),
        release_ms=float(release_ms),
        internal_margin_db=float(internal_margin_db),
    )
    return out, stats.to_dict()
