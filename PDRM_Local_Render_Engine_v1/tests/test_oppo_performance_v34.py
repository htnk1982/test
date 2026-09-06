from pathlib import Path
import sys,tempfile,unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
from scipy import fft
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import offline_peak_lab as kernel
import offline_peak_context as dense
import offline_peak_context_v34 as sparse
import offline_peak_stream_v32 as stream32
import offline_peak_stream_v34 as stream34
import auto_peak_v34 as auto

SR=48000

def crest_highrate(ms=128):
    sr=SR*4;n=round(ms*sr/1000);t=np.arange(n)/sr
    x=np.column_stack((.24*np.sin(2*np.pi*430*t)+.15*np.sin(2*np.pi*1570*t),.22*np.sin(2*np.pi*430*t)+.14*np.sin(2*np.pi*1610*t)))
    x+=.82*np.exp(-.5*((t-ms/2000)/.000055)**2)[:,None]
    return x,sr

def gentle(seconds=.7):
    t=np.arange(round(SR*seconds))/SR
    x=np.column_stack((.08*np.sin(2*np.pi*83*t)+.05*np.sin(2*np.pi*760*t),.075*np.sin(2*np.pi*83*t)+.045*np.sin(2*np.pi*820*t)))
    x[:128]=0;x[-128:]=0;return x

class SparseMath(unittest.TestCase):
    def test_sparse_spectral_operator_is_full_fft_principal_block(self):
        rng=np.random.default_rng(7);n=4096;weights=np.abs(rng.normal(size=n//2+1))+1;lo,hi=1700,2020
        x=rng.normal(size=(hi-lo,2));full=np.zeros((n,2));full[lo:hi]=x
        expected=fft.irfft(weights[:,None]*fft.rfft(full,axis=0),n=n,axis=0)[lo:hi]
        op,size=sparse._toeplitz_spectral_operator(weights,n,lo,hi);actual=op(x)
        self.assertLess(np.max(np.abs(expected-actual)),1e-11);self.assertLess(size,n)
    def test_sparse_solver_matches_dense_solver(self):
        r,sr=crest_highrate(128);cfg=dense.ContextConfig(iterations=160)
        a,sa=dense.solve_context(r,sr,.72,kernel.Config(),cfg=cfg)
        b,sb=sparse.solve_context(r,sr,.72,kernel.Config(),cfg=cfg)
        self.assertLess(np.max(np.abs(a-b)),2e-7);self.assertEqual(sa['iterations'],sb['iterations'])
        self.assertTrue(all(sb['local_metrics']['gates'].values()))
    def test_long_context_reduces_fft_work_without_relaxing_config(self):
        r,sr=crest_highrate(1024);cfg=dense.ContextConfig(iterations=80)
        y,st=sparse.solve_context(r,sr,.72,kernel.Config(),cfg=cfg)
        self.assertLessEqual(np.max(abs(y)),.72+2e-10);self.assertEqual(st['solver'],'SPARSE_EXACT_TOEPLITZ')
        self.assertLess(st['solver_active_fraction'],.10);self.assertLess(st['solver_fft_samples'],st['solver_total_samples']//5)
        self.assertEqual(cfg,dense.ContextConfig(iterations=80))
    def test_long_context_reports_live_solver_progress(self):
        class P:
            def __init__(self):self.calls=[]
            def set(self,*args):self.calls.append(args)
        p=P();r,sr=crest_highrate(256)
        with sparse.bind_progress(p):sparse.solve_context(r,sr,.72,kernel.Config(),cfg=dense.ContextConfig(iterations=80))
        stages=[c[0] for c in p.calls];self.assertTrue(any(s.startswith('OPPO_CONTEXT_SOLVE_') for s in stages))
        self.assertTrue(any(c[1]>0 for c in p.calls if c[0].startswith('OPPO_CONTEXT_SOLVE_')))

class WholeTrackAndAuto(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'gentle.wav';sf.write(self.src,gentle(),SR,subtype='FLOAT')
    def tearDown(self):self.tmp.cleanup()
    def test_no_rescue_path_is_sample_identical_to_v32(self):
        a,_=stream32.render_fixed_gain(self.src,self.root/'old',4.0,.78,chunk_seconds=.25)
        b,_=stream34.render_fixed_gain(self.src,self.root/'new',4.0,.78,chunk_seconds=.25)
        xa,_=sf.read(a,dtype='float64',always_2d=True);xb,_=sf.read(b,dtype='float64',always_2d=True);np.testing.assert_array_equal(xa,xb)
    def test_operational_error_still_never_reaches_limiter(self):
        with patch.object(auto.oppo,'fit',side_effect=RuntimeError('integrity failure')),patch.object(auto.limiter,'fit') as lim:
            with self.assertRaisesRegex(RuntimeError,'integrity failure'):auto.fit(self.src,self.root/'x.wav',self.root/'w',-12,-2)
            lim.assert_not_called()

if __name__=='__main__':unittest.main(verbosity=2)
