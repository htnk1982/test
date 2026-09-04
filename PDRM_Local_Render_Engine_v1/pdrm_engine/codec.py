from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import tempfile

import soundfile as sf

from .analysis import integrated_lufs, true_peak_db, sample_peak_dbfs, crest_db, transient_crest_db


class CodecUnavailable(RuntimeError):
    pass


def ffmpeg_path() -> str | None:
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def ffmpeg_encoders(ffmpeg: str | None = None) -> set[str]:
    ffmpeg = ffmpeg or ffmpeg_path()
    if not ffmpeg:
        return set()
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-encoders"],
        capture_output=True,
        text=True,
        check=False,
    )
    text = (proc.stdout or "") + "\n" + (proc.stderr or "")
    encoders: set[str] = set()
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0].startswith("A"):
            encoders.add(parts[1])
    return encoders


def available_profiles(ffmpeg: str | None = None) -> list[dict]:
    enc = ffmpeg_encoders(ffmpeg)
    profiles: list[dict] = []
    # These are representative distribution-stress probes. They are not claims
    # about any platform's exact current delivery codec.
    if "aac" in enc:
        profiles.append({"name":"aac_lc_256", "codec":"aac", "bitrate":"256k", "ext":"m4a"})
    if "libopus" in enc:
        profiles.append({"name":"opus_160", "codec":"libopus", "bitrate":"160k", "ext":"opus"})
    if "libmp3lame" in enc:
        profiles.append({"name":"mp3_320", "codec":"libmp3lame", "bitrate":"320k", "ext":"mp3"})
    return profiles


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def codec_roundtrip_qc(
    wav_path: str | Path,
    peak_gate_dbtp: float = -0.20,
    max_lufs_drift: float = 0.75,
    max_crest_drift_db: float = 1.25,
    profiles: list[dict] | None = None,
) -> dict:
    """Round-trip through available representative lossy codecs.

    PCM quality remains primary; codec QC is a hard-risk/tie-break layer as
    specified by PDRM v3. A packaged ffmpeg fallback removes the need for a
    separate manual ffmpeg installation on normal Windows setups.
    """
    wav_path = Path(wav_path).resolve()
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise CodecUnavailable("ffmpeg unavailable (system PATH and bundled fallback both failed)")
    if profiles is None:
        profiles = available_profiles(ffmpeg)
    if not profiles:
        raise CodecUnavailable("no supported AAC/Opus/MP3 encoders found in ffmpeg")

    original, sr = sf.read(str(wav_path), always_2d=True, dtype="float64")
    source = {
        "lufs_i": float(integrated_lufs(original, sr)),
        "true_peak_dbtp": float(true_peak_db(original, sr)),
        "sample_peak_dbfs": float(sample_peak_dbfs(original)),
        "crest_db": float(crest_db(original)),
        "transient_crest_db": float(transient_crest_db(original, sr)),
    }

    results = []
    overall = True
    with tempfile.TemporaryDirectory(prefix="pdrm_codec_qc_") as td:
        td = Path(td)
        for p in profiles:
            encoded = td / f"encoded.{p['ext']}"
            decoded = td / f"decoded_{p['name']}.wav"
            _run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(wav_path), "-map_metadata", "-1",
                "-c:a", p["codec"], "-b:a", p["bitrate"], str(encoded),
            ])
            _run([
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(encoded), "-map_metadata", "-1",
                "-c:a", "pcm_f32le", str(decoded),
            ])
            y, ysr = sf.read(str(decoded), always_2d=True, dtype="float64")
            metrics = {
                "lufs_i": float(integrated_lufs(y, ysr)),
                "true_peak_dbtp": float(true_peak_db(y, ysr)),
                "sample_peak_dbfs": float(sample_peak_dbfs(y)),
                "crest_db": float(crest_db(y)),
                "transient_crest_db": float(transient_crest_db(y, ysr)),
            }
            metrics["lufs_drift_lu"] = float(metrics["lufs_i"] - source["lufs_i"])
            metrics["crest_drift_db"] = float(metrics["crest_db"] - source["crest_db"])
            metrics["transient_crest_drift_db"] = float(metrics["transient_crest_db"] - source["transient_crest_db"])
            failures = []
            if metrics["true_peak_dbtp"] > float(peak_gate_dbtp):
                failures.append("CODEC_TRUE_PEAK_RISK")
            if abs(metrics["lufs_drift_lu"]) > float(max_lufs_drift):
                failures.append("CODEC_LOUDNESS_DRIFT")
            if abs(metrics["crest_drift_db"]) > float(max_crest_drift_db):
                failures.append("CODEC_CREST_DRIFT")
            passed = not failures
            overall = overall and passed
            results.append({
                "profile": dict(p),
                "encoded_bytes": int(encoded.stat().st_size),
                "decoded_metrics": metrics,
                "pass": passed,
                "failures": failures,
            })

    return {
        "available": True,
        "ffmpeg": str(ffmpeg),
        "source": source,
        "gates": {
            "peak_gate_dbtp": float(peak_gate_dbtp),
            "max_lufs_drift": float(max_lufs_drift),
            "max_crest_drift_db": float(max_crest_drift_db),
        },
        "profiles": results,
        "pass": bool(overall),
        "note": "Representative lossy-codec robustness test; not an exact platform codec emulation.",
    }
