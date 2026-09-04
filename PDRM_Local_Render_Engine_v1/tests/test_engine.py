from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from pdrm_engine.analysis import integrated_lufs, true_peak_db
from pdrm_engine.engine import CoreInputError, run_job
from pdrm_engine.io_utils import pcm_sha256


class Runtime:
    max_round_allowed = 8

    def __init__(self):
        self.beats = []

    def heartbeat(self, **kwargs):
        self.beats.append(dict(kwargs))

    def is_cancelled(self):
        return False


def synth(sr=48000, seconds=8.0, amp=0.08, spiky=False, channels=2):
    t = np.arange(int(sr * seconds), dtype=np.float64) / sr
    mono = amp * (
        0.72 * np.sin(2*np.pi*97*t)
        + 0.36 * np.sin(2*np.pi*997*t)
        + 0.18 * np.sin(2*np.pi*6041*t)
    )
    if spiky:
        for sec in np.arange(0.4, seconds, 0.55):
            i = int(sec * sr)
            n = min(int(0.040 * sr), len(mono) - i)
            if n <= 0:
                continue
            burst = 0.72 * np.exp(-np.arange(n)/(sr*0.006)) * np.sin(2*np.pi*1800*np.arange(n)/sr)
            mono[i:i+n] += burst
    if channels == 1:
        return mono[:, None].astype(np.float32)
    if channels == 2:
        return np.stack([mono, mono*0.985], axis=1).astype(np.float32)
    return np.stack([mono*(1.0 - 0.01*k) for k in range(channels)], axis=1).astype(np.float32)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.sr = 48000

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, audio):
        p = self.root/name
        sf.write(p, audio, self.sr, subtype="FLOAT")
        return p

    def test_noop_is_exact_file_copy_when_already_optimal(self):
        inp = self.write("noop.wav", synth(amp=0.07))
        audio, sr = sf.read(inp, always_2d=True, dtype="float64")
        target = integrated_lufs(audio, sr)
        out = self.root/"noop_out.wav"
        result = run_job(inp, out, {
            "target_lufs": target,
            "true_peak_ceiling_dbtp": -0.2,
            "output_subtype": "PCM_24",
        }, Runtime())
        self.assertEqual(result["final_status"], "NO_OP_ALREADY_OPTIMAL")
        self.assertEqual(inp.read_bytes(), out.read_bytes())
        self.assertFalse(result["round9_executed"])

    def test_gain_only_normalization(self):
        inp = self.write("gain.wav", synth(amp=0.025))
        out = self.root/"gain_out.wav"
        result = run_job(inp, out, {
            "target_lufs": -18.0,
            "true_peak_ceiling_dbtp": -1.0,
            "output_subtype": "PCM_24",
        }, Runtime())
        self.assertEqual(result["final_status"], "NORMALIZED_ONLY")
        y, sr = sf.read(out, always_2d=True, dtype="float64")
        self.assertLessEqual(abs(integrated_lufs(y, sr) - (-18.0)), 0.18)
        self.assertLessEqual(true_peak_db(y, sr), -0.95)

    def test_spiky_material_never_breaks_tp_ceiling(self):
        inp = self.write("spiky.wav", synth(amp=0.07, spiky=True))
        out = self.root/"spiky_out.wav"
        result = run_job(inp, out, {
            "target_lufs": -14.0,
            "true_peak_ceiling_dbtp": -2.0,
            "output_subtype": "PCM_24",
        }, Runtime())
        self.assertIn(result["final_status"], {
            "NORMALIZED_ONLY", "FINALIZED_TARGET_REACHED",
            "FINALIZED_NEAREST_SAFE", "QUALITY_LIMIT_REACHED"
        })
        y, sr = sf.read(out, always_2d=True, dtype="float64")
        # If the quality frontier had to roll all the way back to NO-OP, the
        # report may legitimately document target miss. Otherwise the emitted
        # processed master must satisfy TP.
        if result["final_status"] != "QUALITY_LIMIT_REACHED":
            self.assertLessEqual(true_peak_db(y, sr), -1.95)
        self.assertFalse(result["round9_executed"])

    def test_same_input_config_produces_same_pcm_hash(self):
        inp = self.write("det.wav", synth(amp=0.03))
        cfg = {
            "target_lufs": -18.0,
            "true_peak_ceiling_dbtp": -1.0,
            "output_subtype": "PCM_24",
        }
        a = self.root/"a.wav"
        b = self.root/"b.wav"
        run_job(inp, a, cfg, Runtime())
        run_job(inp, b, cfg, Runtime())
        self.assertEqual(pcm_sha256(a), pcm_sha256(b))

    def test_existing_output_is_not_overwritten(self):
        inp = self.write("source.wav", synth(amp=0.04))
        out = self.root/"existing.wav"
        out.write_bytes(b"foreign")
        with self.assertRaises(FileExistsError):
            run_job(inp, out, {
                "target_lufs": -18.0,
                "true_peak_ceiling_dbtp": -1.0,
            }, Runtime())
        self.assertEqual(out.read_bytes(), b"foreign")

    def test_three_channel_input_is_outside_authority(self):
        inp = self.write("3ch.wav", synth(amp=0.04, channels=3))
        with self.assertRaises(CoreInputError):
            run_job(inp, self.root/"3ch_out.wav", {
                "target_lufs": -18.0,
                "true_peak_ceiling_dbtp": -1.0,
            }, Runtime())

    def test_heartbeat_is_emitted(self):
        inp = self.write("hb.wav", synth(amp=0.03))
        runtime = Runtime()
        run_job(inp, self.root/"hb_out.wav", {
            "target_lufs": -18.0,
            "true_peak_ceiling_dbtp": -1.0,
        }, runtime)
        stages = {b.get("stage") for b in runtime.beats}
        self.assertIn("INPUT_AUDIT", stages)
        self.assertIn("SAFE_FRONTIER", stages)
        self.assertIn("COMPLETE", stages)


if __name__ == "__main__":
    unittest.main()
