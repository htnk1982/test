from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
from scipy import signal
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hf_temporal_contrast_lab as lab


def fixture(sr=48000, length=4.0):
    t = np.arange(int(round(sr * length))) / sr
    # A quiet HF bed plus strong HF bursts, under a low/mid tonal mixture.
    env = np.full(len(t), .006)
    for c in np.arange(.65, length - .25, .8):
        env += .065 * np.exp(-((t - c) / .07) ** 2)
    hf = env * (np.sin(2*np.pi*10000*t) + .5*np.cos(2*np.pi*13000*t))
    low = .10*np.sin(2*np.pi*90*t) + .06*np.cos(2*np.pi*900*t)
    x = np.stack((low + hf, .8*low + .65*hf), axis=1)
    return x, sr


class HFTCRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root/'inputs').mkdir()
    def tearDown(self): self.tmp.cleanup()
    def source(self, x=None, sr=48000):
        if x is None: x, sr = fixture(sr=sr)
        p=self.root/'inputs'/'input.wav'
        sf.write(p,x,sr,subtype='FLOAT');return p
    def process(self, p, cfg=lab.Config(), where='job'):
        times,gain,stats=lab.analyze_control(p,cfg)
        raw,cache=lab.render_raw(p,self.root/where,times,gain,cfg)
        y,sr=sf.read(raw,always_2d=True)
        return y,(times,gain,stats,cache,raw)
    def test_01_scope_and_configuration_reject_invalid_values(self):
        for cfg in (replace(lab.Config(),max_cut_db=1.1),replace(lab.Config(),low_hz=7000),
                    replace(lab.Config(),max_cut_db=float('nan'))):
            with self.assertRaises(ValueError): cfg.validate(48000)
    def test_02_fir_stopband_and_passband(self):
        for sr in (44100,48000,96000):
            h=lab.coefficients(sr,lab.Config())
            f,z=signal.freqz(h,worN=32768,fs=sr)
            stop=(f<8000)|(f>16000)
            self.assertLess(np.max(np.abs(z[stop])),1e-4)
            self.assertLess(abs(abs(z[np.argmin(abs(f-10000))])-1),1e-4)
    def test_03_amount_zero_is_exact_pcm_noop(self):
        p=self.source();x,_=sf.read(p,always_2d=True)
        y,_=self.process(p,replace(lab.Config(),max_cut_db=0))
        self.assertTrue(np.array_equal(x,y))
    def test_04_silence_is_exact_noop(self):
        p=self.source(np.zeros((48000,2)));y,s=self.process(p)
        self.assertTrue(np.array_equal(y,np.zeros_like(y)));self.assertTrue(np.all(s[1]==1))
    def test_05_out_of_band_tones_unchanged(self):
        sr=48000;t=np.arange(2*sr)/sr
        for hz in (80,1800,19000):
            x=.1*np.sin(2*np.pi*hz*t);p=self.source(np.stack((x,x),axis=1))
            y,_=self.process(p,where='tone'+str(hz));dry,_=sf.read(p,always_2d=True)
            self.assertLess(np.max(np.abs(y-dry)),1e-7)
    def test_06_weak_hf_cut_strong_hf_protected(self):
        n=801;dt=.005;p=np.full(n,1e-4)
        for c in (120,280,440,600,760):p[c-15:c+16]=.01
        gain,stats=lab.plan_gain(p,p,np.ones(n)*.04,dt,lab.Config())
        self.assertAlmostEqual(stats['max_cut_db'],1.0)
        for c in (120,280,440,600,760):self.assertEqual(gain[c],1.0)
        self.assertLess(gain[200],.90)
        self.assertEqual(stats['protected_max_cut_db'],0.0)
    def test_07_constant_hf_is_not_static_eq(self):
        p=np.full(801,.01)
        g,_=lab.plan_gain(p,p,p*2,.005,lab.Config())
        self.assertTrue(np.all(g==1))
    def test_08_onset_lookaround_is_protected(self):
        p=np.full(601,1e-4);p[300:320]=.01
        g,_=lab.plan_gain(p,p,np.full(601,.05),.005,lab.Config())
        self.assertTrue(np.all(g[295:326]==1))
    def test_09_no_filter_tails_into_digital_silence(self):
        x,sr=fixture();x[:sr//3]=0;x[-sr//3:]=0;p=self.source(x)
        y,_=self.process(p)
        self.assertTrue(np.all(y[:sr//3]==0));self.assertTrue(np.all(y[-sr//3:]==0))
    def test_10_stereo_proportionality(self):
        x,sr=fixture();x[:,1]=x[:,0]*.5;p=self.source(x)
        y,_=self.process(p)
        self.assertLess(np.max(np.abs(y[:,1]-.5*y[:,0])),1e-7)
    def test_11_antiphase_hf_does_not_cancel_detector(self):
        x,sr=fixture();x[:,1]=-x[:,0];p=self.source(x)
        y,s=self.process(p)
        self.assertGreater(s[2]['max_cut_db'],.1)
        self.assertTrue(np.array_equal(y[:,1],-y[:,0]))
    def test_12_centered_filter_no_delay(self):
        sr=48000;t=np.arange(sr)/sr;x=np.sin(2*np.pi*11000*t)
        b=lab.extract_band(np.stack((x,x),axis=1),lab.coefficients(sr,lab.Config()))[:,0]
        self.assertGreater(np.corrcoef(b[2000:-2000],x[2000:-2000])[0,1],.99999999)
    def test_13_analysis_chunk_partition_invariance(self):
        p=self.source();a=lab.analyze_control(p,lab.Config());b=lab.analyze_control(p,replace(lab.Config(),chunk_seconds=.413))
        self.assertTrue(np.array_equal(a[0],b[0]));self.assertLess(np.max(abs(a[1]-b[1])),1e-9)
    def test_14_render_partition_invariance(self):
        p=self.source();times,gain,_=lab.analyze_control(p,lab.Config())
        a,_=lab.render_raw(p,self.root/'a',times,gain,lab.Config())
        b,_=lab.render_raw(p,self.root/'b',times,gain,replace(lab.Config(),chunk_seconds=.413))
        x,_=sf.read(a);y,_=sf.read(b)
        self.assertLess(np.max(abs(x-y)),1e-7)
    def test_15_committed_chunk_resume_identical_pcm(self):
        p=self.source();cfg=replace(lab.Config(),chunk_seconds=.5)
        t,g,_=lab.analyze_control(p,cfg)
        with self.assertRaisesRegex(RuntimeError,'TEST_INTERRUPTION'):
            lab.render_raw(p,self.root/'resume',t,g,cfg,interrupt_after=2)
        a,cache=lab.render_raw(p,self.root/'resume',t,g,cfg)
        b,_=lab.render_raw(p,self.root/'clean',t,g,cfg)
        self.assertEqual(cache['reused_chunks'],2)
        self.assertEqual(lab.io.pcm_hash(a),lab.io.pcm_hash(b))
    def test_16_corrupt_chunk_recomputed(self):
        p=self.source();y,s=self.process(p)
        chunk=next((self.root/'job').glob('chunks_*/*.wav'));chunk.write_bytes(b'broken')
        y2,s2=self.process(p)
        self.assertEqual(s2[3]['computed_chunks'],1);self.assertTrue(np.array_equal(y,y2))
    def test_17_source_unchanged(self):
        p=self.source();h=lab.io.file_hash(p);self.process(p)
        self.assertEqual(h,lab.io.file_hash(p))
    def test_18_wrong_source_hash_rejected(self):
        p=self.source()
        with self.assertRaisesRegex(ValueError,'accepted'):
            lab.run_job(p,self.root/'run',write_mp3=False)
    def test_19_nonfinite_samples_rejected(self):
        x=np.zeros((1024,2));x[1,0]=np.nan
        with self.assertRaises(ValueError):lab.extract_band(x,lab.coefficients(48000,lab.Config()))
    def test_20_bounded_smooth_control(self):
        p=self.source();t,g,stats=lab.analyze_control(p,lab.Config())
        d=-20*np.log10(g)
        self.assertTrue(np.all(d>=-1e-12));self.assertLessEqual(np.max(d),1+1e-12)
        self.assertLess(np.max(np.abs(np.diff(d))),.2)
    def test_21_full_pipeline_pcm_codec_idempotence_and_foreign_protection(self):
        x,sr=fixture();x*=10**((-14-lab.io.pyln.Meter(sr).integrated_loudness(x))/20)
        p=self.source(x);h=lab.io.file_hash(p)
        report,out=lab.run_job(p,self.root/'run',expected_hash=h,write_mp3=bool(lab.io.ffmpeg_path()))
        self.assertEqual(lab.io.file_hash(out/'CONTROL_B.wav'),h)
        self.assertLess(abs(report['candidate_metrics']['lufs_i']-report['baseline_metrics']['lufs_i']),.01)
        _,again=lab.run_job(p,self.root/'run',expected_hash=h,write_mp3=bool(lab.io.ffmpeg_path()))
        self.assertEqual(out,again)
        (out/'HFTC_CANDIDATE.wav').write_bytes(b'foreign')
        with self.assertRaisesRegex(RuntimeError,'modified'):
            lab.run_job(p,self.root/'run',expected_hash=h,write_mp3=bool(lab.io.ffmpeg_path()))
    def test_22_output_inside_source_directory_rejected(self):
        p=self.source()
        with self.assertRaisesRegex(ValueError,'outside'):
            lab.run_job(p,p.parent/'new',expected_hash=None,write_mp3=False)
    def test_23_waveform_does_not_import_or_patch_production(self):
        text=(ROOT/'hf_temporal_contrast_lab.py').read_text()
        for token in ('from pdrm_engine','import pdrm_runtime','import pdrm_operator_lab','setattr(io,'):
            self.assertNotIn(token,text)
    def test_24_synthetic_mixture_low_mid_preserved(self):
        p=self.source();dry,sr=sf.read(p);y,_=self.process(p)
        ff,ps=signal.welch((y-dry).T,fs=sr,nperseg=8192,axis=-1)
        ratio=np.sum(ps[:,ff<7900])/max(np.sum(ps),1e-24)
        self.assertLess(10*np.log10(max(ratio,1e-24)),-60)


if __name__=='__main__': unittest.main(verbosity=2)
