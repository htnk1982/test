from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from pdrm_engine.engine import run_job
from pdrm_engine.io_utils import pcm_sha256


class Runtime:
    max_round_allowed = 8
    def heartbeat(self, **kwargs):
        pass
    def is_cancelled(self):
        return False


def synth(sr=48000, seconds=10.0, amp=0.03):
    t = np.arange(int(sr*seconds), dtype=np.float64)/sr
    mono = amp*(0.75*np.sin(2*np.pi*101*t) + 0.24*np.sin(2*np.pi*1201*t))
    return np.stack([mono, mono*0.99], axis=1).astype(np.float32)


class ResilienceContractTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sr = 48000
        self.inp = self.root/"input.wav"
        sf.write(self.inp, synth(), self.sr, subtype="FLOAT")

    def tearDown(self):
        self.tmp.cleanup()

    def test_hard_kill_leaves_no_final_and_restart_is_deterministic(self):
        killed_out = self.root/"killed.wav"
        marker = self.root/"marker.txt"
        helper = Path(__file__).with_name("kill_worker.py")
        proc = subprocess.Popen([sys.executable, str(helper), str(self.inp), str(killed_out), str(marker)])
        deadline = time.time() + 25.0
        while time.time() < deadline and not marker.exists() and proc.poll() is None:
            time.sleep(0.05)
        self.assertTrue(marker.exists(), "worker did not reach SAFE_FRONTIER")
        proc.kill()
        proc.wait(timeout=10)
        self.assertFalse(killed_out.exists(), "hard-killed core published a final output")

        resumed = self.root/"resumed.wav"
        clean = self.root/"clean.wav"
        cfg = {"target_lufs": -18.0, "true_peak_ceiling_dbtp": -1.0, "output_subtype":"PCM_24"}
        run_job(self.inp, resumed, cfg, Runtime())
        run_job(self.inp, clean, cfg, Runtime())
        self.assertEqual(pcm_sha256(resumed), pcm_sha256(clean))

    def test_post_write_failure_rolls_back_to_noop(self):
        out = self.root/"rollback.wav"
        fake_ok = {
            "lufs_i": -18.0,
            "true_peak_dbtp": -5.0,
            "sample_peak_dbfs": -5.2,
            "plr_db": 13.0,
            "preservation": {},
        }
        with mock.patch(
            "pdrm_engine.engine._post_write_validate",
            side_effect=[
                (False, fake_ok, ["INJECTED_POST_WRITE_FAILURE"]),
                (True, fake_ok, []),
            ],
        ):
            result = run_job(self.inp, out, {
                "target_lufs": -18.0,
                "true_peak_ceiling_dbtp": -1.0,
                "output_subtype":"PCM_24",
            }, Runtime())
        self.assertEqual(result["final_status"], "QUALITY_LIMIT_REACHED")
        self.assertEqual(result["rollback"]["action"], "ROLLBACK_TO_NO_OP")
        self.assertEqual(self.inp.read_bytes(), out.read_bytes())

    def test_mapping_runtime_context_is_supported(self):
        out = self.root/"mapping.wav"
        beats = []
        ctx = {
            "max_round_allowed": 8,
            "heartbeat": lambda **kw: beats.append(kw),
            "is_cancelled": lambda: False,
        }
        result = run_job(self.inp, out, {
            "target_lufs": -18.0,
            "true_peak_ceiling_dbtp": -1.0,
        }, ctx)
        self.assertTrue(result["runtime_context_ack"])
        self.assertFalse(result["round9_executed"])
        self.assertTrue(beats)


if __name__ == "__main__":
    unittest.main()
