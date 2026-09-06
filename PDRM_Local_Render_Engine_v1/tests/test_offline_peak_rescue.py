from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import offline_peak_lab as old
import offline_peak_rescue as rescue
import offline_peak_stream as stream0
import offline_peak_stream_v31 as stream1

SR=48000

def block(width=.00005,amp=1.5):
    sr=SR*4;n=8192;t=np.arange(n)/sr
    r=np.column_stack((.25*np.sin(2*np.pi*80*t)+.20*np.sin(2*np.pi*1000*t),
                       .24*np.sin(2*np.pi*80*t)+.18*np.sin(2*np.pi*1200*t)))
    g=np.exp(-.5*((t-.02)/width)**2)
    r+=amp*g[:,None]
    return r,sr

def track(seconds=.75,sharp=True):
    t=np.arange(round(SR*seconds))/SR
    x=np.column_stack((.10*np.sin(2*np.pi*83*t)+.08*np.sin(2*np.pi*770*t),
                       .095*np.sin(2*np.pi*83*t)+.07*np.sin(2*np.pi*820*t)))
    if sharp:
        for when in (.17,.39,.58):
            x+=1.0*np.exp(-.5*((t-when)/.00006)**2)[:,None]
    x[:100]=0;x[-100:]=0
    return x

class RescueBlock(unittest.TestCase):
    def test_old_budget_failure_is_rescued(self):
        r,sr=block();ceiling=10**(-2.12/20)
        with self.assertRaisesRegex(old.NotFeasible,'Residual budget'):
            old.solve_block(r,sr,ceiling,old.Config())
        y,st=rescue.solve_block(r,sr,ceiling,old.Config())
        self.assertTrue(st['rescue']);self.assertLessEqual(np.max(abs(y)),ceiling+2e-10)
        self.assertTrue(all(st['local_gates'].values()))
    def test_old_feasible_result_is_not_a_rescue_contract(self):
        r,sr=block(width=.0002);ceiling=10**(-2.12/20)
        y,st=old.solve_block(r,sr,ceiling,old.Config())
        self.assertTrue(st['active']);self.assertLessEqual(np.max(abs(y)),ceiling+2e-10)
    def test_large_rewrite_still_refused(self):
        r,sr=block(amp=4.0);ceiling=.55
        with self.assertRaisesRegex(old.NotFeasible,'hard cap'):
            rescue.solve_block(r,sr,ceiling,old.Config())
    def test_exact_mono_relation(self):
        r,sr=block();r[:,1]=r[:,0]
        y,_=rescue.solve_block(r,sr,10**(-2.12/20),old.Config())
        np.testing.assert_array_equal(y[:,0],y[:,1])
    def test_exact_antiphase_relation(self):
        r,sr=block();r[:,1]=-r[:,0]
        y,_=rescue.solve_block(r,sr,10**(-2.12/20),old.Config())
        np.testing.assert_array_equal(y[:,0],-y[:,1])
    def test_locked_samples_stay_exact(self):
        r,sr=block();locked=np.zeros_like(r,dtype=bool);locked[::4]=r[::4]==0
        y,_=rescue.solve_block(r,sr,10**(-2.12/20),old.Config(),locked)
        np.testing.assert_array_equal(y[locked],r[locked])
    def test_invalid_rescue_config(self):
        with self.assertRaises(ValueError):rescue.RescueConfig(max_peak_rewrite_fraction=.9).validate(SR*4)
    def test_local_guard_can_refuse(self):
        r,sr=block()
        cfg=rescue.RescueConfig(local_residual_budget_db=-50)
        with self.assertRaisesRegex(old.NotFeasible,'local naturalness gate'):
            rescue.solve_block(r,sr,10**(-2.12/20),old.Config(),rescue=cfg)

class WholeTrack(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.src=self.root/'crest.wav';sf.write(self.src,track(),SR,subtype='FLOAT')
    def tearDown(self):self.tmp.cleanup()
    def test_v31_rescues_track_old_stream_rejects(self):
        # Use a direct render ceiling/gain pair so this specifically exercises
        # the old local-budget failure, not the outer LUFS search.
        with self.assertRaises(old.NotFeasible):
            stream0.render_fixed_gain(self.src,self.root/'old',2.4,10**(-2.2/20),chunk_seconds=.25)
        out,st=stream1.render_fixed_gain(self.src,self.root/'new',2.4,10**(-2.2/20),chunk_seconds=.25)
        self.assertGreater(st['rescue_frame_evaluations'],0);self.assertTrue(out.is_file())
    def test_old_feasible_windows_are_bit_identical(self):
        p=self.root/'gentle.wav';sf.write(p,track(sharp=False),SR,subtype='FLOAT')
        a,_=stream0.render_fixed_gain(p,self.root/'a',5.0,.72,chunk_seconds=.25)
        with patch.object(rescue,'solve_block',side_effect=AssertionError('rescue must not run')):
            b,st=stream1.render_fixed_gain(p,self.root/'b',5.0,.72,chunk_seconds=.25)
        xa,_=sf.read(a,dtype='float64',always_2d=True);xb,_=sf.read(b,dtype='float64',always_2d=True)
        np.testing.assert_array_equal(xa,xb);self.assertEqual(st['rescue_frame_evaluations'],0)
    def test_restart_reuses_rescued_chunks(self):
        with self.assertRaises(InterruptedError):
            stream1.render_fixed_gain(self.src,self.root/'resume',2.4,10**(-2.2/20),
                                      chunk_seconds=.25,interrupt_after=1)
        out,st=stream1.render_fixed_gain(self.src,self.root/'resume',2.4,10**(-2.2/20),chunk_seconds=.25)
        self.assertTrue(out.is_file());self.assertGreaterEqual(st['reused_chunks'],1)
    def test_source_unchanged(self):
        before=stream1.io.file_hash(self.src)
        stream1.render_fixed_gain(self.src,self.root/'work',2.4,10**(-2.2/20),chunk_seconds=.25)
        self.assertEqual(before,stream1.io.file_hash(self.src))
    def test_no_limiter_fallback_in_new_modules(self):
        text=(Path(rescue.__file__).read_text(encoding='utf-8')+
              Path(stream1.__file__).read_text(encoding='utf-8'))
        self.assertNotIn('alimiter=',text);self.assertNotIn('distribution_peak',text)

if __name__=='__main__':unittest.main(verbosity=2)
