from pathlib import Path
import tempfile, unittest, json
from unittest.mock import patch
import numpy as np
import soundfile as sf
import offline_peak_lab as o

SR=48000

def mixture(seconds=1.1,sr=SR):
    t=np.arange(round(seconds*sr))/sr
    x=np.stack([.12*np.sin(2*np.pi*83*t)+.09*np.sin(2*np.pi*760*t),
                .11*np.sin(2*np.pi*83*t)+.08*np.sin(2*np.pi*800*t)],axis=1)
    x+=(.20*np.exp(-30*(t%.5))*np.sin(2*np.pi*63*t))[:,None]
    x+=(.02*np.exp(-120*(t%.25))*np.sin(2*np.pi*9500*t))[:,None]
    x[:round(.1*sr)]=0;x[-round(.1*sr):]=0
    return x

class InputAndBypass(unittest.TestCase):
    def test_invalid_rate(self):
        with self.assertRaises(ValueError):o.optimize(mixture(),22050)
    def test_invalid_shape(self):
        with self.assertRaises(ValueError):o.optimize(np.zeros(48000),SR)
    def test_nan_audio(self):
        x=mixture();x[100,0]=np.nan
        with self.assertRaises(ValueError):o.optimize(x,SR)
    def test_invalid_target(self):
        with self.assertRaises(ValueError):o.optimize(mixture(),SR,target_lufs=float('nan'))
        with self.assertRaises(ValueError):o.optimize(mixture(),SR,ceiling_dbtp=0)
    def test_invalid_config(self):
        with self.assertRaises(ValueError):o.Config(iterations=0).validate(SR)
        with self.assertRaises(ValueError):o.Config(residual_fraction=2).validate(SR)
    def test_silence(self):
        with self.assertRaises(ValueError):o.optimize(np.zeros((48000,2)),SR)
    def test_gain_only_is_constant_gain(self):
        x=mixture();y,r=o.optimize(x,SR,-24,-2)
        self.assertEqual(r['status'],'GAIN_ONLY');self.assertFalse(r['optimizer_used'])
        np.testing.assert_array_equal(y,x*10**(r['gain_db']/20))
    def test_source_array_unchanged(self):
        x=mixture();before=x.copy();o.optimize(x,SR,-12,-2);np.testing.assert_array_equal(x,before)
    def test_gain_budget(self):
        with self.assertRaises(o.NotFeasible):o.optimize(mixture()*1e-2,SR,-12,-2)

class Waveform(unittest.TestCase):
    def test_mixed_known_bass_kick_hf(self):
        x=mixture();y,r=o.optimize(x,SR,-12,-2)
        self.assertEqual(r['status'],'WAVEFORM_CANDIDATE')
        self.assertFalse(r['conventional_limiter_used'])
        self.assertLessEqual(abs(o.loudness(y,SR)+12),.03)
        self.assertLessEqual(o.true_peak(y,SR),-2)
        self.assertTrue(r['quality']['engineering_pass'])
    def test_exact_silence_and_length(self):
        x=mixture();y,r=o.optimize(x,SR,-12,-2)
        self.assertEqual(y.shape,x.shape);np.testing.assert_array_equal(y[x==0],0)
    def test_deterministic(self):
        x=mixture();a,_=o.optimize(x,SR,-12,-2);b,_=o.optimize(x,SR,-12,-2)
        np.testing.assert_array_equal(a,b)
    def test_mono_relation(self):
        x=mixture();x[:,1]=x[:,0]
        y,_=o.optimize(x,SR,-12,-2);np.testing.assert_array_equal(y[:,0],y[:,1])
    def test_antiphase_relation(self):
        x=mixture();x[:,1]=-x[:,0]
        y,_=o.optimize(x,SR,-12,-2);np.testing.assert_array_equal(y[:,0],-y[:,1])
    def test_one_silent_channel(self):
        x=mixture();x[:,1]=0
        # Use a lower loudness so preserving the silent channel stays feasible.
        y,_=o.optimize(x,SR,-17,-2);np.testing.assert_array_equal(y[:,1],0)
    def test_box_objective_improved(self):
        x=mixture(.5);x=x[14000:16048]*3
        up=o.signal.resample_poly(x,4,1,axis=0,window=('kaiser',10.5))
        y,r=o.solve_block(up,SR*4,.45,o.Config())
        self.assertTrue(r['active']);self.assertLessEqual(np.max(abs(y)),.45+1e-12)
        self.assertLess(r['objective'],r['initial_box_objective'])
    def test_infeasible_residual_does_not_clip(self):
        r=np.zeros((2048,2));r[1024]=2
        with self.assertRaises(o.NotFeasible):o.solve_block(r,SR*4,.4,o.Config())
    def test_boundary_peak_full_waveform_qc(self):
        x=mixture();x=np.roll(x,731,axis=0)
        y,r=o.optimize(x,SR,-12,-2)
        self.assertLessEqual(o.true_peak(y,SR),-2)
    def test_strong_change_veto(self):
        x=mixture();qa=o.quality_report(x,x*.5,SR,o.Config())
        self.assertFalse(qa['engineering_pass'])
    def test_native_sample_peak_is_not_tp(self):
        t=np.arange(SR)/SR;s=.8*np.sin(2*np.pi*12000*t+np.pi/4)
        x=np.column_stack((s,s))
        self.assertGreater(o.true_peak(x,SR),o.db(np.max(abs(x)))+2)
    def test_44100_gain_only(self):
        x=mixture(sr=44100);y,r=o.optimize(x,44100,-24,-2)
        self.assertEqual(y.shape,x.shape);self.assertLessEqual(o.true_peak(y,44100),-2)

class Publication(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        d=self.root/'input';d.mkdir();self.src=d/'曲.v1.wav';sf.write(self.src,mixture(),SR,subtype='FLOAT')
    def tearDown(self):self.tmp.cleanup()
    def test_saved_wav_and_proof(self):
        before=o.file_hash(self.src);r,p=o.run_file(self.src,self.root/'output',-12,-2)
        self.assertEqual(before,o.file_hash(self.src));self.assertEqual(r['output_sha256'],o.file_hash(p/'CANDIDATE.wav'))
        self.assertEqual(json.loads((p/'REPORT.json').read_text())['naturalness'],'NOT_LISTENING_VALIDATED')
    def test_no_overwrite(self):
        _,p=o.run_file(self.src,self.root/'output',-24,-2);h=o.file_hash(p/'CANDIDATE.wav')
        with self.assertRaises(FileExistsError):o.run_file(self.src,self.root/'output',-24,-2)
        self.assertEqual(h,o.file_hash(p/'CANDIDATE.wav'))
    def test_failure_has_no_published_audio(self):
        with patch.object(o,'optimize',side_effect=o.NotFeasible('forced gate failure')):
            with self.assertRaises(o.NotFeasible):o.run_file(self.src,self.root/'output')
        self.assertFalse(list((self.root/'output').glob('oppo_*')))
        self.assertFalse(list((self.root/'output').rglob('*.wav')))
    def test_source_directory_refused(self):
        with self.assertRaises(ValueError):o.run_file(self.src,self.src.parent/'output')

if __name__=='__main__':unittest.main(verbosity=2)
