from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from pdrm_engine import MAX_ROUND_ALLOWED
from pdrm_engine.analysis import integrated_lufs
from pdrm_operator_lab.operators import (
    harmonic_elasticity,
    peak_protected_loudness,
    oversampled_chunked,
)
from pdrm_operator_lab.round9 import _normalize_lufs, run_round9


class Round9OperatorTests(unittest.TestCase):
    def test_production_core_remains_locked_to_round8(self):
        self.assertEqual(MAX_ROUND_ALLOWED, 8)

    def test_transfers_are_odd_symmetric_and_finite(self):
        x = np.linspace(-0.8, 0.8, 4001, dtype=np.float32)[:, None]
        for fn in (harmonic_elasticity, peak_protected_loudness):
            yp = fn(x)
            yn = fn(-x)
            self.assertTrue(np.all(np.isfinite(yp)))
            self.assertTrue(np.allclose(yp, -yn, atol=2e-6, rtol=2e-6))

    def test_peak_protected_gain_fades_toward_peak_region(self):
        x = np.array([[0.02], [0.20], [0.56]], dtype=np.float32)
        y = peak_protected_loudness(x, saturation=0.0)
        gain = np.abs(y[:, 0] / x[:, 0])
        self.assertGreater(gain[0], gain[1])
        self.assertGreater(gain[1], gain[2])
        self.assertAlmostEqual(float(gain[2]), 1.0, places=3)

    def test_chunked_oversampling_is_deterministic(self):
        sr = 48000
        t = np.arange(sr * 2, dtype=np.float64) / sr
        mono = 0.12 * np.sin(2 * np.pi * 173 * t) + 0.03 * np.sin(2 * np.pi * 3701 * t)
        x = np.stack([mono, mono * 0.97], axis=1).astype(np.float32)
        a = oversampled_chunked(x, sr, harmonic_elasticity, oversample=4, chunk_seconds=0.37)
        b = oversampled_chunked(x, sr, harmonic_elasticity, oversample=4, chunk_seconds=0.37)
        self.assertTrue(np.array_equal(a, b))

    def test_normalization_hits_target(self):
        sr = 48000
        t = np.arange(sr * 4, dtype=np.float64) / sr
        x = np.stack([
            0.05 * np.sin(2 * np.pi * 113 * t),
            0.049 * np.sin(2 * np.pi * 113 * t),
        ], axis=1).astype(np.float32)
        y = _normalize_lufs(x, sr, -18.0)
        self.assertAlmostEqual(integrated_lufs(y, sr), -18.0, places=4)

    def test_small_end_to_end_builds_blind_package_without_unlocking_core(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            sr = 48000
            t = np.arange(sr * 10, dtype=np.float64) / sr
            mono = 0.04 * np.sin(2 * np.pi * 109 * t) + 0.012 * np.sin(2 * np.pi * 5033 * t)
            x = np.stack([mono, mono * 0.98], axis=1).astype(np.float32)
            inp = root / "baseline.wav"
            sf.write(inp, x, sr, subtype="FLOAT")
            report = run_round9(inp, root / "out", target_lufs=-18.0)
            self.assertEqual(report["result"], "READY_FOR_BLIND_LISTENING")
            self.assertTrue(Path(report["blind_zip"]).exists())
            self.assertTrue(report["production_core_round9_lock_unchanged"])
            self.assertEqual(MAX_ROUND_ALLOWED, 8)


if __name__ == "__main__":
    unittest.main()
