from __future__ import annotations

from dataclasses import dataclass, asdict
import math
from typing import Any

import numpy as np
import pyloudnorm as pyln
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

EPS = 1e-18


def ensure_2d(audio: np.ndarray) -> np.ndarray:
    x = np.asarray(audio)
    if x.ndim == 1:
        return x[:, None]
    if x.ndim != 2:
        raise ValueError(f"unsupported audio shape: {x.shape}")
    return x


def db_to_lin(db: float) -> float:
    return float(10.0 ** (float(db) / 20.0))


def lin_to_db(value: float) -> float:
    value = float(value)
    return float(20.0 * math.log10(max(value, EPS)))


def integrated_lufs(audio: np.ndarray, sr: int) -> float:
    x = ensure_2d(audio)
    meter = pyln.Meter(int(sr), filter_class="K-weighting")
    try:
        return float(meter.integrated_loudness(x))
    except Exception:
        return float("-inf")


def sample_peak_dbfs(audio: np.ndarray) -> float:
    x = np.asarray(audio)
    if x.size == 0:
        return float("-inf")
    return lin_to_db(float(np.max(np.abs(x))))


def true_peak_db(
    audio: np.ndarray,
    sr: int,
    oversample: int = 4,
    chunk_seconds: float = 2.0,
) -> float:
    """Chunked polyphase oversampled peak estimate.

    This is an engineering true-peak estimate used consistently inside PDRM.
    Exact standards certification is outside MVP-0.
    """
    x = ensure_2d(audio).astype(np.float64, copy=False)
    if len(x) == 0:
        return float("-inf")
    oversample = max(1, int(oversample))
    if oversample == 1:
        return sample_peak_dbfs(x)

    core = max(256, int(round(float(chunk_seconds) * int(sr))))
    pad = max(64, 16 * oversample)
    peak = 0.0
    pos = 0
    while pos < len(x):
        core_end = min(len(x), pos + core)
        a = max(0, pos - pad)
        b = min(len(x), core_end + pad)
        seg = x[a:b]
        up = signal.resample_poly(seg, oversample, 1, axis=0, window=("kaiser", 8.6))
        left = (pos - a) * oversample
        right = left + (core_end - pos) * oversample
        local = up[left:right]
        if local.size:
            peak = max(peak, float(np.max(np.abs(local))))
        pos = core_end
    return lin_to_db(peak)


def crest_db(audio: np.ndarray) -> float:
    x = ensure_2d(audio).astype(np.float64, copy=False)
    if not x.size:
        return 0.0
    peak = float(np.max(np.abs(x))) + EPS
    rms = float(np.sqrt(np.mean(x * x))) + EPS
    return float(20.0 * np.log10(peak / rms))


def transient_crest_db(audio: np.ndarray, sr: int | None = None) -> float:
    x = ensure_2d(audio).astype(np.float64, copy=False)
    if not x.size:
        return 0.0
    linked = np.max(np.abs(x), axis=1) + EPS
    if sr is None:
        # Preserve backward-compatible behavior for internal calls that only need
        # a scale-invariant transient proxy.
        sr = 48000
    fast = max(1, int(round(int(sr) * 0.001)))
    slow = max(fast + 1, int(round(int(sr) * 0.050)))
    p = np.mean(x * x, axis=1) + EPS
    slow_rms = np.sqrt(uniform_filter1d(p, size=slow, mode="nearest") + EPS)
    peak_hold = maximum_filter1d(linked, size=fast, mode="nearest")
    c = 20.0 * np.log10((peak_hold + EPS) / (slow_rms + EPS))
    activity = 10.0 * np.log10(slow_rms * slow_rms + EPS)
    active = activity >= max(float(np.percentile(activity, 18.0)), float(np.max(activity) - 48.0))
    values = c[active] if np.any(active) else c
    return float(np.percentile(values, 90.0)) if len(values) else 0.0


def ms_ratio_db(audio: np.ndarray) -> float:
    x = ensure_2d(audio).astype(np.float64, copy=False)
    if x.shape[1] < 2:
        return 60.0
    l, r = x[:, 0], x[:, 1]
    mid = (l + r) * 0.5
    side = (l - r) * 0.5
    pm = float(np.mean(mid * mid)) + EPS
    ps = float(np.mean(side * side)) + EPS
    return float(10.0 * np.log10(pm / ps))


def window_levels(audio: np.ndarray, sr: int, window_seconds: float = 3.0, hop_seconds: float = 1.0) -> np.ndarray:
    x = ensure_2d(audio).astype(np.float64, copy=False)
    mono_power = np.mean(x * x, axis=1) + EPS
    win = max(1, int(round(float(window_seconds) * sr)))
    hop = max(1, int(round(float(hop_seconds) * sr)))
    if len(mono_power) <= win:
        return np.array([10.0 * np.log10(float(np.mean(mono_power)) + EPS)], dtype=np.float64)
    out = []
    for start in range(0, len(mono_power) - win + 1, hop):
        out.append(10.0 * np.log10(float(np.mean(mono_power[start:start+win])) + EPS))
    return np.asarray(out, dtype=np.float64)


def rank_corr(a: np.ndarray, b: np.ndarray) -> float:
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    n = min(len(a), len(b))
    if n < 3:
        return 1.0
    a, b = a[:n], b[:n]
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    if np.std(ra) < EPS or np.std(rb) < EPS:
        return 1.0
    return float(np.corrcoef(ra, rb)[0, 1])


def log_spectral_signature(audio: np.ndarray, sr: int, bands: int = 48) -> np.ndarray:
    x = ensure_2d(audio).astype(np.float64, copy=False)
    mono = np.mean(x[:, :2], axis=1)
    if len(mono) < 256:
        return np.zeros(bands, dtype=np.float64)
    nperseg = min(8192, max(1024, 2 ** int(np.floor(np.log2(max(1024, min(len(mono), 8192)))))))
    freqs, psd = signal.welch(mono, fs=sr, window="hann", nperseg=nperseg, noverlap=nperseg // 2)
    lo, hi = 25.0, min(18000.0, sr * 0.48)
    edges = np.geomspace(lo, max(lo * 1.05, hi), bands + 1)
    vals = np.empty(bands, dtype=np.float64)
    for i in range(bands):
        idx = (freqs >= edges[i]) & (freqs < edges[i+1])
        vals[i] = 10.0 * np.log10(float(np.mean(psd[idx])) + EPS) if np.any(idx) else -160.0
    return vals


def clipping_ratio(audio: np.ndarray, threshold: float = 0.9995) -> float:
    x = np.asarray(audio)
    return float(np.mean(np.abs(x) >= float(threshold))) if x.size else 0.0


@dataclass
class InputAudit:
    samplerate: int
    channels: int
    frames: int
    duration_seconds: float
    lufs_i: float
    sample_peak_dbfs: float
    true_peak_dbtp: float
    plr_db: float
    crest_db: float
    transient_crest_db: float
    stereo_ms_ratio_db: float
    clipping_ratio: float
    authority_issues: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def audit_input(audio: np.ndarray, sr: int) -> InputAudit:
    x = ensure_2d(audio).astype(np.float64, copy=False)
    issues: list[str] = []
    if not np.all(np.isfinite(x)):
        issues.append("NON_FINITE_INPUT")
    if x.shape[1] not in (1, 2):
        issues.append("UNSUPPORTED_CHANNEL_COUNT")
    if int(sr) < 22050:
        issues.append("SAMPLERATE_TOO_LOW")
    duration = len(x) / float(sr) if sr else 0.0
    if duration < 1.0:
        issues.append("INPUT_TOO_SHORT")

    lufs = integrated_lufs(x, sr)
    tp = true_peak_db(x, sr)
    sp = sample_peak_dbfs(x)
    clip = clipping_ratio(x)
    if clip > 0.002:
        issues.append("HEAVY_EXISTING_CLIPPING")
    if not math.isfinite(lufs) or lufs < -70.0:
        issues.append("TOO_QUIET_FOR_RELIABLE_LOUDNESS")

    return InputAudit(
        samplerate=int(sr),
        channels=int(x.shape[1]),
        frames=int(len(x)),
        duration_seconds=float(duration),
        lufs_i=float(lufs),
        sample_peak_dbfs=float(sp),
        true_peak_dbtp=float(tp),
        plr_db=float(tp - lufs) if math.isfinite(lufs) and math.isfinite(tp) else float("inf"),
        crest_db=float(crest_db(x)),
        transient_crest_db=float(transient_crest_db(x, sr)),
        stereo_ms_ratio_db=float(ms_ratio_db(x)),
        clipping_ratio=float(clip),
        authority_issues=issues,
    )
