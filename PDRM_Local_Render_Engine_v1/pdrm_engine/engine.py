from __future__ import annotations

from pathlib import Path
import hashlib
import json
import math

import numpy as np
import soundfile as sf

from . import __version__, CORE_API_VERSION, MAX_ROUND_ALLOWED
from .analysis import audit_input, integrated_lufs, true_peak_db, sample_peak_dbfs
from .contract import (
    ContractError,
    heartbeat,
    normalize_config,
    require_not_cancelled,
    validate_runtime_context,
)
from .io_utils import (
    audio_pcm_fingerprint,
    copy_noop_atomic,
    pcm_sha256,
    sha256_file,
    write_audio_atomic,
)
from .planner import solve_safe_frontier
from .preservation import preservation_metrics, evaluate_gates, SAFE_PROFILE


class CoreInputError(RuntimeError):
    pass


class CoreValidationError(RuntimeError):
    pass


HARD_AUTHORITY_ISSUES = {
    "NON_FINITE_INPUT",
    "UNSUPPORTED_CHANNEL_COUNT",
    "SAMPLERATE_TOO_LOW",
    "INPUT_TOO_SHORT",
    "TOO_QUIET_FOR_RELIABLE_LOUDNESS",
}


def _stable_hash(obj: dict) -> str:
    payload = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _runtime_allowed(runtime_context) -> int:
    if isinstance(runtime_context, dict):
        return int(runtime_context["max_round_allowed"])
    return int(getattr(runtime_context, "max_round_allowed"))


def _classify(selected, requested_target: float, tolerance: float, already_optimal: bool) -> str:
    if selected.plan == "no_op":
        return "NO_OP_ALREADY_OPTIMAL" if already_optimal else "QUALITY_LIMIT_REACHED"
    if selected.plan == "gain_only":
        return "NORMALIZED_ONLY"
    if abs(selected.achieved_lufs - requested_target) <= tolerance:
        return "FINALIZED_TARGET_REACHED"
    return "FINALIZED_NEAREST_SAFE"


def _post_write_validate(reference: np.ndarray, output_path: Path, sr: int, limiter_stats: dict, config: dict) -> tuple[bool, dict, list[str]]:
    out, out_sr = sf.read(str(output_path), always_2d=True, dtype="float64")
    failures: list[str] = []
    if out_sr != sr:
        failures.append("SAMPLERATE_DRIFT")
    if not np.all(np.isfinite(out)):
        failures.append("NON_FINITE_OUTPUT")
    lufs = integrated_lufs(out, out_sr)
    tp = true_peak_db(out, out_sr)
    sp = sample_peak_dbfs(out)
    if tp > float(config["true_peak_ceiling_dbtp"]) + 0.03:
        failures.append("TRUE_PEAK_CEILING")
    if sp >= -0.001:
        failures.append("SAMPLE_CLIPPING")

    pm = preservation_metrics(reference, out, out_sr, limiter_stats)
    gate_ok, gate_failures = evaluate_gates(pm, SAFE_PROFILE)
    failures.extend(gate_failures)
    return (len(failures) == 0 and gate_ok), {
        "lufs_i": float(lufs),
        "true_peak_dbtp": float(tp),
        "sample_peak_dbfs": float(sp),
        "plr_db": float(tp - lufs) if math.isfinite(tp) and math.isfinite(lufs) else float("inf"),
        "preservation": pm,
    }, failures


def run_job(
    input_path: str | Path,
    output_path: str | Path,
    config: dict | None,
    runtime_context,
) -> dict:
    """Run the conservative PDRM MVP-0 core.

    Contract:
      * runtime_context is mandatory and must hard-limit execution to round <= 8
      * Round 9 configuration is rejected
      * output_path must not pre-exist
      * requested loudness is subordinate to preservation and output validity
      * NO-OP is a legitimate successful result
    """
    validate_runtime_context(runtime_context)
    cfg = normalize_config(config)
    require_not_cancelled(runtime_context)

    input_path = Path(input_path).resolve()
    output_path = Path(output_path).resolve()
    if not input_path.exists() or not input_path.is_file():
        raise FileNotFoundError(input_path)
    if input_path.suffix.lower() != ".wav":
        raise CoreInputError("MVP-0 accepts WAV input only")
    if output_path.suffix.lower() != ".wav":
        raise CoreInputError("MVP-0 output must be WAV")
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite existing output: {output_path}")

    heartbeat(runtime_context, "INPUT_AUDIT", 0.05, "reading and auditing input")
    audio, sr = sf.read(str(input_path), always_2d=True, dtype="float64")
    input_file_hash = sha256_file(input_path)
    input_pcm_hash = audio_pcm_fingerprint(audio, sr)
    audit = audit_input(audio, sr)
    require_not_cancelled(runtime_context)

    hard_authority = sorted(set(audit.authority_issues) & HARD_AUTHORITY_ISSUES)
    if hard_authority and not bool(cfg.get("process_outside_authority", False)):
        raise CoreInputError("input outside MVP-0 authority: " + ",".join(hard_authority))

    requested = float(cfg["target_lufs"])
    tolerance = float(cfg["target_tolerance_lu"])
    already_optimal = (
        not audit.authority_issues
        and abs(audit.lufs_i - requested) <= tolerance
        and audit.true_peak_dbtp <= float(cfg["true_peak_ceiling_dbtp"]) + 0.025
    )

    heartbeat(runtime_context, "SAFE_FRONTIER", 0.20, "searching gain/limiter frontier")
    selected, history = solve_safe_frontier(audio, sr, cfg)
    require_not_cancelled(runtime_context)
    selected_meta = selected.metadata()
    status = _classify(selected, requested, tolerance, already_optimal)

    # Deterministic render seed depends only on decoded source PCM and config.
    render_seed = hashlib.sha256((input_pcm_hash + _stable_hash(cfg)).encode("ascii")).hexdigest()

    heartbeat(runtime_context, "RENDER", 0.70, f"rendering {selected.plan}")
    if selected.plan == "no_op":
        copy_noop_atomic(input_path, output_path, refuse_existing=True)
    else:
        assert selected.audio is not None
        write_audio_atomic(
            output_path,
            selected.audio,
            sr,
            cfg["output_subtype"],
            render_seed,
            refuse_existing=True,
        )

    heartbeat(runtime_context, "EXACT_VALIDATION", 0.88, "validating written output")
    post_ok, post_measurement, post_failures = _post_write_validate(
        audio, output_path, sr, selected.limiter, cfg
    )

    rollback = None
    if not post_ok and selected.plan != "no_op":
        # Exact outer validation outranks target attainment.  Roll back to the
        # source instead of publishing a misleading master.
        try:
            output_path.unlink()
        except FileNotFoundError:
            pass
        copy_noop_atomic(input_path, output_path, refuse_existing=True)
        rollback = {
            "from_plan": selected.plan,
            "reason": list(post_failures),
            "action": "ROLLBACK_TO_NO_OP",
        }
        status = "QUALITY_LIMIT_REACHED"
        selected_meta = {
            **selected_meta,
            "rolled_back": True,
        }
        post_ok, post_measurement, rollback_failures = _post_write_validate(audio, output_path, sr, {}, cfg)
        # A no-op may legitimately miss requested TP/loudness.  Preservation is
        # still the highest priority, so target failures are reported but do not
        # trigger destructive retries.
        post_failures = sorted(set(post_failures + rollback_failures))

    require_not_cancelled(runtime_context)
    heartbeat(runtime_context, "COMPLETE", 1.0, status)

    result = {
        "pdrm_core_version": __version__,
        "core_api_version": CORE_API_VERSION,
        "final_status": status,
        "status": status,
        "input_path": str(input_path),
        "output_path": str(output_path),
        "input_file_sha256": input_file_hash,
        "input_pcm_sha256": input_pcm_hash,
        "output_file_sha256": sha256_file(output_path),
        "output_pcm_sha256": pcm_sha256(output_path),
        "config": cfg,
        "input_audit": audit.to_dict(),
        "selected_candidate": selected_meta,
        "frontier_history": history,
        "post_write_validation": post_measurement,
        "post_write_failures": list(post_failures),
        "rollback": rollback,
        "runtime_context_ack": True,
        "runtime_max_round_allowed": _runtime_allowed(runtime_context),
        "max_round_executed": min(int(cfg.get("requested_round", MAX_ROUND_ALLOWED)), MAX_ROUND_ALLOWED),
        "round9_executed": False,
        "round9_gate_ready": bool(post_ok),
    }
    return result
