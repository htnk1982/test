from pathlib import Path
import functools
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import round9_path_audit as audit
from pdrm_operator_lab import operators as ops
from pdrm_operator_lab.round9 import DEFAULT_CONFIG, _normalize_lufs


class SilentProgress:
    def set(self, stage):
        pass


def make_job(root):
    job = root / "Round9_試験 space"
    for name in ("DECODED", "RENDERS", "LAB_INTERNAL", "BLIND_TEST"):
        (job/name).mkdir(parents=True, exist_ok=True)
    sr = 48000
    t = np.arange(sr*2, dtype=np.float64)/sr
    m = .15*np.sin(2*np.pi*223*t)+.03*np.sin(2*np.pi*8700*t)
    raw = np.stack([m, .97*m], axis=1).astype(np.float32)
    baseline = job/"DECODED"/"baseline_float.wav"
    sf.write(baseline, raw, sr, subtype="FLOAT")
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    cfg["chunk_seconds"] = .25
    x = _normalize_lufs(raw, sr, cfg["target_lufs"])
    mapping = {"A":"PeakProtectedLoudness", "B":"Control_Round8A", "C":"HarmonicElasticity"}
    state = {"candidates":{}}
    for letter, name in mapping.items():
        if name == "Control_Round8A":
            y = x
        else:
            fn = ops.harmonic_elasticity if name == "HarmonicElasticity" else ops.peak_protected_loudness
            params = cfg["harmonic_elasticity"] if name == "HarmonicElasticity" else cfg["peak_protected_loudness"]
            y = ops.oversampled_chunked(x, sr, functools.partial(fn, **params), oversample=4,
                                        chunk_seconds=cfg["chunk_seconds"], pad_seconds=cfg["pad_seconds"])
            y = _normalize_lufs(y, sr, cfg["target_lufs"])
        p = job/"RENDERS"/(name+".wav")
        sf.write(p, y, sr, subtype="PCM_24")
        (job/"BLIND_TEST"/f"ROUND9_{letter}.wav").write_bytes(p.read_bytes())
        state["candidates"][name] = {"status":"DONE", "sha256":audit.sha(p)}
    audit.write_json(job/"state.json", state)
    audit.write_json(job/"manifest.json", {"config":cfg, "input_path":str(baseline), "input_sha256":audit.sha(baseline)})
    audit.write_json(job/"LAB_INTERNAL"/"blind_mapping.json", mapping)
    return job, x, sr, cfg


class PathAuditTests(unittest.TestCase):
    def test_checkpointed_path_matches_original(self):
        with tempfile.TemporaryDirectory() as td:
            job, x, sr, cfg = make_job(Path(td))
            fn = functools.partial(ops.harmonic_elasticity, **cfg["harmonic_elasticity"])
            expected = ops.oversampled_chunked(x, sr, fn, 4, cfg["chunk_seconds"], cfg["pad_seconds"])
            actual = audit.render_cached(x, sr, fn, cfg, Path(td)/"chunks", SilentProgress(), "C")
            np.testing.assert_array_equal(actual, expected)

    def test_interrupted_chunk_is_reused_and_deterministic(self):
        with tempfile.TemporaryDirectory() as td:
            _, x, sr, cfg = make_job(Path(td))
            path = Path(td)/"chunks"
            with self.assertRaisesRegex(RuntimeError, "INJECTED_AUDIT_STOP"):
                audit.render_cached(x, sr, ops.control, cfg, path, SilentProgress(), "F", fail_after=1)
            before = (path/"000000.npy").stat().st_mtime_ns
            actual = audit.render_cached(x, sr, ops.control, cfg, path, SilentProgress(), "F")
            self.assertEqual(before, (path/"000000.npy").stat().st_mtime_ns)
            expected = ops.oversampled_chunked(x, sr, ops.control, 4, cfg["chunk_seconds"], cfg["pad_seconds"])
            np.testing.assert_array_equal(actual, expected)

    def test_tampered_chunk_is_recomputed(self):
        with tempfile.TemporaryDirectory() as td:
            _, x, sr, cfg = make_job(Path(td))
            path = Path(td)/"chunks"
            before = audit.render_cached(x, sr, ops.control, cfg, path, SilentProgress(), "F")
            (path/"000001.npy").write_bytes(b"broken")
            after = audit.render_cached(x, sr, ops.control, cfg, path, SilentProgress(), "F")
            np.testing.assert_array_equal(before, after)

    def test_zero_amount_is_resample_only_not_dry(self):
        sr = 48000
        t = np.arange(sr)/sr
        x = (.1*np.sin(2*np.pi*20000*t)).astype(np.float32)[:,None]
        f = ops.oversampled_chunked(x, sr, ops.control)
        c0 = ops.oversampled_chunked(x, sr, functools.partial(ops.harmonic_elasticity, amount=0))
        np.testing.assert_array_equal(f, c0)
        self.assertGreater(float(np.max(np.abs(f[1000:-1000]-x[1000:-1000]))), .001)

    def test_filter_probe_is_explicitly_synthetic(self):
        r = audit.filter_probe()
        self.assertIn("not_user_audio", r["scope"])
        one = next(x for x in r["rows"] if x["sr"] == 48000 and x["hz"] == 1000)
        high = next(x for x in r["rows"] if x["sr"] == 48000 and x["hz"] == 22000)
        self.assertLess(abs(one["roundtrip_gain_db"]), .01)
        self.assertLess(high["roundtrip_gain_db"], -.5)

    def test_full_audit_keeps_winner_and_all_job_files_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job, _, _, _ = make_job(root)
            before = {str(p):audit.sha(p) for p in audit.job_files(job)}
            r = audit.audit_job(job, root/"audits", codec=False)
            self.assertEqual(r["status"], "AUDIT_COMPLETE")
            self.assertTrue(r["source_unchanged"])
            self.assertLessEqual(r["reconstruction"]["C"]["max_abs_delta"], audit.RECONSTRUCTION_TOLERANCE)
            self.assertEqual(before, {str(p):audit.sha(p) for p in audit.job_files(job)})
            with mock.patch.object(audit, "render_cached", side_effect=AssertionError("unneeded rerender")):
                again = audit.audit_job(job, root/"audits", codec=False)
            self.assertEqual(r["audit_directory"], again["audit_directory"])
            self.assertTrue((Path(r["audit_directory"])/"AUDIT_REPORT.md").exists())

    def test_source_checkpoint_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as td:
            job, _, _, _ = make_job(Path(td))
            p = job/"RENDERS"/"HarmonicElasticity.wav"
            with p.open("ab") as f:
                f.write(b"tamper")
            with self.assertRaisesRegex(ValueError, "checkpoint"):
                audit.audit_job(job, Path(td)/"audit", codec=False)

    def test_output_inside_source_job_refused(self):
        with tempfile.TemporaryDirectory() as td:
            job, _, _, _ = make_job(Path(td))
            with self.assertRaisesRegex(ValueError, "outside"):
                audit.audit_job(job, job/"audit", codec=False)

    def test_mp3_endpoint_measurement_uses_existing_and_fresh_paths(self):
        ff = audit.ffmpeg_path()
        if not ff or "libmp3lame" not in audit.ffmpeg_encoders(ff):
            self.skipTest("MP3 encoder unavailable")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            job, _, _, _ = make_job(root)
            for letter in "ABC":
                audit.run_ffmpeg(ff, ["-i", str(job/"BLIND_TEST"/f"ROUND9_{letter}.wav"),
                                      "-map_metadata", "-1", "-codec:a", "libmp3lame", "-b:a", "320k",
                                      str(job/"BLIND_TEST"/f"ROUND9_{letter}_320kbps.mp3")], root/f"{letter}.log")
            r = audit.audit_job(job, root/"audits", codec=True)
            self.assertTrue(r["codec"]["available"])
            self.assertEqual(len(r["codec"]["existing_listened_mp3"]), 3)
            self.assertEqual(len(r["codec"]["fresh_same_encoder"]), 3)
            self.assertIn("fresh_lufs_spread_lu", r["codec"])

    def test_kernel_lock_blocks_second_process(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td)/"audit.lock"
            code = "import sys; from pathlib import Path; import round9_path_audit as a;\nwith a.exclusive_lock(Path(sys.argv[1])): print('unexpected')"
            with audit.exclusive_lock(p):
                proc = subprocess.run([sys.executable, "-c", code, str(p)], cwd=ROOT,
                                      capture_output=True, text=True, timeout=30)
            self.assertNotEqual(proc.returncode, 0)
            with audit.exclusive_lock(p):
                pass


if __name__ == "__main__":
    unittest.main()
