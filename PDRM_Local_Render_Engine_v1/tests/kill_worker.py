from __future__ import annotations

from pathlib import Path
import sys
import time

from pdrm_engine.engine import run_job


class BlockingRuntime:
    max_round_allowed = 8

    def __init__(self, marker: Path):
        self.marker = marker
        self.blocked = False

    def heartbeat(self, stage=None, progress=None, message=None, **kwargs):
        if stage == "SAFE_FRONTIER" and not self.blocked:
            self.blocked = True
            self.marker.write_text("SAFE_FRONTIER", encoding="utf-8")
            # Parent test deliberately kills this process during the sleep.
            time.sleep(30.0)

    def is_cancelled(self):
        return False


def main():
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])
    marker = Path(sys.argv[3])
    run_job(inp, out, {
        "target_lufs": -18.0,
        "true_peak_ceiling_dbtp": -1.0,
        "output_subtype": "PCM_24",
    }, BlockingRuntime(marker))


if __name__ == "__main__":
    main()
