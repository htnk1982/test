from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from .analysis import (
    db_to_lin,
    integrated_lufs,
    sample_peak_dbfs,
    true_peak_db,
    ensure_2d,
)
from .limiter import offline_limiter
from .preservation import preservation_metrics, evaluate_gates, SAFE_PROFILE

EPS = 1e-18


@dataclass
class Candidate:
    name: str
    plan: str
    frontier_target_lufs: float
    achieved_lufs: float
    true_peak_dbtp: float
    sample_peak_dbfs: float
    intervention_level: int
    safe: bool
    failures: list[str] = field(default_factory=list)
    preservation: dict = field(default_factory=dict)
    limiter: dict = field(default_factory=dict)
    pregain_db: float = 0.0
    audio: np.ndarray | None = field(default=None, repr=False)

    def metadata(self) -> dict:
        return {
            "name": self.name,
            "plan": self.plan,
            "frontier_target_lufs": float(self.frontier_target_lufs),
            "achieved_lufs": float(self.achieved_lufs),
            "target_error_lu": float(self.achieved_lufs - self.frontier_target_lufs),
            "true_peak_dbtp": float(self.true_peak_dbtp),
            "sample_peak_dbfs": float(self.sample_peak_dbfs),
            "intervention_level": int(self.intervention_level),
            "safe": bool(self.safe),
            "failures": list(self.failures),
            "preservation": dict(self.preservation),
            "limiter": dict(self.limiter),
            "pregain_db": float(self.pregain_db),
        }


def _hard_validity(audio: np.ndarray, sr: int, tp_ceiling: float) -> tuple[dict, list[str]]:
    failures: list[str] = []
    if not np.all(np.isfinite(audio)):
        failures.append("NON_FINITE_OUTPUT")
    sp = sample_peak_dbfs(audio)
    tp = true_peak_db(audio, sr)
    lufs = integrated_lufs(audio, sr)
    if tp > float(tp_ceiling) + 0.025:
        failures.append("TRUE_PEAK_CEILING")
    if sp >= -0.001:
        failures.append("SAMPLE_CLIPPING")
    return {
        "lufs_i": float(lufs),
        "true_peak_dbtp": float(tp),
        "sample_peak_dbfs": float(sp),
    }, failures


def _evaluate(
    reference: np.ndarray,
    candidate: np.ndarray,
    sr: int,
    plan: str,
    name: str,
    frontier_target: float,
    tp_ceiling: float,
    intervention_level: int,
    limiter_stats: dict,
    pregain_db: float,
) -> Candidate:
    exact, hard = _hard_validity(candidate, sr, tp_ceiling)
    pm = preservation_metrics(reference, candidate, sr, limiter_stats)
    gate_ok, gate_failures = evaluate_gates(pm, SAFE_PROFILE)
    failures = hard + gate_failures
    # Overshooting a frontier target is not useful; a lower value is allowed
    # because this solver explicitly searches the safe loudness frontier.
    if exact["lufs_i"] > frontier_target + 0.12:
        failures.append("FRONTIER_TARGET_OVERSHOOT")
    return Candidate(
        name=name,
        plan=plan,
        frontier_target_lufs=float(frontier_target),
        achieved_lufs=float(exact["lufs_i"]),
        true_peak_dbtp=float(exact["true_peak_dbtp"]),
        sample_peak_dbfs=float(exact["sample_peak_dbfs"]),
        intervention_level=int(intervention_level),
        safe=bool(gate_ok and not failures),
        failures=failures,
        preservation=pm,
        limiter=limiter_stats,
        pregain_db=float(pregain_db),
        audio=np.asarray(candidate, dtype=np.float64),
    )


def render_gain_candidate(
    reference: np.ndarray,
    sr: int,
    frontier_target: float,
    tp_ceiling: float,
) -> Candidate:
    current = integrated_lufs(reference, sr)
    gain_db = float(frontier_target - current)
    out = ensure_2d(reference).astype(np.float64, copy=False) * db_to_lin(gain_db)
    return _evaluate(
        reference, out, sr, "gain_only", "gain_only", frontier_target,
        tp_ceiling, 1, {}, gain_db,
    )


def _render_limiter_once(
    reference: np.ndarray,
    sr: int,
    pregain_db: float,
    tp_ceiling: float,
    config: dict,
) -> tuple[np.ndarray, dict]:
    pre = ensure_2d(reference).astype(np.float64, copy=False) * db_to_lin(pregain_db)
    return offline_limiter(
        pre,
        sr,
        tp_ceiling,
        lookahead_ms=config["limiter_lookahead_ms"],
        release_ms=config["limiter_release_ms"],
        internal_margin_db=config["limiter_internal_margin_db"],
    )


def render_limiter_candidate(
    reference: np.ndarray,
    sr: int,
    frontier_target: float,
    tp_ceiling: float,
    config: dict,
) -> Candidate:
    input_lufs = integrated_lufs(reference, sr)
    guess = float(frontier_target - input_lufs)
    low = guess - 4.0
    high = guess + 12.0
    best_audio = None
    best_stats: dict = {}
    best_pg = guess
    best_error = float("inf")

    # Loudness solve uses only integrated loudness inside the loop.  The more
    # expensive oversampled TP check is performed after selecting a pregain.
    for _ in range(14):
        mid = 0.5 * (low + high)
        out, stats = _render_limiter_once(reference, sr, mid, tp_ceiling, config)
        lufs = integrated_lufs(out, sr)
        err = abs(lufs - frontier_target)
        if err < best_error:
            best_error, best_audio, best_stats, best_pg = err, out, stats, mid
        if lufs < frontier_target:
            low = mid
        else:
            high = mid

    assert best_audio is not None

    # True-peak projection is a final local/global safety action, not the
    # loudness engine.  A small corrective re-render is allowed twice.
    for _ in range(3):
        tp = true_peak_db(best_audio, sr)
        if tp > tp_ceiling:
            trim = float(tp_ceiling - tp - 0.01)
            best_audio = best_audio * db_to_lin(trim)
        lufs = integrated_lufs(best_audio, sr)
        deficit = frontier_target - lufs
        if deficit <= 0.06:
            break
        best_pg += min(1.5, deficit + 0.05)
        best_audio, best_stats = _render_limiter_once(reference, sr, best_pg, tp_ceiling, config)

    tp = true_peak_db(best_audio, sr)
    if tp > tp_ceiling:
        best_audio = best_audio * db_to_lin(tp_ceiling - tp - 0.01)

    return _evaluate(
        reference,
        best_audio,
        sr,
        "baseline_limiter",
        "baseline_limiter",
        frontier_target,
        tp_ceiling,
        2,
        best_stats,
        best_pg,
    )


def noop_candidate(reference: np.ndarray, sr: int, requested_target: float, tp_ceiling: float) -> Candidate:
    exact, hard = _hard_validity(reference, sr, tp_ceiling)
    pm = preservation_metrics(reference, reference, sr, {})
    gate_ok, gate_failures = evaluate_gates(pm, SAFE_PROFILE)
    return Candidate(
        name="no_op",
        plan="no_op",
        frontier_target_lufs=float(requested_target),
        achieved_lufs=float(exact["lufs_i"]),
        true_peak_dbtp=float(exact["true_peak_dbtp"]),
        sample_peak_dbfs=float(exact["sample_peak_dbfs"]),
        intervention_level=0,
        safe=bool(gate_ok and not hard),
        failures=hard + gate_failures,
        preservation=pm,
        limiter={},
        pregain_db=0.0,
        audio=np.asarray(reference, dtype=np.float64),
    )


def frontier_targets(input_lufs: float, requested_target: float, step: float, max_retreat: float) -> list[float]:
    if requested_target <= input_lufs:
        return [float(requested_target)]
    lower = max(float(input_lufs), float(requested_target - max_retreat))
    values: list[float] = []
    value = float(requested_target)
    while value >= lower - 1e-9:
        values.append(round(value, 6))
        value -= float(step)
    if not values or abs(values[-1] - lower) > 0.05:
        values.append(float(lower))
    # preserve order but remove numerical duplicates
    dedup: list[float] = []
    for v in values:
        if not dedup or abs(v - dedup[-1]) > 1e-6:
            dedup.append(v)
    return dedup


def solve_safe_frontier(reference: np.ndarray, sr: int, config: dict) -> tuple[Candidate, list[dict]]:
    requested = float(config["target_lufs"])
    ceiling = float(config["true_peak_ceiling_dbtp"])
    input_lufs = integrated_lufs(reference, sr)
    history: list[dict] = []

    # If already at the requested loudness and under the ceiling, preserve the
    # exact source instead of manufacturing work.
    no_op = noop_candidate(reference, sr, requested, ceiling)
    if (
        no_op.safe
        and abs(input_lufs - requested) <= float(config["target_tolerance_lu"])
        and no_op.true_peak_dbtp <= ceiling + 0.025
    ):
        history.append(no_op.metadata())
        return no_op, history

    for level in frontier_targets(
        input_lufs,
        requested,
        float(config["frontier_step_lu"]),
        float(config["frontier_max_retreat_lu"]),
    ):
        gain = render_gain_candidate(reference, sr, level, ceiling)
        history.append(gain.metadata())
        if gain.safe and abs(gain.achieved_lufs - level) <= 0.12:
            return gain, history

        limited = render_limiter_candidate(reference, sr, level, ceiling, config)
        history.append(limited.metadata())
        if limited.safe and abs(limited.achieved_lufs - level) <= max(0.15, float(config["target_tolerance_lu"])):
            return limited, history

    # Quality gates outrank target attainment.  Unchanged source is the final
    # fallback even when it cannot meet the requested TP/loudness profile.
    history.append(no_op.metadata())
    return no_op, history
