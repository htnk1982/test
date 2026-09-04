from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from .analysis import (
    crest_db,
    transient_crest_db,
    log_spectral_signature,
    ms_ratio_db,
    window_levels,
    rank_corr,
)

EPS = 1e-18


@dataclass(frozen=True)
class GateProfile:
    max_gr_db: float = 6.5
    p95_gr_db: float = 4.0
    crest_drop_db: float = 5.5
    transient_drop_db: float = 3.8
    spectral_mean_db: float = 0.65
    spectral_max_db: float = 1.8
    stereo_ms_drift_db: float = 0.75
    window_rel_drift_db: float = 1.15
    minimum_window_rank_corr: float = 0.97

    def to_dict(self) -> dict:
        return asdict(self)


SAFE_PROFILE = GateProfile()


def preservation_metrics(reference: np.ndarray, candidate: np.ndarray, sr: int, limiter_stats: dict) -> dict:
    c0 = crest_db(reference)
    c1 = crest_db(candidate)
    t0 = transient_crest_db(reference, sr)
    t1 = transient_crest_db(candidate, sr)

    s0 = log_spectral_signature(reference, sr)
    s1 = log_spectral_signature(candidate, sr)
    active = s0 >= (float(np.max(s0)) - 42.0)
    if np.sum(active) < 3:
        active = np.ones_like(s0, dtype=bool)
    delta = s1[active] - s0[active]
    weights = np.power(10.0, (s0[active] - np.max(s0[active])) / 10.0)
    weights = weights / (np.sum(weights) + EPS)
    global_shift = float(np.sum(delta * weights))
    sdiff = np.abs(delta - global_shift)
    spectral_mean = float(np.sum(sdiff * weights))
    spectral_max = float(np.percentile(sdiff, 90)) if len(sdiff) else 0.0

    ms0 = ms_ratio_db(reference)
    ms1 = ms_ratio_db(candidate)

    w0 = window_levels(reference, sr)
    w1 = window_levels(candidate, sr)
    n = min(len(w0), len(w1))
    if n:
        rw0 = w0[:n] - np.median(w0[:n])
        rw1 = w1[:n] - np.median(w1[:n])
        window_drift = float(np.percentile(np.abs(rw1 - rw0), 95))
        if np.std(rw0) < 0.15 and np.std(rw1) < 0.15:
            rcorr = 1.0
        else:
            rcorr = rank_corr(rw0, rw1)
    else:
        window_drift = 0.0
        rcorr = 1.0

    return {
        "crest_drop_db": max(0.0, float(c0 - c1)),
        "transient_crest_drop_db": max(0.0, float(t0 - t1)),
        "spectral_mean_abs_drift_db": spectral_mean,
        "spectral_max_abs_drift_db": spectral_max,
        "stereo_ms_drift_db": abs(float(ms1 - ms0)),
        "window_relative_p95_drift_db": window_drift,
        "window_rank_corr": float(rcorr),
        "max_gr_db": float(limiter_stats.get("max_gr_db", 0.0)),
        "p95_active_gr_db": float(limiter_stats.get("p95_active_gr_db", 0.0)),
    }


def evaluate_gates(metrics: dict, profile: GateProfile = SAFE_PROFILE) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if metrics["max_gr_db"] > profile.max_gr_db:
        failures.append("LIMIT_MAX_GAIN_REDUCTION")
    if metrics["p95_active_gr_db"] > profile.p95_gr_db:
        failures.append("LIMIT_SUSTAINED_GAIN_REDUCTION")
    if metrics["crest_drop_db"] > profile.crest_drop_db:
        failures.append("LIMIT_CREST_RELATION")
    if metrics["transient_crest_drop_db"] > profile.transient_drop_db:
        failures.append("LIMIT_TRANSIENT")
    if metrics["spectral_mean_abs_drift_db"] > profile.spectral_mean_db:
        failures.append("LIMIT_TIMBRE_MEAN")
    if metrics["spectral_max_abs_drift_db"] > profile.spectral_max_db:
        failures.append("LIMIT_TIMBRE_LOCAL")
    if metrics["stereo_ms_drift_db"] > profile.stereo_ms_drift_db:
        failures.append("LIMIT_STEREO")
    if metrics["window_relative_p95_drift_db"] > profile.window_rel_drift_db:
        failures.append("LIMIT_SECTION_RELATION")
    if metrics["window_rank_corr"] < profile.minimum_window_rank_corr:
        failures.append("LIMIT_SECTION_ORDER")
    return len(failures) == 0, failures
