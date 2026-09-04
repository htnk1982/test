from __future__ import annotations

from typing import Callable

import numpy as np
from scipy import signal


Array = np.ndarray


def control(x: Array) -> Array:
    return np.asarray(x, dtype=np.float32)


def harmonic_elasticity(
    x: Array,
    amount: float = 0.105,
    quintic_scale: float = 0.30,
) -> Array:
    """Very mild odd-symmetric nonlinear elasticity.

    This is a PDRM-original public-principle abstraction.  It is NOT an
    emulation of Inflator, Gold Clip, CGII or any other proprietary transfer.
    """
    u = np.asarray(x, dtype=np.float32)
    a = float(amount)
    q = float(quintic_scale)
    y = u - a * (u ** 3) + q * (a * a) * (u ** 5)
    return y.astype(np.float32, copy=False)


def peak_protected_loudness(
    x: Array,
    max_gain_db: float = 0.70,
    knee: float = 0.58,
    exponent: float = 2.0,
    saturation: float = 0.025,
) -> Array:
    """Promote small/mid amplitudes while continuously protecting peaks.

    Gain tends to zero as |x| approaches `knee`; a very weak odd cubic term is
    then used only as harmonic elasticity.  No clipping or HF lift is included.
    """
    u = np.asarray(x, dtype=np.float32)
    knee = max(float(knee), 1e-6)
    w = np.clip(1.0 - np.abs(u) / knee, 0.0, 1.0)
    gain_db = float(max_gain_db) * np.power(w, float(exponent))
    v = u * np.power(10.0, gain_db / 20.0)
    b = float(saturation)
    y = v - b * (v ** 3)
    return y.astype(np.float32, copy=False)


def oversampled_chunked(
    audio: Array,
    sr: int,
    transfer: Callable[[Array], Array],
    oversample: int = 4,
    chunk_seconds: float = 8.0,
    pad_seconds: float = 0.08,
) -> Array:
    """Apply a memoryless nonlinear transfer with bounded-memory oversampling.

    Segments overlap before polyphase up/down sampling and only the central
    source-aligned region is retained.  This avoids full-track 4x allocation.
    """
    x = np.asarray(audio, dtype=np.float32)
    if x.ndim == 1:
        x = x[:, None]
    if x.ndim != 2:
        raise ValueError(f"unsupported audio shape: {x.shape}")

    osf = max(1, int(oversample))
    if osf == 1:
        return transfer(x).astype(np.float32, copy=False)

    n = len(x)
    core = max(1, int(round(float(chunk_seconds) * int(sr))))
    pad = max(0, int(round(float(pad_seconds) * int(sr))))
    out = np.empty_like(x, dtype=np.float32)

    pos = 0
    while pos < n:
        core0 = pos
        core1 = min(n, pos + core)
        a = max(0, core0 - pad)
        b = min(n, core1 + pad)
        seg = x[a:b]

        up = signal.resample_poly(
            seg,
            osf,
            1,
            axis=0,
            window=("kaiser", 10.5),
        ).astype(np.float32, copy=False)
        proc = transfer(up).astype(np.float32, copy=False)
        down = signal.resample_poly(
            proc,
            1,
            osf,
            axis=0,
            window=("kaiser", 10.5),
        ).astype(np.float32, copy=False)

        # resample_poly can differ by one sample at an edge depending on length.
        if len(down) < len(seg):
            down = np.pad(down, ((0, len(seg) - len(down)), (0, 0)))
        down = down[: len(seg)]
        c0 = core0 - a
        c1 = c0 + (core1 - core0)
        out[core0:core1] = down[c0:c1]
        pos = core1

    return out
