from __future__ import annotations

from pathlib import Path
import argparse
import json

from .engine import run_job


class LocalRuntimeContext:
    max_round_allowed = 8

    def heartbeat(self, stage=None, progress=None, message=None, **kwargs):
        pct = "" if progress is None else f" {float(progress)*100:5.1f}%"
        msg = "" if not message else f" - {message}"
        print(f"[{stage}]{pct}{msg}")

    def is_cancelled(self):
        return False


def build_parser():
    p = argparse.ArgumentParser(description="PDRM Local Render Engine v1 MVP-0")
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--target-lufs", type=float, default=-9.0)
    p.add_argument("--tp", type=float, default=-2.0)
    p.add_argument("--subtype", default="PCM_24")
    p.add_argument("--report", type=Path)
    return p


def main():
    args = build_parser().parse_args()
    cfg = {
        "target_lufs": args.target_lufs,
        "true_peak_ceiling_dbtp": args.tp,
        "output_subtype": args.subtype,
        "round9_enabled": False,
        "requested_round": 8,
    }
    result = run_job(args.input, args.output, cfg, LocalRuntimeContext())
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
