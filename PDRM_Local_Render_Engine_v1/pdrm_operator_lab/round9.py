from __future__ import annotations

from pathlib import Path
import argparse
import functools
import hashlib
import json
import math
import os
import shutil
import subprocess
import zipfile

import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

from pdrm_engine.analysis import (
    integrated_lufs,
    sample_peak_dbfs,
    true_peak_db,
    crest_db,
    transient_crest_db,
    ms_ratio_db,
)
from pdrm_engine.codec import ffmpeg_path, ffmpeg_encoders
from pdrm_engine.io_utils import sha256_file

from . import LAB_VERSION
from .operators import harmonic_elasticity, peak_protected_loudness, oversampled_chunked


EPS = 1e-18
EXPERIMENT_ID = "PDRM-v0.6-Round9-HarmonicLoudness-exp1"
CANDIDATE_ORDER = (
    "Control_Round8A",
    "HarmonicElasticity",
    "PeakProtectedLoudness",
)
DEFAULT_CONFIG = {
    "experiment_id": EXPERIMENT_ID,
    "target_lufs": -14.0,
    "oversample": 4,
    "chunk_seconds": 8.0,
    "pad_seconds": 0.08,
    "harmonic_elasticity": {
        "amount": 0.105,
        "quintic_scale": 0.30,
    },
    "peak_protected_loudness": {
        "max_gain_db": 0.70,
        "knee": 0.58,
        "exponent": 2.0,
        "saturation": 0.025,
    },
}


def _stable_hash(obj: object) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _atomic_json(path: Path, obj: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _atomic_wav(path: Path, audio: np.ndarray, sr: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp" + path.suffix)
    sf.write(tmp, audio, sr, subtype="PCM_24")
    os.replace(tmp, path)


def _decode_to_float_wav(src: Path, dst: Path) -> Path:
    src = src.resolve()
    dst.parent.mkdir(parents=True, exist_ok=True)
    # WAV/FLAC/AIFF go through one libsndfile decode path.  Compressed delivery
    # formats are decoded once with ffmpeg and then shared by all candidates.
    if src.suffix.lower() in {".wav", ".flac", ".aif", ".aiff"}:
        x, sr = sf.read(src, always_2d=True, dtype="float32")
        tmp = dst.with_name(dst.stem + ".tmp.wav")
        sf.write(tmp, x, sr, subtype="FLOAT")
        os.replace(tmp, dst)
        return dst

    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("Compressed Round 8 baseline requires ffmpeg, but ffmpeg is unavailable.")
    tmp = dst.with_name(dst.stem + ".tmp.wav")
    subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-c:a", "pcm_f32le", str(tmp)],
        check=True,
    )
    os.replace(tmp, dst)
    return dst


def _normalize_lufs(audio: np.ndarray, sr: int, target: float) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32)
    current = integrated_lufs(x, sr)
    if not math.isfinite(current):
        raise ValueError("baseline loudness is not finite")
    gain = float(10.0 ** ((float(target) - current) / 20.0))
    return (x * gain).astype(np.float32, copy=False)


def _event_crest(audio: np.ndarray, sr: int, window_ms: int) -> float:
    x = np.asarray(audio, dtype=np.float64)
    block = max(1, int(round(sr * 0.001)))
    pad = (-len(x)) % block
    xp = np.pad(x, ((0, pad), (0, 0))) if pad else x
    b = xp.reshape(-1, block, x.shape[1])
    p = np.mean(b * b, axis=(1, 2)) + EPS
    pk = np.max(np.abs(b), axis=(1, 2)) + EPS
    width = max(1, int(window_ms))
    ps = uniform_filter1d(p, width, mode="nearest")
    pm = maximum_filter1d(pk, width, mode="nearest")
    level = 10.0 * np.log10(ps)
    active = level >= max(float(np.percentile(level, 18.0)), float(np.max(level) - 48.0))
    c = 20.0 * np.log10(pm / np.sqrt(ps))
    values = c[active] if np.any(active) else c
    return float(np.median(values)) if len(values) else 0.0


def _pdf_metrics(audio: np.ndarray) -> dict:
    a = np.abs(np.asarray(audio, dtype=np.float64)).ravel()
    peak = float(np.max(a)) + EPS
    r = a / peak
    return {
        "mean_abs_over_peak": float(np.mean(a) / peak),
        "near_zero_ratio": float(np.mean(r < 0.01)),
        "mid_01_03_ratio": float(np.mean((r >= 0.10) & (r < 0.30))),
        "mid_03_06_ratio": float(np.mean((r >= 0.30) & (r < 0.60))),
        "high_06_09_ratio": float(np.mean((r >= 0.60) & (r < 0.90))),
    }


def _spectral_shares(audio: np.ndarray, sr: int) -> dict:
    x = np.asarray(audio, dtype=np.float64)
    mono = np.mean(x[:, :2], axis=1)
    nper = min(8192, len(mono))
    if nper < 256:
        return {}
    f, p = signal.welch(mono, fs=sr, nperseg=nper, noverlap=nper // 2)
    total = float(np.sum(p[(f >= 20) & (f < min(18000, sr * 0.48))])) + EPS
    out = {}
    for lo, hi in ((20, 80), (80, 200), (500, 4000), (4000, 8000), (8000, 16000)):
        out[f"{lo}_{hi}_share"] = float(np.sum(p[(f >= lo) & (f < hi)]) / total)
    return out


def _candidate_metrics(audio: np.ndarray, sr: int, control: np.ndarray | None = None) -> dict:
    x = np.asarray(audio, dtype=np.float32)
    result = {
        "lufs_i": float(integrated_lufs(x, sr)),
        "sample_peak_dbfs": float(sample_peak_dbfs(x)),
        "true_peak_dbtp": float(true_peak_db(x, sr)),
        "crest_db": float(crest_db(x)),
        "transient_crest_db": float(transient_crest_db(x, sr)),
        "crest_100ms_median_db": _event_crest(x, sr, 100),
        "crest_400ms_median_db": _event_crest(x, sr, 400),
        "stereo_ms_ratio_db": float(ms_ratio_db(x)),
        "pdf": _pdf_metrics(x),
        "spectral_share": _spectral_shares(x, sr),
    }
    if control is not None:
        a = np.asarray(control, dtype=np.float64).ravel()
        b = np.asarray(x, dtype=np.float64).ravel()
        n = min(len(a), len(b))
        a, b = a[:n], b[:n]
        d = b - a
        result["delta_rms_dbfs_vs_control"] = float(20.0 * np.log10(np.sqrt(np.mean(d * d)) + EPS))
        result["corr_vs_control"] = float(np.corrcoef(a, b)[0, 1]) if n > 2 else 1.0
    else:
        result["delta_rms_dbfs_vs_control"] = None
        result["corr_vs_control"] = 1.0
    return result


def _encode_mp3(src: Path, dst: Path) -> bool:
    ff = ffmpeg_path()
    if not ff or "libmp3lame" not in ffmpeg_encoders(ff):
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.stem + ".tmp.mp3")
    subprocess.run(
        [ff, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
         "-map_metadata", "-1", "-codec:a", "libmp3lame", "-b:a", "320k", str(tmp)],
        check=True,
    )
    os.replace(tmp, dst)
    return True


def _load_or_render_candidate(
    name: str,
    control: np.ndarray,
    sr: int,
    render_path: Path,
    state: dict,
    config: dict,
) -> np.ndarray:
    entry = state.get("candidates", {}).get(name, {})
    if render_path.exists() and entry.get("sha256") == sha256_file(render_path):
        y, ysr = sf.read(render_path, always_2d=True, dtype="float32")
        if int(ysr) == int(sr):
            return y

    if name == "Control_Round8A":
        y = control
    elif name == "HarmonicElasticity":
        params = config["harmonic_elasticity"]
        transfer = functools.partial(harmonic_elasticity, **params)
        y = oversampled_chunked(
            control, sr, transfer,
            oversample=int(config["oversample"]),
            chunk_seconds=float(config["chunk_seconds"]),
            pad_seconds=float(config["pad_seconds"]),
        )
        y = _normalize_lufs(y, sr, float(config["target_lufs"]))
    elif name == "PeakProtectedLoudness":
        params = config["peak_protected_loudness"]
        transfer = functools.partial(peak_protected_loudness, **params)
        y = oversampled_chunked(
            control, sr, transfer,
            oversample=int(config["oversample"]),
            chunk_seconds=float(config["chunk_seconds"]),
            pad_seconds=float(config["pad_seconds"]),
        )
        y = _normalize_lufs(y, sr, float(config["target_lufs"]))
    else:
        raise KeyError(name)

    if not np.all(np.isfinite(y)):
        raise RuntimeError(f"{name}: non-finite output")
    # Round 9 intentionally contains no safety limiter.  Abort instead of
    # silently introducing a second variable if the experiment clips.
    if true_peak_db(y, sr) >= -0.05:
        raise RuntimeError(f"{name}: true peak too close to 0 dBTP; refusing hidden limiting")

    _atomic_wav(render_path, y, sr)
    state.setdefault("candidates", {})[name] = {
        "status": "DONE",
        "sha256": sha256_file(render_path),
    }
    return y


def run_round9(input_path: str | Path, output_root: str | Path, target_lufs: float = -14.0) -> dict:
    input_path = Path(input_path).resolve()
    output_root = Path(output_root).resolve()
    if not input_path.exists():
        raise FileNotFoundError(input_path)

    config = json.loads(json.dumps(DEFAULT_CONFIG))
    config["target_lufs"] = float(target_lufs)
    input_hash = sha256_file(input_path)
    config_hash = _stable_hash(config)
    job = output_root / f"Round9_{input_path.stem}_{input_hash[:8]}_{config_hash[:8]}"
    decoded_dir = job / "DECODED"
    renders_dir = job / "RENDERS"
    blind_dir = job / "BLIND_TEST"
    internal_dir = job / "LAB_INTERNAL"
    for d in (decoded_dir, renders_dir, blind_dir, internal_dir):
        d.mkdir(parents=True, exist_ok=True)

    manifest_path = job / "manifest.json"
    manifest = {
        "schema": 1,
        "lab_version": LAB_VERSION,
        "experimental_only": True,
        "production_core_round9_lock_unchanged": True,
        "experiment_id": EXPERIMENT_ID,
        "input_path": str(input_path),
        "input_sha256": input_hash,
        "config": config,
        "config_sha256": config_hash,
    }
    if manifest_path.exists():
        old = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old.get("input_sha256") != input_hash or old.get("config_sha256") != config_hash:
            raise RuntimeError("existing Round 9 job manifest does not match input/config")
    _atomic_json(manifest_path, manifest)

    state_path = job / "state.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    except Exception:
        state = {}

    decoded = decoded_dir / "baseline_float.wav"
    if not decoded.exists():
        _decode_to_float_wav(input_path, decoded)
    source, sr = sf.read(decoded, always_2d=True, dtype="float32")
    if source.shape[1] != 2:
        raise ValueError("Round 9 blind experiment requires a stereo baseline")
    if len(source) < int(sr * 10):
        raise ValueError("Round 9 baseline must be at least 10 seconds")

    # Fairness anchor: every candidate starts from this exact level-matched PCM.
    control = _normalize_lufs(source, sr, float(config["target_lufs"]))
    if true_peak_db(control, sr) >= -0.05:
        raise RuntimeError("level-matched control has insufficient peak headroom; no hidden limiter will be added")

    candidates: dict[str, np.ndarray] = {}
    for name in CANDIDATE_ORDER:
        p = renders_dir / f"{name}.wav"
        candidates[name] = _load_or_render_candidate(name, control, sr, p, state, config)
        _atomic_json(state_path, state)

    metrics = {}
    for name in CANDIDATE_ORDER:
        metrics[name] = _candidate_metrics(
            candidates[name], sr,
            None if name == "Control_Round8A" else candidates["Control_Round8A"],
        )
    _atomic_json(internal_dir / "metrics_by_candidate.json", metrics)

    seed_material = f"{input_hash}|{config_hash}|{EXPERIMENT_ID}|blind"
    seed = int(hashlib.sha256(seed_material.encode("utf-8")).hexdigest()[:16], 16)
    perm = np.random.default_rng(seed).permutation(list(CANDIDATE_ORDER))
    mapping = dict(zip("ABC", [str(x) for x in perm]))
    _atomic_json(internal_dir / "blind_mapping.json", mapping)
    (job / "REVEAL_AFTER_LISTENING.txt").write_text(
        "DO NOT OPEN BEFORE LISTENING.\n\n" +
        "\n".join(f"ROUND9_{letter} = {name}" for letter, name in mapping.items()) + "\n",
        encoding="utf-8",
    )

    blind_metrics = {}
    mp3_ok = True
    for letter, name in mapping.items():
        wav_src = renders_dir / f"{name}.wav"
        wav_dst = blind_dir / f"ROUND9_{letter}.wav"
        if not wav_dst.exists() or sha256_file(wav_dst) != sha256_file(wav_src):
            tmp = wav_dst.with_name(wav_dst.stem + ".tmp.wav")
            shutil.copyfile(wav_src, tmp)
            os.replace(tmp, wav_dst)
        mp3_dst = blind_dir / f"ROUND9_{letter}_320kbps.mp3"
        if not mp3_dst.exists():
            mp3_ok = _encode_mp3(wav_src, mp3_dst) and mp3_ok
        blind_metrics[letter] = metrics[name]
    _atomic_json(blind_dir / "BLIND_METRICS.json", blind_metrics)

    instructions = (
        "PDRM Round 9 blind test — Harmonic Loudness / Surface Elasticity\n\n"
        "All candidates share the same decoded baseline and are level-matched to "
        f"{config['target_lufs']:.2f} LUFS-I before comparison.\n"
        "Judge repeated listening, not first-impression brightness.\n\n"
        "PASS cues:\n"
        "- surface gloss / elasticity without simply becoming brighter\n"
        "- body and upper partials feel like the same physical object\n"
        "- attack, groove and breathability remain intact\n\n"
        "FAIL cues:\n"
        "- hard / hot / breathless\n"
        "- recessed attack or flattened groove\n"
        "- merely brighter, fizzy or more forward\n\n"
        "Return a preference such as A > C > B, and note if all fail.\n"
        "Do not open REVEAL_AFTER_LISTENING.txt until the listening decision is fixed.\n"
    )
    (blind_dir / "BLIND_INSTRUCTIONS.txt").write_text(instructions, encoding="utf-8")

    zip_path = job / "PDRM_v0_6_Round9_HarmonicLoudness_BLIND.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for letter in "ABC":
            mp3 = blind_dir / f"ROUND9_{letter}_320kbps.mp3"
            wav = blind_dir / f"ROUND9_{letter}.wav"
            z.write(mp3 if mp3.exists() else wav, arcname=(mp3 if mp3.exists() else wav).name)
        z.write(blind_dir / "BLIND_INSTRUCTIONS.txt", arcname="BLIND_INSTRUCTIONS.txt")

    report = {
        "result": "READY_FOR_BLIND_LISTENING",
        "job_directory": str(job),
        "blind_zip": str(zip_path),
        "mp3_320_available": bool(mp3_ok),
        "target_lufs": float(config["target_lufs"]),
        "input_sha256": input_hash,
        "config_sha256": config_hash,
        "production_core_round9_lock_unchanged": True,
        "note": "This is an isolated experimental operator lab. It does not unlock or modify pdrm_engine max_round_allowed=8.",
    }
    _atomic_json(job / "ROUND9_LAB_REPORT.json", report)
    return report


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="PDRM isolated Round 9 blind operator lab")
    p.add_argument("input", type=Path, help="Round 8 A listening winner, WAV/FLAC/AIFF/MP3")
    p.add_argument("--output-root", type=Path, default=Path("Round9_Output"))
    p.add_argument("--target-lufs", type=float, default=-14.0)
    return p


def main() -> None:
    args = build_parser().parse_args()
    result = run_round9(args.input, args.output_root, target_lufs=args.target_lufs)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
