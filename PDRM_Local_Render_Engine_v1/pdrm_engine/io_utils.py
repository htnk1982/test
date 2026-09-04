from __future__ import annotations

from pathlib import Path
import hashlib
import os
import shutil
import tempfile

import numpy as np
import soundfile as sf

EPS = 1e-18


def sha256_file(path: str | Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    path = Path(path)
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def pcm_sha256(path: str | Path) -> str:
    """Hash decoded PCM deterministically instead of container metadata."""
    path = Path(path)
    audio, sr = sf.read(str(path), always_2d=True, dtype="float32")
    h = hashlib.sha256()
    h.update(str(int(sr)).encode("ascii"))
    h.update(str(tuple(audio.shape)).encode("ascii"))
    h.update(np.asarray(audio, dtype="<f4", order="C").tobytes())
    return h.hexdigest()


def audio_pcm_fingerprint(audio: np.ndarray, sr: int) -> str:
    x = np.asarray(audio, dtype="<f4", order="C")
    h = hashlib.sha256()
    h.update(str(int(sr)).encode("ascii"))
    h.update(str(tuple(x.shape)).encode("ascii"))
    h.update(x.tobytes())
    return h.hexdigest()


def deterministic_tpdf_dither(audio: np.ndarray, seed_hex: str, bits: int) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float64)
    lsb = 1.0 / (2 ** (bits - 1))
    seed = int(seed_hex[:16], 16) & 0xFFFFFFFF
    rng = np.random.default_rng(seed)
    noise = (rng.random(x.shape) - rng.random(x.shape)) * (0.5 * lsb)
    return np.clip(x + noise, -1.0, 1.0 - lsb)


def write_audio_atomic(
    path: str | Path,
    audio: np.ndarray,
    sr: int,
    subtype: str,
    seed_hex: str,
    refuse_existing: bool = True,
) -> None:
    """Write to a sibling temp file and atomically publish.

    The resilience layer should normally provide a private output path.  Core
    still refuses to overwrite a pre-existing path by default.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and path.exists():
        raise FileExistsError(f"output already exists: {path}")

    subtype = str(subtype).upper()
    out = np.asarray(audio, dtype=np.float64)
    bits_map = {"PCM_16": 16, "PCM_24": 24, "PCM_32": 32}
    if subtype in bits_map:
        out = deterministic_tpdf_dither(out, seed_hex, bits_map[subtype])

    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp.wav", dir=str(path.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        sf.write(str(tmp), out, int(sr), subtype=subtype)
        # fsync file payload before rename when possible.
        with tmp.open("rb") as f:
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        if refuse_existing and path.exists():
            raise FileExistsError(f"output appeared during render: {path}")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def copy_noop_atomic(src: str | Path, dst: str | Path, refuse_existing: bool = True) -> None:
    src, dst = Path(src), Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if refuse_existing and dst.exists():
        raise FileExistsError(f"output already exists: {dst}")
    fd, tmp_name = tempfile.mkstemp(prefix=dst.name + ".", suffix=".tmp", dir=str(dst.parent))
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        shutil.copyfile(src, tmp)
        if refuse_existing and dst.exists():
            raise FileExistsError(f"output appeared during no-op publish: {dst}")
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
