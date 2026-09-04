from pathlib import Path
import tempfile
import unittest

import numpy as np
import soundfile as sf

from pdrm_engine.codec import available_profiles, ffmpeg_path
from pdrm_runtime.acceptance import run_acceptance


def synth(sr=48000, seconds=3.0, amp=0.025):
    t = np.arange(int(sr*seconds), dtype=np.float64)/sr
    mono = amp*(
        0.72*np.sin(2*np.pi*113*t)
        + 0.27*np.sin(2*np.pi*1601*t)
        + 0.08*np.sin(2*np.pi*7031*t)
    )
    # Deterministic small transients make the fixture less trivial.
    for sec in (0.45, 1.20, 2.15):
        i = int(sec*sr)
        n = min(int(0.035*sr), len(mono)-i)
        mono[i:i+n] += 0.12*np.exp(-np.arange(n)/(sr*0.006))*np.sin(2*np.pi*2200*np.arange(n)/sr)
    return np.stack([mono, mono*0.99], axis=1).astype(np.float32)


@unittest.skipUnless(ffmpeg_path(), "ffmpeg unavailable")
class AcceptanceTests(unittest.TestCase):
    def test_full_acceptance_sequence(self):
        profiles = available_profiles()
        if not profiles:
            self.skipTest("no representative lossy encoder available")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            inp = root/"private_fixture.wav"
            sf.write(inp, synth(), 48000, subtype="FLOAT")
            report = run_acceptance(
                inp,
                root/"acceptance",
                target_lufs=-18.0,
                tp=-1.0,
                minimum_duration_seconds=2.0,
                kill_timeout_seconds=60.0,
                codec_profiles=profiles[:1],
                keep_clean_copy=False,
            )
            self.assertEqual(report["result"], "PASS")
            self.assertTrue(report["round9_unlock_candidate"])
            self.assertTrue(all(report["gates"].values()))
            report_path = Path(report["acceptance_directory"])/"ACCEPTANCE_REPORT.json"
            self.assertTrue(report_path.exists())
            self.assertFalse(report["restart_result"]["sidecar"]["round9_executed"])


if __name__ == "__main__":
    unittest.main()
