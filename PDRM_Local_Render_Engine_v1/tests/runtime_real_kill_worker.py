from __future__ import annotations

from pathlib import Path
import sys
import time

import pdrm_runtime.runner as runner_module
from pdrm_runtime.runtime_context import RuntimeContext as BaseRuntimeContext


class BlockingRuntimeContext(BaseRuntimeContext):
    def __init__(self, job_dir, marker):
        super().__init__(job_dir)
        self.marker = Path(marker)
        self.blocked = False

    def heartbeat(self, stage=None, progress=None, message=None, **kwargs):
        super().heartbeat(stage=stage, progress=progress, message=message, **kwargs)
        if stage == "SAFE_FRONTIER" and not self.blocked:
            self.blocked = True
            self.marker.write_text("SAFE_FRONTIER", encoding="utf-8")
            time.sleep(30.0)


def main():
    inp = Path(sys.argv[1])
    out = Path(sys.argv[2])
    work = Path(sys.argv[3])
    marker = Path(sys.argv[4])

    # Test-only replacement: production RuntimeContext remains unchanged.
    runner_module.RuntimeContext = lambda job_dir: BlockingRuntimeContext(job_dir, marker)
    runner = runner_module.ResilientRunner(work)
    try:
        runner.render(inp, out, {
            "target_lufs": -18.0,
            "true_peak_ceiling_dbtp": -1.0,
            "output_subtype": "PCM_24",
            "round9_enabled": False,
            "requested_round": 8,
        })
    finally:
        runner.close()


if __name__ == "__main__":
    main()
