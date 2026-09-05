from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import note_sub_lab_v02 as lab


def row(time_s, target=41.2, f0=82.4, amplitude=.02, **extra):
    value = dict(
        time=float(time_s),
        track_state='TRACK',
        track_reason='tonal_candidate',
        state='SYNTHESIZE' if amplitude > 0 else 'KEEP',
        reason='eligible_tonal_interval' if amplitude > 0 else 'existing_low_end_sufficient',
        f0_hz=float(f0),
        sub_hz=float(target),
        amplitude=float(amplitude),
        tonal_strength=.03,
        boundary_evidence=False,
    )
    value.update(extra)
    return value


class NoteSubV021ContextRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.quiet = self.root / 'quiet.wav'
        sf.write(self.quiet, np.zeros((48000, 2)), 48000, subtype='FLOAT')

    def tearDown(self):
        self.tmp.cleanup()

    def test_01_isolated_target_outlier_bridges_tracking_but_adds_nothing(self):
        rows = [row(.40 + .02 * i) for i in range(32)]
        rows[16] = row(.40 + .02 * 16, target=46.25, f0=92.5, amplitude=.02)

        tracks = lab.track_notes(rows)
        self.assertEqual(len(tracks), 1, [len(t) for t in tracks])
        corrected = tracks[0][16]
        self.assertEqual(corrected['tracking_correction'], 'isolated_target_outlier_bridged')
        self.assertAlmostEqual(corrected['raw_tracking_target_hz'], 46.25)
        self.assertLess(lab.cents(corrected['tracking_target_hz'], 41.2), 1e-6)
        self.assertEqual(corrected['amplitude'], 0.0)

        events, rejected = lab.make_events(rows, self.quiet)
        self.assertEqual(len(events), 1, rejected)
        self.assertEqual(events[0]['tracking_corrections'], 1)
        self.assertLess(lab.cents(max(events[0]['frequencies']), 41.2), 1e-6)
        self.assertEqual(events[0]['amplitudes'][16], 0.0)

    def test_02_two_frame_target_change_is_not_context_bridged(self):
        rows = [row(.40 + .02 * i) for i in range(36)]
        rows[16] = row(.40 + .02 * 16, target=46.25, f0=92.5)
        rows[17] = row(.40 + .02 * 17, target=46.25, f0=92.5)

        stable = lab.stabilize_tracking_rows(rows)
        self.assertNotIn('tracking_correction', stable[16])
        self.assertNotIn('tracking_correction', stable[17])
        tracks = lab.track_notes(rows)
        self.assertGreaterEqual(len(tracks), 2, [len(t) for t in tracks])

    def test_03_boundary_marked_outlier_is_not_smoothed_away(self):
        rows = [row(.40 + .02 * i) for i in range(32)]
        rows[16] = row(.40 + .02 * 16, target=46.25, f0=92.5,
                       boundary_evidence=True)

        stable = lab.stabilize_tracking_rows(rows)
        self.assertNotIn('tracking_correction', stable[16])
        tracks = lab.track_notes(rows)
        self.assertGreaterEqual(len(tracks), 2, [len(t) for t in tracks])


if __name__ == '__main__':
    unittest.main(verbosity=2)
