from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import numpy as np
import soundfile as sf

from pdrm_engine.io_utils import pcm_sha256
from pdrm_runtime.runner import ResilientRunner


def synth(sr=48000, seconds=5.0, amp=0.025):
    t = np.arange(int(sr*seconds), dtype=np.float64)/sr
    mono = amp*(0.78*np.sin(2*np.pi*109*t) + 0.21*np.sin(2*np.pi*1409*t))
    return np.stack([mono, mono*0.99], axis=1).astype(np.float32)


class WholeRuntimeHardKillTests(unittest.TestCase):
    def test_real_core_runtime_kill_restart_equals_clean_pcm(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inp = root/"input.wav"
            out = root/"restarted.wav"
            work = root/"work"
            marker = root/"marker.txt"
            sf.write(inp, synth(), 48000, subtype="FLOAT")

            worker = Path(__file__).with_name("runtime_real_kill_worker.py")
            proc = subprocess.Popen([
                sys.executable, str(worker), str(inp), str(out), str(work), str(marker)
            ])
            deadline = time.time() + 20.0
            while time.time() < deadline and not marker.exists() and proc.poll() is None:
                time.sleep(0.05)
            self.assertTrue(marker.exists(), "whole runtime did not reach SAFE_FRONTIER")
            proc.kill()
            proc.wait(timeout=10)
            self.assertFalse(out.exists(), "hard-killed runtime published a final output")

            cfg = {
                "target_lufs": -18.0,
                "true_peak_ceiling_dbtp": -1.0,
                "output_subtype": "PCM_24",
                "round9_enabled": False,
                "requested_round": 8,
            }
            runner = ResilientRunner(work)
            try:
                restarted = runner.render(inp, out, cfg)
                self.assertEqual(restarted["runtime_status"], "SUCCEEDED")
                self.assertTrue(runner.verify(out)["ok"])
            finally:
                runner.close()

            clean_out = root/"clean.wav"
            clean_runner = ResilientRunner(root/"clean_work")
            try:
                clean_runner.render(inp, clean_out, cfg)
            finally:
                clean_runner.close()
            self.assertEqual(pcm_sha256(out), pcm_sha256(clean_out))

            # The restarted run must have reclaimed the dead process lock.
            archived_locks = list(work.glob("jobs/*/job.lock.json.stale-lock.*"))
            self.assertTrue(archived_locks)


if __name__ == "__main__":
    unittest.main()
