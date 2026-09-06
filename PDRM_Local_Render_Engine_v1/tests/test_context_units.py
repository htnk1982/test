"""Specification-oracle regressions: milliseconds must never mean seconds.

Expected frame counts below come from physical units, not a previous renderer.
The long-file case is deliberate: old sub-second fixtures hid the defect.
"""
from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).parent))
import offline_peak_lab as kernel
import offline_peak_stream_v32 as shared
import offline_peak_stream_v34 as active
import offline_peak_context_v34 as context
from test_offline_peak_context import broad, gentle


class ContextUnitContract(unittest.TestCase):
    def test_128ms_at_48khz_is_6144_frames_on_five_minute_track(self):
        a, b = shared._context_bounds(150*48000, 150*48000+2048, 300*48000, 48000, 128, 12)
        self.assertEqual(b-a, 6144)

    def test_all_configured_widths_at_all_supported_rates(self):
        # Independent values, not a copy of the conversion expression.
        expected = {44100: (5645,11290,22579,45158), 48000: (6144,12288,24576,49152),
                    88200: (11290,22579,45158,90317), 96000: (12288,24576,49152,98304)}
        for sr, values in expected.items():
            for ms, count in zip((128,256,512,1024), values):
                with self.subTest(sr=sr,ms=ms):
                    a,b=shared._context_bounds(150*sr,150*sr+round(.043*sr),300*sr,sr,ms,12)
                    self.assertEqual(b-a,count)
                    self.assertLessEqual(abs((b-a)/sr-ms/1000),.5/sr+1e-12)

    def test_longer_track_does_not_enlarge_local_context(self):
        for seconds in (1,60,300,1800):
            with self.subTest(seconds=seconds):
                a,b=shared._context_bounds(20000,22048,seconds*48000,48000,128,12)
                self.assertEqual(b-a,6144)

    def test_actual_width_has_same_units_under_active_v34_wrapper(self):
        with active._runtime():
            a,b=shared._context_bounds(20000,22048,300*48000,48000,128,12)
        self.assertEqual(b-a,6144)

    def test_boundary_context_stays_in_file_and_retains_guard(self):
        sr=48000;length=sr
        for start,end in ((600,2648),(length-2648,length-600)):
            a,b=shared._context_bounds(start,end,length,sr,128,12)
            self.assertEqual(b-a,6144)
            self.assertGreaterEqual(a,0);self.assertLessEqual(b,length)
            self.assertGreaterEqual(start-a,576);self.assertGreaterEqual(b-end,576)

    def test_no_boundary_guard_is_not_repaired_by_enlarging_whole_track(self):
        with self.assertRaises(kernel.NotFeasible):
            shared._context_bounds(0,2048,300*48000,48000,128,12)

    def test_short_file_never_requests_audio_outside_file(self):
        a,b=shared._context_bounds(10000,12048,24000,48000,1024,12)
        self.assertEqual((a,b),(0,24000))

    def test_large_cluster_tries_next_configured_width_not_silent_growth(self):
        sr=48000
        with self.assertRaises(kernel.NotFeasible):
            shared._context_bounds(100000,109600,300*sr,sr,128,12)
        a,b=shared._context_bounds(100000,109600,300*sr,sr,256,12)
        self.assertEqual(b-a,12288)

    def test_cluster_longer_than_maximum_is_explicitly_infeasible(self):
        sr=48000
        with self.assertRaises(kernel.NotFeasible):
            shared._context_bounds(100000,100000+2*sr,300*sr,sr,1024,12)

    def test_invalid_units_and_indices_are_operational_errors(self):
        for sr,ms in ((0,128),(48000,float('nan')),(48000,0),(48000,-128)):
            with self.subTest(sr=sr,ms=ms),self.assertRaises(ValueError):
                shared._context_bounds(10000,12048,48000,sr,ms,12)
        for a,b,length in ((-1,2000,48000),(100,50,48000),(100,50000,48000)):
            with self.subTest(a=a,b=b),self.assertRaises(ValueError):
                shared._context_bounds(a,b,length,48000,128,12)


class RendererBoundaryIntegration(unittest.TestCase):
    def test_real_rescue_calls_and_receipts_use_bounded_ms(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'mixed.wav'
            sf.write(src,broad(2.0),48000,subtype='FLOAT')
            original=context.solve_context;calls=[]
            def observe(r,sr,*args,**kwargs):
                calls.append((len(r),sr))
                self.assertLessEqual(len(r)/sr,1.024+.5/48000)
                return original(r,sr,*args,**kwargs)
            with patch.object(context,'solve_context',side_effect=observe):
                out,stats=active.render_fixed_gain(src,root/'work',2.4,10**(-2.2/20),chunk_seconds=.25)
            self.assertTrue(calls);self.assertTrue(out.is_file())
            self.assertGreater(stats['context_rescue_regions'],0)
            markers=list((root/'work').rglob('CONTEXT_PATCHED.json'));self.assertEqual(len(markers),1)
            records=json.loads(markers[0].read_text())['records']
            for r in records:
                self.assertLessEqual(r['actual_context_ms'],r['context_ms']+.02)
                self.assertAlmostEqual(r['actual_context_ms'],r['context_frames']/48000*1000)
                self.assertLessEqual(r['actual_context_ms'],1024.02)
            m=shared.measure(out)
            self.assertLessEqual(m['true_peak_max_dbtp_estimate'],-2.0)

    def test_long_context_no_rescue_is_still_exact(self):
        import offline_peak_stream as original
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);src=root/'gentle.wav';sf.write(src,gentle(1.2),48000,subtype='FLOAT')
            a,_=original.render_fixed_gain(src,root/'a',4.,.78,chunk_seconds=.25)
            b,st=active.render_fixed_gain(src,root/'b',4.,.78,chunk_seconds=.25)
            np.testing.assert_array_equal(sf.read(a)[0],sf.read(b)[0])
            self.assertEqual(st['context_rescue_regions'],0)

if __name__=='__main__':unittest.main(verbosity=2)
