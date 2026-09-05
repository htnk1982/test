"""Read-only audit of an existing Round 9 job. No new mastering decision.

Uses the installed, unchanged Round 9 operators. Original audio and job files
are never written. Audit outputs/checkpoints live in a separate local directory.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import functools
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import traceback

for _key in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_key, "1")

import numpy as np
import soundfile as sf
from scipy import signal

from pdrm_engine.analysis import integrated_lufs, true_peak_db
from pdrm_engine.codec import ffmpeg_path, ffmpeg_encoders
from pdrm_operator_lab import operators as ops
from pdrm_operator_lab.round9 import _normalize_lufs

VERSION = "round9-path-audit-1.0"
NAMES = ("Control_Round8A", "HarmonicElasticity", "PeakProtectedLoudness")
BANDS = ((20, 80), (80, 200), (200, 1000), (1000, 4000),
         (4000, 8000), (8000, 12000), (12000, 16000), (16000, 20000))
# Numerical reconstruction tolerance, NOT an audibility threshold.
RECONSTRUCTION_TOLERANCE = 2.0 / (2 ** 23)


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def stable_hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode("utf-8")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(value, f, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def write_wav(path: Path, x, sr, subtype="PCM_24"):
    tmp = path.with_name(path.stem + ".partial.wav")
    sf.write(tmp, x, sr, subtype=subtype)
    # Windows _commit/FlushFileBuffers requires a writable handle. This is
    # only the audit's own temporary output, never an original audio file.
    with tmp.open("r+b") as f:
        os.fsync(f.fileno())
    os.replace(tmp, path)


def environment() -> dict:
    versions = {}
    for name in ("numpy", "scipy", "soundfile", "pyloudnorm", "psutil", "imageio-ffmpeg"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return {"python": sys.version, "platform": platform.platform(), "versions": versions,
            "audit_sha256": sha(Path(__file__)),
            "operators_sha256": sha(Path(ops.__file__))}


@contextmanager
def exclusive_lock(path: Path):
    """Kernel lock, automatically released on a process kill. No PID guessing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as f:
        if f.seek(0, 2) == 0:
            f.write(b"0")
            f.flush()
        f.seek(0)
        if os.name == "nt":
            import msvcrt
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("This audit is already running; do not start a second copy.") from exc
        else:
            import fcntl
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise RuntimeError("This audit is already running.") from exc
        try:
            yield
        finally:
            f.seek(0)
            if os.name == "nt":
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(f, fcntl.LOCK_UN)


class Progress:
    def __init__(self, root: Path):
        self.root, self.stage = root, "START"
        self.started = time.monotonic()
        self.stop = threading.Event()
        self.guard = threading.Lock()
        self.error = None
        self.thread = threading.Thread(target=self._loop, daemon=True)

    def _emit(self):
        with self.guard:
            record = {"stage": self.stage, "pid": os.getpid(), "heartbeat_unix": time.time(),
                      "elapsed_seconds": round(time.monotonic() - self.started, 1)}
            write_json(self.root / "heartbeat.json", record)
            print(f"[{record['stage']}] {record['elapsed_seconds']:.1f}s", flush=True)

    def _loop(self):
        while not self.stop.wait(2.0):
            try:
                self._emit()
            except Exception as exc:
                self.error = exc
                return

    def __enter__(self):
        self._emit()
        self.thread.start()
        return self

    def set(self, stage):
        if self.error:
            raise RuntimeError("Cannot persist heartbeat") from self.error
        self.stage = stage
        self._emit()

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=5)


def finite_db(value):
    return float(20 * np.log10(value)) if value > 0 else None


def pair_metrics(reference: Path, candidate: Path) -> dict:
    a, b = sf.info(reference), sf.info(candidate)
    if (a.frames, a.channels, a.samplerate) != (b.frames, b.channels, b.samplerate):
        raise ValueError("Cannot compare PCM with different frame counts/channels/sample rates")
    xx = yy = xy = dd = 0.0
    peak = 0.0
    count = 0
    with sf.SoundFile(reference) as fa, sf.SoundFile(candidate) as fb:
        while True:
            x = fa.read(65536, dtype="float64", always_2d=True)
            y = fb.read(65536, dtype="float64", always_2d=True)
            if not len(x):
                break
            d = y - x
            xx += float(np.sum(x*x)); yy += float(np.sum(y*y))
            xy += float(np.sum(x*y)); dd += float(np.sum(d*d))
            peak = max(peak, float(np.max(np.abs(d))))
            count += x.size
    if not count or xx <= 0:
        raise ValueError("Empty/silent PCM comparison")
    scale = xy / xx
    residual = max(0.0, yy - 2 * scale * xy + scale * scale * xx)
    return {"max_abs_delta": peak,
            "delta_rms_dbfs": finite_db(math.sqrt(dd/count)),
            "delta_rms_relative_db": finite_db(math.sqrt(dd/xx)),
            "best_linear_gain": scale,
            "gain_removed_residual_relative_db": finite_db(math.sqrt(residual/xx)),
            "note": "Numerical residual; not an audibility/fatigue score. No time alignment applied."}


def audio_metrics(path: Path) -> dict:
    x, sr = sf.read(path, dtype="float32", always_2d=True)
    if not np.all(np.isfinite(x)):
        raise ValueError("Non-finite PCM: " + path.name)
    loudness = integrated_lufs(x, sr)
    if not math.isfinite(loudness):
        raise ValueError("Unmeasurable loudness: " + path.name)
    tp = true_peak_db(x, sr)
    # Sum stereo channel powers; do not downmix to mono and hide phase cancellation.
    nper = min(8192, len(x))
    sums = None
    nframes = 0
    for start in range(0, len(x), 8 * sr):
        piece = x[start:start + 8 * sr].astype(np.float64)
        if len(piece) < nper:
            continue
        freq, psd = signal.welch(piece, sr, nperseg=nper, noverlap=nper//2, axis=0)
        w = 1 + (len(piece)-nper)//(nper//2)
        power = psd.mean(axis=1)
        sums = power*w if sums is None else sums + power*w
        nframes += w
    bands = {}
    if sums is not None:
        psd = sums / nframes
        for lo, hi in BANDS:
            mask = (freq >= lo) & (freq < min(hi, sr/2))
            power = float(np.sum(psd[mask]) * sr/nper)
            bands[f"{lo}_{hi}"] = 10 * math.log10(max(power, 1e-30))
    return {"lufs_i": float(loudness), "true_peak_dbtp_estimate": float(tp),
            "sample_peak_dbfs": finite_db(float(np.max(np.abs(x)))),
            "frames": len(x), "samplerate": sr, "channels": x.shape[1],
            "band_power_dbfs": bands}


def render_cached(x, sr, transfer, config, directory: Path, progress, name, fail_after=None):
    """Checkpoint each completed source-aligned chunk, not just a whole track."""
    directory.mkdir(parents=True, exist_ok=True)
    core = max(1, round(config["chunk_seconds"] * sr))
    pad = max(0, round(config["pad_seconds"] * sr))
    osf = int(config["oversample"])
    y = np.empty_like(x, dtype=np.float32)
    total = math.ceil(len(x)/core)
    for i, start in enumerate(range(0, len(x), core)):
        end = min(len(x), start + core)
        p = directory / f"{i:06d}.npy"
        marker = p.with_suffix(".json")
        block = None
        if p.exists() and marker.exists():
            m = read_json(marker)
            if m.get("sha256") == sha(p):
                z = np.load(p, allow_pickle=False)
                if z.shape == (end-start, x.shape[1]) and np.all(np.isfinite(z)):
                    block = z
        if block is None:
            left, right = max(0, start-pad), min(len(x), end+pad)
            # One chunk plus both halos. A single inner chunk reproduces the
            # unchanged original helper's up/filter/transfer/down path exactly.
            seg = x[left:right]
            z = ops.oversampled_chunked(seg, sr, transfer, oversample=osf,
                                        chunk_seconds=(len(seg)+sr)/sr,
                                        pad_seconds=config["pad_seconds"])
            block = z[start-left:end-left]
            if not np.all(np.isfinite(block)):
                raise ValueError("Non-finite chunk")
            tmp = p.with_suffix(".partial.npy")
            with tmp.open("wb") as f:
                np.save(f, block, allow_pickle=False)
                f.flush(); os.fsync(f.fileno())
            os.replace(tmp, p)
            write_json(marker, {"sha256": sha(p), "chunk": i, "frames": len(block)})
            if fail_after is not None and i == fail_after:
                raise RuntimeError("INJECTED_AUDIT_STOP")
        y[start:end] = block
        progress.set(f"{name} {i+1}/{total}")
    return y


def filter_probe() -> dict:
    """Synthetic path measurement, not a measurement of the user's recording."""
    rows = []
    for sr in (44100, 48000):
        t = np.arange(sr, dtype=np.float64) / sr
        for hz in (100, 1000, 8000, 12000, 16000, 18000, 20000, 21000, 22000):
            if hz >= sr * 0.49:
                continue
            x = (0.1*np.sin(2*np.pi*hz*t)).astype(np.float32)[:, None]
            y = ops.oversampled_chunked(x, sr, ops.control, oversample=4)
            a, b = x[sr//10:-sr//10], y[sr//10:-sr//10]
            gain = 10 * np.log10(float(np.mean(b.astype(float)**2)) /
                                 float(np.mean(a.astype(float)**2)))
            rows.append({"sr": sr, "hz": hz, "roundtrip_gain_db": float(gain)})
    return {"scope": "synthetic_steady_sines_filter_only_not_user_audio",
            "environment": environment(), "normalization": "none",
            "oversample": 4, "kaiser_beta": 10.5, "rows": rows}


def run_ffmpeg(ff, args, log: Path):
    with log.open("wb") as f:
        subprocess.run([ff, "-y", "-hide_banner", "-loglevel", "error", *args],
                       stdout=f, stderr=subprocess.STDOUT, check=True, timeout=300)


def decode_mp3(ff, src: Path, dst: Path, log: Path):
    tmp = dst.with_name(dst.stem + ".partial.wav")
    run_ffmpeg(ff, ["-i", str(src), "-c:a", "pcm_f32le", str(tmp)], log)
    os.replace(tmp, dst)


def default_output_root():
    base = os.environ.get("LOCALAPPDATA")
    return ((Path(base) if base else Path.home()/".local"/"share") /
            "PDRM_Local_Render_Engine_v1"/"round9_path_audit")


def job_files(job: Path) -> list[Path]:
    files = [job/"manifest.json", job/"state.json", job/"DECODED"/"baseline_float.wav",
             job/"LAB_INTERNAL"/"blind_mapping.json"]
    files += [job/"RENDERS"/(name+".wav") for name in NAMES]
    for p in files:
        if not p.is_file():
            raise FileNotFoundError("Required original Round 9 artifact missing: " + str(p))
    files += sorted((job/"BLIND_TEST").glob("ROUND9_*.wav"))
    files += sorted((job/"BLIND_TEST").glob("ROUND9_*_320kbps.mp3"))
    return files


def audit_job(job: Path, output_root: Path | None = None, codec=True) -> dict:
    job = Path(job).resolve()
    if job.is_file():
        job = job.parent
    output_root = Path(output_root or default_output_root()).resolve()
    if output_root == job or job in output_root.parents:
        raise ValueError("Audit output must be outside the original Round 9 job")
    files = job_files(job)
    snapshot = {str(p.relative_to(job)): sha(p) for p in files}
    manifest = read_json(job/"manifest.json")
    cfg = manifest["config"]
    if int(cfg["oversample"]) != 4:
        raise ValueError("This diagnostic is scoped to the agreed 4x Round 9 experiment")
    mapping = read_json(job/"LAB_INTERNAL"/"blind_mapping.json")
    if set(mapping) != set("ABC") or set(mapping.values()) != set(NAMES):
        raise ValueError("Invalid blind mapping")
    state = read_json(job/"state.json")
    for name in NAMES:
        p = job/"RENDERS"/(name+".wav")
        if state.get("candidates", {}).get(name, {}).get("sha256") != sha(p):
            raise ValueError("Saved render differs from its checkpoint: " + name)
    for letter, name in mapping.items():
        p = job/"BLIND_TEST"/f"ROUND9_{letter}.wav"
        if p.exists() and sha(p) != sha(job/"RENDERS"/(name+".wav")):
            raise ValueError("Blind WAV mapping mismatch: " + letter)

    env = environment()
    ff = ffmpeg_path() if codec else None
    ff_version = None
    if ff:
        ff_version = subprocess.run([ff, "-version"], capture_output=True,
                                    text=True, errors="replace", check=True, timeout=20).stdout.splitlines()[0]
    key = stable_hash({"snapshot": snapshot, "config": cfg, "environment": env,
                       "ffmpeg": ff_version, "codec": codec, "version": VERSION})[:20]
    out = output_root / ("audit_" + key)
    out.mkdir(parents=True, exist_ok=True)
    report_path = out/"AUDIT_REPORT.json"
    with exclusive_lock(out/"audit.lock"), Progress(out) as progress:
        report = {"schema": 1, "audit_version": VERSION, "status": "RUNNING",
                  "scope": "numerical_path_audit_not_listening_quality_approval",
                  "environment": env, "config": cfg, "mapping": mapping,
                  "source_snapshot": snapshot, "audit_directory": str(out),
                  "winner_audio_modified": False, "production_core_modified": False,
                  "listening_request": "NONE_AT_THIS_STAGE", "ffmpeg_version": ff_version}
        try:
            if report_path.exists():
                old = read_json(report_path)
                generated = old.get("generated_hashes", {})
                if old.get("status") == "AUDIT_COMPLETE" and generated and all(
                    (out/p).is_file() and sha(out/p) == h for p, h in generated.items()
                ):
                    progress.set("AUDIT_REUSED")
                    return old
            write_json(report_path, report)
            progress.set("READ_AND_NORMALIZE_BASELINE")
            info = sf.info(job/"DECODED"/"baseline_float.wav")
            import psutil
            # Guard the one full float32 baseline plus pyloudnorm working buffers.
            if info.frames * info.channels * 4 * 14 > psutil.virtual_memory().available:
                raise MemoryError("Insufficient available RAM for this audit; no source was changed")
            source, sr = sf.read(job/"DECODED"/"baseline_float.wav", dtype="float32", always_2d=True)
            if source.shape[1] != 2 or not np.all(np.isfinite(source)):
                raise ValueError("Stereo finite baseline required")
            x = _normalize_lufs(source, sr, float(cfg["target_lufs"]))
            del source
            dry_check = out/"dry_reconstruction.wav"
            write_wav(dry_check, x, sr)
            dry = job/"RENDERS"/"Control_Round8A.wav"
            winner = job/"RENDERS"/"HarmonicElasticity.wav"
            dry_diff = pair_metrics(dry, dry_check)
            if dry_diff["max_abs_delta"] > RECONSTRUCTION_TOLERANCE:
                raise ValueError("Control cannot be reproduced from saved baseline/config in this environment")
            filtered = render_cached(x, sr, ops.control, cfg, out/"chunks_filter", progress, "FILTER_ONLY")
            raw_filter_lufs = integrated_lufs(filtered, sr)
            f = _normalize_lufs(filtered, sr, float(cfg["target_lufs"]))
            filter_wav = out/"filter_only_matched.wav"
            write_wav(filter_wav, f, sr)
            del filtered, f
            transfer = functools.partial(ops.harmonic_elasticity, **cfg["harmonic_elasticity"])
            c = render_cached(x, sr, transfer, cfg, out/"chunks_c", progress, "VERIFY_CURRENT_C")
            c = _normalize_lufs(c, sr, float(cfg["target_lufs"]))
            c_check = out/"c_reconstruction.wav"
            write_wav(c_check, c, sr)
            del c, x
            c_diff = pair_metrics(winner, c_check)
            report["reconstruction"] = {"dry": dry_diff, "C": c_diff,
                                         "tolerance": RECONSTRUCTION_TOLERANCE}
            if c_diff["max_abs_delta"] > RECONSTRUCTION_TOLERANCE:
                raise ValueError("Current C cannot be reproduced; refusing causal attribution to a different render")
            source_path = Path(manifest.get("input_path", ""))
            report["original_input_hash_verified"] = bool(source_path.is_file() and sha(source_path) == manifest.get("input_sha256"))
            paths = {"Dry": dry, "FilterOnly": filter_wav, "CurrentC": winner}
            metrics = {}
            for name, p in paths.items():
                progress.set("PCM_METRICS_"+name)
                metrics[name] = audio_metrics(p)
            report["pcm_metrics"] = metrics
            report["filter_only_matching_gain_db"] = float(cfg["target_lufs"]-raw_filter_lufs)
            report["pcm_pair_deltas"] = {
                "filter_minus_dry": pair_metrics(dry, filter_wav),
                "C_minus_filter": pair_metrics(filter_wav, winner),
                "C_minus_dry": pair_metrics(dry, winner)}
            report["band_deltas_db"] = {
                tag: {b: metrics[to]["band_power_dbfs"][b]-metrics[frm]["band_power_dbfs"][b]
                      for b in metrics[frm]["band_power_dbfs"]}
                for tag, frm, to in (("filter_minus_dry", "Dry", "FilterOnly"),
                                     ("C_minus_filter", "FilterOnly", "CurrentC"))}
            progress.set("SYNTHETIC_FILTER_PROBE")
            report["synthetic_filter_probe"] = filter_probe()
            codec_dir = out/"codec"
            codec_dir.mkdir(exist_ok=True)
            report["codec"] = {"available": False}
            if codec and ff and "libmp3lame" in ffmpeg_encoders(ff):
                endpoint = {}
                existing = {}
                for letter, name in mapping.items():
                    src = job/"BLIND_TEST"/f"ROUND9_{letter}_320kbps.mp3"
                    if src.exists():
                        progress.set("MEASURE_LISTENED_MP3_"+letter)
                        dst = codec_dir/f"original_{letter}_decoded.wav"
                        decode_mp3(ff, src, dst, codec_dir/f"original_{letter}.log")
                        existing[letter] = {"candidate": name, "file_sha256": sha(src), **audio_metrics(dst)}
                # Fresh matched encode chain separates endpoint differences from
                # potentially different old ffmpeg builds. Never replace old MP3s.
                for name, p in paths.items():
                    progress.set("MATCHED_CODEC_"+name)
                    mp3 = codec_dir/f"matched_{name}.mp3"
                    run_ffmpeg(ff, ["-i", str(p), "-map_metadata", "-1", "-codec:a",
                                    "libmp3lame", "-b:a", "320k", str(mp3)], codec_dir/f"{name}.log")
                    decoded = codec_dir/f"matched_{name}_decoded.wav"
                    decode_mp3(ff, mp3, decoded, codec_dir/f"{name}_decode.log")
                    endpoint[name] = audio_metrics(decoded)
                spread = max(m["lufs_i"] for m in endpoint.values()) - min(m["lufs_i"] for m in endpoint.values())
                old_spread = (max(m["lufs_i"] for m in existing.values()) - min(m["lufs_i"] for m in existing.values())) if len(existing) == 3 else None
                report["codec"] = {"available": True, "existing_listened_mp3": existing,
                                    "fresh_same_encoder": endpoint,
                                    "fresh_lufs_spread_lu": spread, "original_ABC_lufs_spread_lu": old_spread,
                                    "level_recheck_flag": bool(spread > 0.10 or (old_spread is not None and old_spread > 0.10)),
                                    "threshold_note": "0.10 LU is an engineering comparison tolerance, not a proven perceptual threshold.",
                                    "provenance_note": "Existing MP3 assignment follows saved filenames/mapping; old encoder provenance is unavailable."}
            report["source_unchanged"] = snapshot == {str(p.relative_to(job)): sha(p) for p in files}
            if not report["source_unchanged"]:
                raise RuntimeError("Original job changed during audit; stop before drawing conclusions")
            report["status"] = "AUDIT_COMPLETE"
            report["interpretation_limits"] = [
                "C remains the reported listening winner; this tool does not rank candidates.",
                "Filter-only and C share the original resampling path and separate final LUFS matching.",
                "Residual energies are not additive percentages of the subjective improvement.",
                "No fatigue, gloss, audibility, or mastering-SOTA claim follows from these measurements.",
                "A rebuilt C match validates this baseline/config numerically, not any upstream MP3 history."]
            generated = [dry_check, filter_wav, c_check] + sorted(codec_dir.glob("*.wav")) + sorted(codec_dir.glob("*.mp3"))
            report["generated_hashes"] = {str(p.relative_to(out)): sha(p) for p in generated}
            write_json(report_path, report)
            write_report_md(out/"AUDIT_REPORT.md", report)
            progress.set("AUDIT_COMPLETE_NO_LISTENING_REQUIRED_YET")
            return report
        except BaseException as exc:
            report.update(status="ERROR", error=repr(exc), traceback=traceback.format_exc(),
                          failed_stage=progress.stage)
            try:
                write_json(report_path, report)
                write_report_md(out/"AUDIT_REPORT.md", report)
            except Exception:
                print("Could not save audit error report: " + traceback.format_exc(), file=sys.stderr)
            raise


def write_report_md(path: Path, r):
    lines = ["# Round 9 経路監査", "", "状態: **"+r["status"]+"**", "",
             "Cの音・本番core・既存Round9出力は変更しない。これは聴感品質の合格証ではない。", ""]
    if r.get("error"):
        lines += ["## 停止理由", r["error"], "", "同じ処理を連打せず、AUDIT_REPORT.jsonを確認する。"]
    if "pcm_metrics" in r:
        lines += ["## PCM", "", "| 経路 | LUFS-I | TP推定 dBTP |", "|---|---:|---:|"]
        for name, m in r["pcm_metrics"].items():
            lines.append(f"| {name} | {m['lufs_i']:.6f} | {m['true_peak_dbtp_estimate']:.4f} |")
        lines += ["", "## LUFS整合後の残差", "", "| 差 | RMS相対 dB |", "|---|---:|"]
        for name, m in r["pcm_pair_deltas"].items():
            value = m["delta_rms_relative_db"]
            lines.append(f"| {name} | {value if value is not None else 'exact zero'} |")
    if r.get("codec", {}).get("available"):
        lines += ["", "## 実際の試聴MP3を復号した結果", "", "| 文字 | 処理 | LUFS-I | TP推定 |", "|---|---|---:|---:|"]
        for letter, m in r["codec"]["existing_listened_mp3"].items():
            lines.append(f"| {letter} | {m['candidate']} | {m['lufs_i']:.6f} | {m['true_peak_dbtp_estimate']:.4f} |")
        lines += ["", "再エンコードした3経路のLUFS差: " + str(r["codec"]["fresh_lufs_spread_lu"]),
                  "音量差再確認フラグ: " + str(r["codec"]["level_recheck_flag"])]
    lines += ["", "## 次の扱い", "Cを保持する。数値だけで疲れなさの原因を確定しない。",
              "追加試聴は今は不要。AUDIT_REPORT.jsonを共有し、比較が必要な場合だけ短区間へ絞る。", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", type=Path, help="Existing Round9 job folder or its manifest.json")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--probe-only", type=Path, help="Write synthetic filter probe JSON; no user audio")
    args = parser.parse_args()
    if args.probe_only:
        r = filter_probe()
        write_json(args.probe_only, r)
        for row in r["rows"]:
            print(f"FILTER_PROBE sr={row['sr']} hz={row['hz']} gain_db={row['roundtrip_gain_db']:.6f}")
        return
    if not args.job:
        parser.error("Drag the existing Round9 job folder or its manifest.json onto round9_path_audit.cmd")
    report = audit_job(args.job, args.output_root)
    print("\nReport: " + str(Path(report["audit_directory"])/"AUDIT_REPORT.json"), flush=True)
    print("No listening task now. Keep Current C unchanged.", flush=True)


if __name__ == "__main__":
    main()
