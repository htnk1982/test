from pathlib import Path
import shutil
import tempfile
import unittest

import numpy as np
import soundfile as sf

from pdrm_engine.codec import available_profiles, codec_roundtrip_qc


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed on test host")
class CodecQCTests(unittest.TestCase):
    def test_representative_codec_roundtrip_runs(self):
        profiles = available_profiles()
        if not profiles:
            self.skipTest("ffmpeg has no supported AAC/Opus/MP3 encoder")
        # One available profile is enough for mechanics; local pre-Round-9 QC
        # will run every available representative profile on real music.
        profiles = profiles[:1]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"source.wav"
            sr = 48000
            t = np.arange(sr*2, dtype=np.float64)/sr
            mono = 0.035*np.sin(2*np.pi*97*t) + 0.012*np.sin(2*np.pi*5003*t)
            x = np.stack([mono, mono*0.99], axis=1).astype(np.float32)
            sf.write(p, x, sr, subtype="PCM_24")
            result = codec_roundtrip_qc(
                p,
                peak_gate_dbtp=0.0,
                max_lufs_drift=1.5,
                max_crest_drift_db=2.0,
                profiles=profiles,
            )
            self.assertTrue(result["available"])
            self.assertEqual(len(result["profiles"]), 1)
            self.assertIn("decoded_metrics", result["profiles"][0])


if __name__ == "__main__":
    unittest.main()
