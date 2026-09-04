from __future__ import annotations

from pathlib import Path
import argparse
import json

from .runner import ResilientRunner


def parser():
    p = argparse.ArgumentParser(description="PDRM resilient local runner")
    p.add_argument("--work-root", type=Path, default=Path(".pdrm_runtime"))
    sp = p.add_subparsers(dest="cmd", required=True)

    d = sp.add_parser("doctor")

    r = sp.add_parser("render")
    r.add_argument("input", type=Path)
    r.add_argument("output", type=Path)
    r.add_argument("--target-lufs", type=float, default=-9.0)
    r.add_argument("--tp", type=float, default=-2.0)

    v = sp.add_parser("verify")
    v.add_argument("output", type=Path)
    return p


def main():
    args = parser().parse_args()
    runner = ResilientRunner(args.work_root)
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
        else:
            raise SystemExit(2)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        runner.close()


if __name__ == "__main__":
    main()
