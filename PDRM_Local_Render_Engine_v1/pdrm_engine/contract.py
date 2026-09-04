from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Mapping

from . import MAX_ROUND_ALLOWED


class ContractError(RuntimeError):
    """Raised when runtime/config authority is violated."""


DEFAULT_CONFIG = {
    "target_lufs": -9.0,
    "true_peak_ceiling_dbtp": -2.0,
    "mode": "safe",
    "output_subtype": "PCM_24",
    "target_tolerance_lu": 0.15,
    "frontier_step_lu": 0.5,
    "frontier_max_retreat_lu": 6.0,
    "limiter_lookahead_ms": 2.0,
    "limiter_release_ms": 85.0,
    "limiter_internal_margin_db": 0.30,
    "process_outside_authority": False,
    "round9_enabled": False,
    "requested_round": 8,
}


SUPPORTED_MODES = {"safe"}
SUPPORTED_SUBTYPES = {"PCM_16", "PCM_24", "PCM_32", "FLOAT", "DOUBLE"}


def _ctx_get(ctx: Any, key: str, default: Any = None) -> Any:
    if isinstance(ctx, Mapping):
        return ctx.get(key, default)
    return getattr(ctx, key, default)


def _ctx_call(ctx: Any, name: str, *args, **kwargs) -> Any:
    if isinstance(ctx, Mapping):
        fn = ctx.get(name)
    else:
        fn = getattr(ctx, name, None)
    if callable(fn):
        return fn(*args, **kwargs)
    return None


def validate_runtime_context(runtime_context: Any) -> None:
    if runtime_context is None:
        raise ContractError("runtime_context is required")

    allowed = _ctx_get(runtime_context, "max_round_allowed", None)
    if allowed is None:
        raise ContractError("runtime_context.max_round_allowed is required")
    try:
        allowed = int(allowed)
    except Exception as exc:
        raise ContractError("runtime_context.max_round_allowed must be an integer") from exc

    if allowed > MAX_ROUND_ALLOWED:
        raise ContractError(
            f"core is hard-locked to round <= {MAX_ROUND_ALLOWED}; runtime allowed {allowed}"
        )
    if allowed < 0:
        raise ContractError("runtime_context.max_round_allowed must be >= 0")


def normalize_config(config: Mapping[str, Any] | None) -> dict[str, Any]:
    cfg = deepcopy(DEFAULT_CONFIG)
    if config:
        cfg.update(dict(config))

    if bool(cfg.get("round9_enabled", False)):
        raise ContractError("Round 9 is hard-locked")
    if int(cfg.get("requested_round", MAX_ROUND_ALLOWED)) > MAX_ROUND_ALLOWED:
        raise ContractError("requested_round exceeds hard lock")

    target = float(cfg["target_lufs"])
    tp = float(cfg["true_peak_ceiling_dbtp"])
    tol = float(cfg["target_tolerance_lu"])
    step = float(cfg["frontier_step_lu"])
    retreat = float(cfg["frontier_max_retreat_lu"])

    if not (-40.0 <= target <= -3.0):
        raise ContractError("target_lufs must be between -40 and -3 LUFS")
    if not (-12.0 <= tp <= -0.01):
        raise ContractError("true_peak_ceiling_dbtp must be between -12 and -0.01 dBTP")
    if not (0.02 <= tol <= 1.0):
        raise ContractError("target_tolerance_lu must be between 0.02 and 1.0")
    if not (0.1 <= step <= 2.0):
        raise ContractError("frontier_step_lu must be between 0.1 and 2.0")
    if not (0.0 <= retreat <= 12.0):
        raise ContractError("frontier_max_retreat_lu must be between 0 and 12")
    if cfg["mode"] not in SUPPORTED_MODES:
        raise ContractError(f"unsupported mode: {cfg['mode']}")
    if str(cfg["output_subtype"]).upper() not in SUPPORTED_SUBTYPES:
        raise ContractError(f"unsupported output_subtype: {cfg['output_subtype']}")

    cfg["target_lufs"] = target
    cfg["true_peak_ceiling_dbtp"] = tp
    cfg["target_tolerance_lu"] = tol
    cfg["frontier_step_lu"] = step
    cfg["frontier_max_retreat_lu"] = retreat
    cfg["limiter_lookahead_ms"] = float(cfg["limiter_lookahead_ms"])
    cfg["limiter_release_ms"] = float(cfg["limiter_release_ms"])
    cfg["limiter_internal_margin_db"] = float(cfg["limiter_internal_margin_db"])
    cfg["output_subtype"] = str(cfg["output_subtype"]).upper()
    cfg["requested_round"] = int(cfg.get("requested_round", MAX_ROUND_ALLOWED))
    return cfg


def heartbeat(runtime_context: Any, stage: str, progress: float | None = None, message: str | None = None) -> None:
    payload = {"stage": stage}
    if progress is not None:
        payload["progress"] = float(progress)
    if message is not None:
        payload["message"] = str(message)
    _ctx_call(runtime_context, "heartbeat", **payload)


def cancellation_requested(runtime_context: Any) -> bool:
    value = _ctx_get(runtime_context, "cancelled", None)
    if isinstance(value, bool):
        return value
    result = _ctx_call(runtime_context, "is_cancelled")
    return bool(result) if result is not None else False


def require_not_cancelled(runtime_context: Any) -> None:
    if cancellation_requested(runtime_context):
        raise ContractError("runtime requested cancellation")
