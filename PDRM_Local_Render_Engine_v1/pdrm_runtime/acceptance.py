from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import soundfile as sf

from pdrm_engine.codec import available_profiles, codec_roundtrip_qc, CodecUnavailable
from pdrm_engine.io_utils import pcm_sha256, sha256_file
from .runner import ResilientRunner
from .util import atomic_write_json, now_iso


def _run_cli(cmd: list[str], log_path: Path, timeout: float | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "COMMAND:\n" + " ".join(cmd) + "\n\nSTDOUT:\n" + (proc.stdout or "") +
        "\n\nSTDERR:\n" + (proc.stderr or ""),
        encoding="utf-8",
    )
    return proc


def _find_heartbeat(work_root: Path) -> tuple[Path | None, dict | None]:
    newest = None
    newest_mtime = -1.0
    for p in work_root.glob("jobs/*/heartbeat.json"):
        try:
            mtime = p.stat().st_mtime
            if mtime > newest_mtime:
                data = json.loads(p.read_text(encoding="utf-8"))
                newest = (p, data)
                newest_mtime = mtime
        except Exception:
            pass
    return newest if newest else (None, None)


def _kill_at_safe_frontier(
    input_path: Path,
    output_path: Path,
    work_root: Path,
    target_lufs: float,
    tp: float,
    timeout_seconds: float,
    log_path: Path,
) -> dict:
    cmd = [
        sys.executable, "-m", "pdrm_runtime.cli",
        "--work-root", str(work_root),
        "render", str(input_path), str(output_path),
        "--target-lufs", str(target_lufs), "--tp", str(tp),
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    deadline = time.time() + float(timeout_seconds)
    seen = None
    try:
        while time.time() < deadline:
            hb_path, hb = _find_heartbeat(work_root)
            if hb:
                seen = hb
                if hb.get("stage") == "SAFE_FRONTIER":
                    proc.kill()
                    stdout, stderr = proc.communicate(timeout=15)
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text(
                        "COMMAND:\n" + " ".join(cmd) +
                        "\n\nKILLED_AT:\n" + json.dumps(hb, ensure_ascii=False, indent=2) +
                        "\n\nSTDOUT:\n" + (stdout or "") +
                        "\n\nSTDERR:\n" + (stderr or ""),
                        encoding="utf-8",
                    )
                    return {
                        "reached_safe_frontier": True,
                        "killed": True,
                        "child_returncode": proc.returncode,
                        "final_exists_after_kill": output_path.exists(),
                        "heartbeat": hb,
                    }
            if proc.poll() is not None:
                stdout, stderr = proc.communicate()
                log_path.write_text(
                    "COMMAND:\n" + " ".join(cmd) +
                    "\n\nPROCESS_EXITED_BEFORE_KILL\n\nSTDOUT:\n" + (stdout or "") +
                    "\n\nSTDERR:\n" + (stderr or ""),
                    encoding="utf-8",
                )
                return {
                    "reached_safe_frontier": False,
                    "killed": False,
                    "child_returncode": proc.returncode,
                    "final_exists_after_kill": output_path.exists(),
                    "last_heartbeat": seen,
                }
            time.sleep(0.04)
        proc.kill()
        stdout, stderr = proc.communicate(timeout=15)
        log_path.write_text(
            "COMMAND:\n" + " ".join(cmd) +
            "\n\nTIMEOUT\n\nSTDOUT:\n" + (stdout or "") +
            "\n\nSTDERR:\n" + (stderr or ""),
            encoding="utf-8",
        )
        return {
            "reached_safe_frontier": False,
            "killed": True,
            "timeout": True,
            "final_exists_after_kill": output_path.exists(),
            "last_heartbeat": seen,
        }
    finally:
        if proc.poll() is None:
            proc.kill()
            try:
                proc.wait(timeout=10)
            except Exception:
                pass


def run_acceptance(
    input_path: str | Path,
    acceptance_root: str | Path,
    target_lufs: float = -14.0,
    tp: float = -2.0,
    minimum_duration_seconds: float = 180.0,
    kill_timeout_seconds: float = 180.0,
    codec_profiles: list[dict] | None = None,
    keep_clean_copy: bool = False,
) -> dict:
    input_path = Path(input_path).resolve()
    acceptance_root = Path(acceptance_root).resolve()
    acceptance_root.mkdir(parents=True, exist_ok=True)

    info = sf.info(str(input_path))
    input_hash_before = sha256_file(input_path)
    duration_ok = float(info.duration) >= float(minimum_duration_seconds)

    run_id = hashlib.sha256(
        (input_hash_before + f"|{target_lufs}|{tp}|{time.time_ns()}").encode("utf-8")
    ).hexdigest()[:12]
    root = acceptance_root / f"accept_{input_path.stem}_{run_id}"
    root.mkdir(parents=True, exist_ok=False)
    logs = root / "logs"
    logs.mkdir()

    killed_output = root / "restart_output.wav"
    kill_work = root / "kill_work"
    kill_result = _kill_at_safe_frontier(
        input_path, killed_output, kill_work, target_lufs, tp,
        kill_timeout_seconds, logs / "01_kill.log",
    )
    no_final_after_kill = not killed_output.exists()

    config = {
        "target_lufs": float(target_lufs),
        "true_peak_ceiling_dbtp": float(tp),
        "output_subtype": "PCM_24",
        "round9_enabled": False,
        "requested_round": 8,
    }

    restart_runner = ResilientRunner(kill_work)
    try:
        restart_result = restart_runner.render(input_path, killed_output, config)
        verify_result = restart_runner.verify(killed_output)
        rerun_result = restart_runner.render(input_path, killed_output, config)
    finally:
        restart_runner.close()

    clean_output = root / "clean_output.wav"
    clean_work = root / "clean_work"
    clean_runner = ResilientRunner(clean_work)
    try:
        clean_result = clean_runner.render(input_path, clean_output, config)
        clean_verify = clean_runner.verify(clean_output)
    finally:
        clean_runner.close()

    restart_pcm = pcm_sha256(killed_output) if killed_output.exists() else None
    clean_pcm = pcm_sha256(clean_output) if clean_output.exists() else None
    deterministic_pcm = bool(restart_pcm and restart_pcm == clean_pcm)

    codec_result: dict
    try:
        codec_result = codec_roundtrip_qc(killed_output, profiles=codec_profiles)
    except CodecUnavailable as exc:
        codec_result = {"available": False, "pass": False, "error": str(exc)}

    input_hash_after = sha256_file(input_path)
    input_unchanged = input_hash_before == input_hash_after
    idempotent = rerun_result.get("runtime_status") == "IDEMPOTENT_SKIP"
    whole_kill_pass = bool(
        kill_result.get("reached_safe_frontier")
        and kill_result.get("killed")
        and no_final_after_kill
    )

    gates = {
        "duration_3min_or_configured_minimum": duration_ok,
        "input_unchanged": input_unchanged,
        "whole_process_kill_no_final": whole_kill_pass,
        "restart_render_succeeded": restart_result.get("runtime_status") in {"SUCCEEDED", "RECOVERED"},
        "restart_verify": bool(verify_result.get("ok")),
        "identical_rerun_no_dsp": idempotent,
        "clean_second_render_succeeded": clean_result.get("runtime_status") in {"SUCCEEDED", "RECOVERED"},
        "clean_verify": bool(clean_verify.get("ok")),
        "deterministic_pcm_hash": deterministic_pcm,
        "codec_qc_available": bool(codec_result.get("available")),
        "codec_qc_pass": bool(codec_result.get("pass")),
        "round9_still_locked": (
            restart_result.get("sidecar", {}).get("round9_executed") is False
            and clean_result.get("sidecar", {}).get("round9_executed") is False
        ),
    }
    passed = all(gates.values())

    report = {
        "schema": 1,
        "created_at": now_iso(),
        "result": "PASS" if passed else "FAIL",
        "round9_unlock_candidate": bool(passed),
        "input": {
            "path": str(input_path),
            "sha256_before": input_hash_before,
            "sha256_after": input_hash_after,
            "samplerate": int(info.samplerate),
            "channels": int(info.channels),
            "duration_seconds": float(info.duration),
        },
        "requested_profile": {"target_lufs": float(target_lufs), "tp_dbtp": float(tp)},
        "gates": gates,
        "kill_test": kill_result,
        "restart_result": restart_result,
        "verify_result": verify_result,
        "rerun_result": rerun_result,
        "clean_result": clean_result,
        "clean_verify": clean_verify,
        "pcm_hashes": {"restart": restart_pcm, "clean": clean_pcm},
        "codec_qc": codec_result,
        "acceptance_directory": str(root),
        "note": "PASS is evidence for the local execution/codec gate only; it is not a listening-quality approval and does not itself modify the Round 9 hard lock.",
    }

    atomic_write_json(root / "ACCEPTANCE_REPORT.json", report)
    md_lines = [
        "# PDRM Local Render Engine v1 — Real Audio Acceptance",
        "",
        f"**Result: {report['result']}**",
        "",
        f"Input: `{input_path}`",
        f"Duration: {info.duration:.2f} s",
        f"Target: {target_lufs:.2f} LUFS / {tp:.2f} dBTP",
        "",
        "## Gates",
        "",
    ]
    for key, value in gates.items():
        md_lines.append(f"- {'PASS' if value else 'FAIL'} — `{key}`")
    md_lines.extend([
        "",
        "## Determinism",
        "",
        f"- restart PCM SHA-256: `{restart_pcm}`",
        f"- clean PCM SHA-256: `{clean_pcm}`",
        "",
        "## Round 9",
        "",
        "This report does **not** unlock Round 9 by itself. It is the private local evidence to review before changing the hard lock.",
    ])
    (root / "ACCEPTANCE_REPORT.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    if not keep_clean_copy and clean_output.exists():
        clean_output.unlink()
        clean_output.with_name(clean_output.name + ".pdrm.json").unlink(missing_ok=True)

    return report


def build_parser():
    p = argparse.ArgumentParser(description="Run PDRM pre-Round-9 acceptance on private local real audio")
    p.add_argument("input", type=Path)
    p.add_argument("--acceptance-root", type=Path, default=Path(".pdrm_acceptance"))
    p.add_argument("--target-lufs", type=float, default=-14.0)
    p.add_argument("--tp", type=float, default=-2.0)
    p.add_argument("--minimum-duration", type=float, default=180.0)
    p.add_argument("--kill-timeout", type=float, default=180.0)
    p.add_argument("--keep-clean-copy", action="store_true")
    return p


def main():
    args = build_parser().parse_args()
    report = run_acceptance(
        args.input,
        args.acceptance_root,
        target_lufs=args.target_lufs,
        tp=args.tp,
        minimum_duration_seconds=args.minimum_duration,
        kill_timeout_seconds=args.kill_timeout,
        keep_clean_copy=args.keep_clean_copy,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(0 if report["result"] == "PASS" else 6)


if __name__ == "__main__":
    main()
