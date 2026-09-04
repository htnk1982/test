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
    research renderer.  It anticipates peaks with a centered future-aware hold
    and releases exponentially.  L/R share one gain envelope.
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
    gr = np.empty_like(desired)
    state = 0.0
    for i, d in enumerate(desired):
        d = float(d)
        if d >= state:
            state = d
        else:
            state = max(d, state * release_coeff)
        gr[i] = state

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
