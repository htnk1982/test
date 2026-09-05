from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import pyloudnorm as pyln
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import note_sub_lab as v011
import note_sub_lab_v02 as lab


def _row(time_s, f0=82.4, target=41.2, amplitude=.02, strength=.03, **extra):
    row = dict(
        time=float(time_s),
        track_state='TRACK',
        track_reason='tonal_candidate',
        state='SYNTHESIZE' if amplitude > 0 else 'KEEP',
        reason='eligible_tonal_interval' if amplitude > 0 else 'existing_low_end_sufficient',
        f0_hz=float(f0),
        sub_hz=float(target),
        amplitude=float(amplitude),
        tonal_strength=float(strength),
    )
    row.update(extra)
    return row


def _normalize_lufs(stereo, sr, target=-14.0):
    loudness = pyln.Meter(sr).integrated_loudness(stereo.astype('float64'))
    return (stereo * 10 ** ((target - loudness) / 20)).astype('float32')


def _mixed_bass(sr=48000):
    duration = 2.8
    t = np.arange(int(duration * sr), dtype=np.float64) / sr
    x = np.zeros_like(t)

    start, stop = .25, 2.55
    local = t - start
    active = (t >= start) & (t < stop)
    env = lab.smoother(local / .05) * lab.smoother((stop - t) / .06) * active
    f0 = 82.406889
    for h, amp in ((1, .060), (2, .040), (3, .026), (4, .014)):
        x += env * amp * np.cos(2 * np.pi * f0 * h * local + .11 * h)

    # Low-frequency kick transients overlap the known bass.
    for hit in (.72, 1.48, 2.12):
        k = t - hit
        m = (k >= 0) & (k < .16)
        phase_cycles = 96 * np.maximum(k, 0) - 150 * np.maximum(k, 0) ** 2
        x += m * .115 * np.exp(-np.maximum(k, 0) / .035) * np.cos(2 * np.pi * phase_cycles)

    # Mid-band chord tones and high percussive hits force the test away from a
    # clean single-bass condition.
    chord_env = ((t >= .42) & (t < 2.42)).astype(np.float64)
    for f, amp in ((220.0, .014), (277.18, .012), (329.63, .010)):
        x += chord_env * amp * np.cos(2 * np.pi * f * t + f / 1000.0)

    rng = np.random.default_rng(20260905)
    noise = rng.normal(0, 1, len(t))
    for hit in (1.02, 1.90):
        h = t - hit
        m = (h >= 0) & (h < .035)
        x += m * .020 * np.exp(-np.maximum(h, 0) / .010) * noise

    stereo = np.stack((x, x), axis=1)
    return _normalize_lufs(stereo, sr), sr


def _harmonic_note(sr=48000, f0=82.406889, duration=1.8):
    t = np.arange(int(duration * sr), dtype=np.float64) / sr
    x = np.zeros_like(t)
    start, stop = .25, 1.55
    local = t - start
    m = (t >= start) & (t < stop)
    env = lab.smoother(local / .04) * lab.smoother((stop - t) / .04) * m
    for h, a in ((1, .070), (2, .048), (3, .030), (4, .016)):
        x += env * a * np.cos(2 * np.pi * f0 * h * local + .13 * h)
    return _normalize_lufs(np.stack((x, x), axis=1), sr), sr


class NoteSubV02Regression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inputs = self.root / 'inputs'
        self.inputs.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write_audio(self, name, x, sr):
        path = self.inputs / name
        sf.write(path, x, sr, subtype='FLOAT')
        return path

    def collect(self, x, sr, name='input.wav'):
        path = self.write_audio(name, x, sr)
        job = self.root / (Path(name).stem + '_job')
        (job / 'analysis').mkdir(parents=True)
        rows, cache = lab.collect_frames(path, job, lab.Progress())
        return rows, path, cache

    def test_01_target_selection_is_separate_from_f0_octave_interpretation(self):
        self.assertAlmostEqual(lab.select_generation_target(43.7), 43.7)
        self.assertAlmostEqual(lab.select_generation_target(87.4), 43.7)
        self.assertIsNone(lab.select_generation_target(150.0))

    def test_02_f0_octave_flip_does_not_restart_same_target_note(self):
        quiet = self.write_audio('quiet.wav', np.zeros((48000, 2)), 48000)
        rows = []
        for i in range(32):
            f0 = 43.7 if i < 16 else 87.4
            rows.append(_row(.50 + .02 * i, f0=f0, target=43.7))
        tracks = lab.track_notes(rows)
        events, rejected = lab.make_events(rows, quiet)
        self.assertEqual(len(tracks), 1, tracks)
        self.assertEqual(len(events), 1, (events, rejected))
        self.assertLess(lab.cents(events[0]['median_sub_hz'], 43.7), 1.0)

    def test_03_zero_addition_inside_note_does_not_end_tracking_or_phase(self):
        quiet = self.write_audio('zero_gap.wav', np.zeros((48000, 2)), 48000)
        rows = []
        for i in range(36):
            amp = 0.0 if 11 <= i <= 23 else .02
            rows.append(_row(.40 + .02 * i, amplitude=amp))
        tracks = lab.track_notes(rows)
        events, rejected = lab.make_events(rows, quiet)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(len(events), 1, rejected)
        event = events[0]
        self.assertTrue(any(a == 0.0 for a in event['amplitudes']))
        self.assertTrue(any(a > 0.0 for a in event['amplitudes']))
        self.assertEqual(len(event['integral_cycles']), len(event['times']))
        self.assertTrue(np.all(np.diff(event['integral_cycles']) > 0))
        probe = np.arange(.68, .78, 1 / 48000)
        self.assertLess(float(np.max(np.abs(lab.event_wave(event, probe)))), 1e-12)

    def test_04_same_pitch_reattack_and_real_rest_remain_separate_notes(self):
        rows = [_row(.40 + .02 * i) for i in range(44)]
        rows[20]['tonal_strength'] = .002
        rows[21]['tonal_strength'] = .03
        tracks = lab.track_notes(rows)
        self.assertEqual(len(tracks), 2, [len(x) for x in tracks])

        with_rest = [_row(.40 + .02 * i) for i in range(16)]
        with_rest += [
            dict(time=.72 + .02 * i, track_state='SILENCE', track_reason='silence',
                 state='ABSTAIN', reason='silence', amplitude=0.0)
            for i in range(4)
        ]
        with_rest += [_row(.80 + .02 * i) for i in range(16)]
        tracks = lab.track_notes(with_rest)
        self.assertEqual(len(tracks), 2, [len(x) for x in tracks])

    def test_05_existing_low_end_can_be_keep_while_note_tracking_continues(self):
        x, sr = _harmonic_note(f0=41.2034445)
        rows, path, _ = self.collect(x, sr, 'existing_low.wav')
        tracked = [r for r in rows if r.get('track_state') == 'TRACK']
        self.assertTrue(tracked)
        self.assertTrue(any(r.get('state') == 'KEEP' for r in tracked))
        tracks = lab.track_notes(rows)
        events, rejected = lab.make_events(rows, path)
        self.assertTrue(tracks)
        self.assertFalse(events)
        self.assertTrue(any(r['reason'] == 'tracked_but_no_addition_required' for r in rejected))

    def test_06_mixed_audio_regression_bass_kick_chord_and_high_hit(self):
        x, sr = _mixed_bass()
        rows, path, _ = self.collect(x, sr, 'mixed.wav')
        tracked = [
            r for r in rows
            if .45 <= r['time'] <= 2.35 and r.get('track_state') == 'TRACK'
        ]
        self.assertGreater(len(tracked), 20,
                           [(r['time'], r.get('track_reason'), r.get('reason')) for r in rows])
        events, rejected = lab.make_events(rows, path)
        self.assertTrue(events, rejected)
        for event in events:
            self.assertLess(lab.cents(event['median_sub_hz'], 41.2034445), 35.0, event)
            self.assertGreaterEqual(event['start'], .15)
            self.assertLessEqual(event['end'], 2.65)
        self.assertGreater(sum(e['active_addition_seconds'] for e in events), .20)

    def test_07_v02_run_job_keeps_c_and_production_runtime_outside_scope(self):
        v02_source = (ROOT / 'note_sub_lab_v02.py').read_text(encoding='utf-8')
        self.assertNotIn('from pdrm_engine', v02_source)
        self.assertNotIn('import pdrm_runtime', v02_source)
        self.assertEqual(lab.KNOWN_C, v011.KNOWN_C)

        x, sr = _harmonic_note()
        source = self.write_audio('run.wav', x, sr)
        before = lab.file_hash(source)
        report, result = lab.run_job(source, self.root / 'work', write_mp3=False)
        self.assertEqual(report['version'], lab.VERSION)
        self.assertEqual(lab.file_hash(source), before)
        self.assertEqual(lab.file_hash(result / 'CONTROL_C.wav'), before)
        self.assertFalse(report['production_core_modified'])
        self.assertFalse(report['winner_audio_modified'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
