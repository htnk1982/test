from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import accepted_finish as app
from test_note_sub_lab import notes


class AcceptedFinishTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'input').mkdir()
        self.output = self.root / 'out'
        self.x, self.sr = notes(frequencies=(82.406889,))
        self.x = self.x * .5
        self.src = self.root / 'input' / 'track.wav'
        sf.write(self.src, self.x, self.sr, subtype='FLOAT')

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_frozen_hashes_match(self):
        self.assertEqual(app.verify_dsp(), app.DSP_SHA256)

    def test_02_low_crest_can_reach_minus14(self):
        self.assertEqual(app.safe_target(dict(lufs_i=-20, true_peak_dbtp_estimate=-11)), -14)

    def test_03_high_crest_lowers_level_not_peak_processing(self):
        self.assertEqual(app.safe_target(dict(lufs_i=-20, true_peak_dbtp_estimate=-5)), -17.5)

    def test_04_silence_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Silent'):
            app.safe_target(dict(lufs_i=None, true_peak_dbtp_estimate=-120))

    def test_05_target_override_restored_even_after_exception(self):
        original = app.ns.CONFIG
        with self.assertRaises(ValueError):
            with app._note_level(-18):
                self.assertEqual(app.ns.CONFIG['target_lufs'], -18)
                self.assertEqual(app.ns.CONFIG['max_added_peak'], original['max_added_peak'])
                raise ValueError('test')
        self.assertIs(app.ns.CONFIG, original)
        self.assertEqual(app.ns.CONFIG['target_lufs'], -14)
        self.assertEqual(app.io.CONFIG['target_lufs'], -14)

    def test_06_full_pipeline_source_protected_no_blind_files(self):
        h = app.io.file_hash(self.src)
        report, result = app.run_file(self.src, self.output, write_mp3=False)
        self.assertEqual(report['status'], 'COMPLETE')
        self.assertEqual(h, app.io.file_hash(self.src))
        self.assertTrue(report['source_unchanged'])
        self.assertFalse(report['limiter_added'])
        self.assertFalse(report['harmonic_elasticity_applied'])
        self.assertEqual(report['output_metrics']['frames'], len(self.x))
        self.assertLessEqual(report['output_metrics']['true_peak_dbtp_estimate'], -1.5)
        self.assertTrue((result / 'FINISHED.wav').is_file())
        self.assertFalse(any('BLIND' in p.name or 'REVEAL' in p.name for p in result.rglob('*')))

    def test_07_idempotent_no_second_application(self):
        _, out = app.run_file(self.src, self.output, write_mp3=False)
        h = app.io.file_hash(out / 'FINISHED.wav')
        report, out2 = app.run_file(self.src, self.output, write_mp3=False)
        self.assertEqual(out, out2)
        self.assertEqual(report['rerun_status'], 'IDEMPOTENT_SKIP')
        self.assertEqual(app.io.file_hash(out2 / 'FINISHED.wav'), h)

    def test_08_renamed_output_rejected_by_pcm_registry(self):
        _, out = app.run_file(self.src, self.output, write_mp3=False)
        renamed = self.root / 'input' / 'another.wav'
        shutil.copyfile(out / 'FINISHED.wav', renamed)
        with self.assertRaisesRegex(ValueError, 'already been processed'):
            app.run_file(renamed, self.output, write_mp3=False)

    def test_09_source_tree_and_generated_name_rejected(self):
        with self.assertRaises(ValueError):
            app.run_file(self.src, self.src.parent / 'output', write_mp3=False)
        with self.assertRaises(ValueError):
            app._validate_paths(self.root / 'input' / 'SUB_AUGMENTED.wav', self.output)

    def test_10_modified_result_never_overwritten(self):
        _, out = app.run_file(self.src, self.output, write_mp3=False)
        dest = out / 'FINISHED.wav'
        dest.write_bytes(b'user-edited output')
        with self.assertRaisesRegex(RuntimeError, 'Result modified'):
            app.run_file(self.src, self.output, write_mp3=False)
        self.assertEqual(dest.read_bytes(), b'user-edited output')

    def test_11_interrupted_pipeline_resumes_identical_pcm(self):
        with self.assertRaisesRegex(RuntimeError, 'TEST_INTERRUPTION_AFTER_NOTE'):
            app.run_file(self.src, self.output, write_mp3=False, interrupt_after='note')
        self.assertFalse(any(self.output.glob('*/RESULT')))
        _, resumed = app.run_file(self.src, self.output, write_mp3=False)
        _, clean = app.run_file(self.src, self.root / 'clean', write_mp3=False)
        self.assertEqual(app.io.pcm_hash(resumed / 'FINISHED.wav'), app.io.pcm_hash(clean / 'FINISHED.wav'))

    def test_12_high_crest_pipeline_never_inserts_limiter(self):
        x = self.x.copy()
        x[len(x) // 2] = .99
        sf.write(self.src, x, self.sr, subtype='FLOAT')
        report, out = app.run_file(self.src, self.output, write_mp3=False)
        self.assertTrue(report['peak_limited_level'])
        self.assertLess(report['output_metrics']['lufs_i'], -14.01)
        self.assertFalse(report['limiter_added'])
        reference = out.parent / 'input' / 'REFERENCE.wav'
        ref, _ = sf.read(reference, dtype='float64', always_2d=True)
        src, _ = sf.read(self.src, dtype='float64', always_2d=True)
        g = 10 ** ((report['normalization_target_lufs'] - report['baseline_metrics']['lufs_i']) / 20)
        self.assertLess(np.max(np.abs(ref - src * g)), 8e-8)

    def test_13_codec_gate_with_actual_ffmpeg(self):
        if not app.io.ffmpeg_path():
            self.skipTest('ffmpeg unavailable')
        r, out = app.run_file(self.src, self.output, write_mp3=True)
        self.assertTrue((out / 'FINISHED_320kbps.mp3').is_file())
        self.assertLess(abs(r['output_metrics']['lufs_i'] - r['codec_metrics']['lufs_i']), .1)
        self.assertLessEqual(r['codec_metrics']['true_peak_dbtp_estimate'], -1)

    def test_14_partial_mono_rejected_without_output(self):
        sf.write(self.src, self.x[:, 0], self.sr, subtype='FLOAT')
        with self.assertRaisesRegex(ValueError, 'Stereo'):
            app.run_file(self.src, self.output, write_mp3=False)
        self.assertFalse(self.output.exists())

    def test_15_hf_failure_leaves_no_final(self):
        with patch.object(app.hf, 'analyze_control', side_effect=RuntimeError('HF injected failure')):
            with self.assertRaisesRegex(RuntimeError, 'HF injected'):
                app.run_file(self.src, self.output, write_mp3=False)
        self.assertFalse(any(self.output.glob('*/RESULT')))
        self.assertTrue(any(self.output.glob('*/FAILURE.json')))

    def test_16_nonfinite_input_rejected(self):
        self.x[100, 0] = np.nan
        sf.write(self.src, self.x, self.sr, subtype='FLOAT')
        with self.assertRaisesRegex(ValueError, 'Non-finite'):
            app.run_file(self.src, self.output, write_mp3=False)
        self.assertFalse(any(self.output.glob('*/RESULT')))

    def test_17_44k_and_flac_input(self):
        x, sr = notes(sr=44100, frequencies=(82.406889,))
        p = self.src.with_suffix('.flac')
        sf.write(p, x * .5, sr, subtype='PCM_24')
        r, out = app.run_file(p, self.output, write_mp3=False)
        self.assertEqual(r['output_metrics']['samplerate'], sr)
        self.assertEqual(r['output_metrics']['frames'], len(x))


if __name__ == '__main__':
    unittest.main(verbosity=2)
