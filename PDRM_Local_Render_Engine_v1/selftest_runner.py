from __future__ import annotations

from pathlib import Path
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parent
LOG = ROOT / "SELFTEST_DIAGNOSTIC.txt"


def safe_version(module_name: str) -> str:
    try:
        mod = __import__(module_name)
        return str(getattr(mod, "__version__", "unknown"))
    except Exception as exc:
        return f"IMPORT_FAILED: {exc!r}"


def collect_environment() -> list[str]:
    lines: list[str] = []
    lines.append("=== PDRM SELFTEST ENVIRONMENT ===")
    lines.append(f"cwd={Path.cwd()}")
    lines.append(f"root={ROOT}")
    lines.append(f"python={sys.executable}")
    lines.append(f"python_version={sys.version.replace(os.linesep, ' ')}")
    lines.append(f"platform={platform.platform()}")
    lines.append(f"machine={platform.machine()}")
    lines.append(f"processor={platform.processor()}")
    lines.append(f"temp={tempfile.gettempdir()}")
    lines.append(f"numpy={safe_version('numpy')}")
    lines.append(f"scipy={safe_version('scipy')}")
    lines.append(f"soundfile={safe_version('soundfile')}")
    lines.append(f"pyloudnorm={safe_version('pyloudnorm')}")
    lines.append(f"psutil={safe_version('psutil')}")
    lines.append(f"imageio_ffmpeg={safe_version('imageio_ffmpeg')}")
    lines.append(f"ffmpeg_on_PATH={shutil.which('ffmpeg')}")
    try:
        from pdrm_engine.codec import ffmpeg_path
        lines.append(f"pdrm_ffmpeg={ffmpeg_path()}")
    except Exception as exc:
        lines.append(f"pdrm_ffmpeg=IMPORT_FAILED: {exc!r}")
    try:
        probe = ROOT / ".selftest_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        lines.append("root_write_test=PASS")
    except Exception as exc:
        lines.append(f"root_write_test=FAIL: {exc!r}")
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "probe.txt"
            p.write_text("ok", encoding="utf-8")
            lines.append("temp_write_test=PASS")
    except Exception as exc:
        lines.append(f"temp_write_test=FAIL: {exc!r}")
    lines.append("")
    return lines


def main() -> int:
    os.chdir(ROOT)
    report = collect_environment()
    report.append("=== UNITTEST OUTPUT ===")
    cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    report.append("command=" + " ".join(cmd))
    report.append("")
    try:
        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            errors="replace",
        )
        output = proc.stdout or ""
        report.append(output)
        report.append("")
        report.append(f"return_code={proc.returncode}")
        failures = [
            line for line in output.splitlines()
            if line.startswith("FAIL:") or line.startswith("ERROR:") or " ... FAIL" in line or " ... ERROR" in line
        ]
        report.append("=== FAILURE INDEX ===")
        if failures:
            report.extend(failures)
        else:
            report.append("No FAIL/ERROR line detected. Inspect full unittest output above.")
        LOG.write_text("\n".join(report) + "\n", encoding="utf-8")
        print(output, end="" if output.endswith("\n") else "\n")
        print(f"\nDiagnostic log: {LOG}")
        if failures:
            print("Failure index:")
            for line in failures:
                print("  " + line)
        return int(proc.returncode)
    except Exception:
        report.append(traceback.format_exc())
        LOG.write_text("\n".join(report) + "\n", encoding="utf-8")
        print(traceback.format_exc())
        print(f"Diagnostic log: {LOG}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
