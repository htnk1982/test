from __future__ import annotations

from pathlib import Path
import argparse
import json

from pdrm_engine.codec import codec_roundtrip_qc, CodecUnavailable
from .runner import ResilientRunner


def parser():
    p = argparse.ArgumentParser(description="PDRM resilient local runner")
    p.add_argument("--work-root", type=Path, default=Path(".pdrm_runtime"))
    sp = p.add_subparsers(dest="cmd", required=True)

    sp.add_parser("doctor")

    r = sp.add_parser("render")
    r.add_argument("input", type=Path)
    r.add_argument("output", type=Path)
    r.add_argument("--target-lufs", type=float, default=-9.0)
    r.add_argument("--tp", type=float, default=-2.0)

    v = sp.add_parser("verify")
    v.add_argument("output", type=Path)

    c = sp.add_parser("codec-qc")
    c.add_argument("output", type=Path)
    c.add_argument("--codec-peak-gate", type=float, default=-0.20)
    c.add_argument("--max-lufs-drift", type=float, default=0.75)
    c.add_argument("--max-crest-drift", type=float, default=1.25)
    return p


def main():
    args = parser().parse_args()
    runner = ResilientRunner(args.work_root)
    exit_code = 0
    try:
        if args.cmd == "doctor":
            result = runner.doctor()
        elif args.cmd == "render":
            result = runner.render(args.input, args.output, {
                "target_lufs": args.target_lufs,
                "true_peak_ceiling_dbtp": args.tp,
                "output_subtype": "PCM_24",
                "round9_enabled": False,
                "requested_round": 8,
            })
        elif args.cmd == "verify":
            result = runner.verify(args.output)
            exit_code = 0 if result.get("ok") else 3
        elif args.cmd == "codec-qc":
            try:
                result = codec_roundtrip_qc(
                    args.output,
                    peak_gate_dbtp=args.codec_peak_gate,
                    max_lufs_drift=args.max_lufs_drift,
                    max_crest_drift_db=args.max_crest_drift,
                )
                exit_code = 0 if result.get("pass") else 4
            except CodecUnavailable as exc:
                result = {"available": False, "pass": False, "error": str(exc)}
                exit_code = 5
        else:
            raise SystemExit(2)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        runner.close()
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
