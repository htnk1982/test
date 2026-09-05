from __future__ import annotations
from dataclasses import replace
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
import pyloudnorm as pyln

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import release_finish as r


def mix(sr=48000, seconds=2.6):
    t = np.arange(round(sr*seconds))/sr
    x = .05*np.sin(2*np.pi*220*t)+.02*np.cos(2*np.pi*441*t)
    # Sparse peaks need genuine limiting at -12 LUFS, not a gain-only bypass.
    for start in (.41, 1.14, 1.93):
        q = t-start
        x += .8*np.exp(-(q/.0018)**2)*np.cos(2*np.pi*900*q)
    return np.stack([x, .7*x], axis=1)


class ReleaseFinish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.root = Path(self.tmp.name)
        self.inputs = self.root/'inputs'; self.inputs.mkdir()
        self.ff = r.io.ffmpeg_path()
        if not self.ff: self.skipTest('FFmpeg unavailable')
    def tearDown(self): self.tmp.cleanup()
    def wav(self, name='source.wav', x=None, sr=48000):
        p=self.inputs/name; sf.write(p, mix(sr) if x is None else x, sr, subtype='FLOAT');return p
    def export(self, p=None, **kwargs):
        return r.run_file(p or self.wav(), self.root/'work', finished=True, **kwargs)
    def test_01_frozen_dsp_hashes(self):
        self.assertEqual(len(r.accepted.verify_dsp()),3)
    def test_02_invalid_config(self):
        for c in (replace(r.Config(), wav_lufs=np.nan), replace(r.Config(), wav_tp=1),
                  replace(r.Config(), oversample=1), replace(r.Config(), max_passes=0)):
            with self.assertRaises(ValueError): c.validate()
    def test_03_gain_only_bypasses_limiter(self):
        sr=48000;t=np.arange(sr)/sr
        p=self.wav(x=np.stack([.05*np.sin(2*np.pi*1000*t)]*2,axis=1))
        rep,out=self.export(p,write_mp3=False)
        self.assertFalse(rep['wave']['limiter_used'])
        self.assertLess(abs(rep['wave']['output_metrics']['lufs_i']+12),.01)
        self.assertEqual(sf.info(out/r.WAV_NAME).subtype,'PCM_24')
    def test_04_limiting_meets_both_targets(self):
        rep,out=self.export(write_mp3=False);m=rep['wave']['output_metrics']
        self.assertTrue(rep['wave']['limiter_used']);self.assertLess(abs(m['lufs_i']+12),.03)
        self.assertLessEqual(m['true_peak_dbtp_estimate'],-2)
        self.assertGreater(rep['wave']['predicted_gain_only_tp_dbtp'],-2)
    def test_05_mp3_from_delivered_wav_minus14(self):
        rep,out=self.export()
        self.assertLess(abs(rep['codec']['metrics']['lufs_i']+14),.03)
        self.assertLessEqual(rep['codec']['metrics']['true_peak_dbtp_estimate'],-2)
        self.assertEqual(rep['codec']['encoded_from_delivered_wav_sha256'],r.io.file_hash(out/r.WAV_NAME))
        self.assertFalse(rep['codec']['limiter_used'])
        self.assertAlmostEqual(rep['codec']['constant_gain_db'],-2,delta=.05)
    def test_06_original_unchanged(self):
        p=self.wav();h=r.io.file_hash(p);self.export(p,write_mp3=False)
        self.assertEqual(h,r.io.file_hash(p))
    def test_07_idempotent_rerun(self):
        p=self.wav();a,x=self.export(p,write_mp3=False);b,y=self.export(p,write_mp3=False)
        self.assertEqual(x,y);self.assertEqual(b['rerun_status'],'IDEMPOTENT_SKIP')
    def test_08_foreign_result_refused(self):
        p=self.wav();_,out=self.export(p,write_mp3=False);q=out/r.WAV_NAME;q.write_bytes(b'foreign')
        with self.assertRaises(RuntimeError): self.export(p,write_mp3=False)
        self.assertEqual(q.read_bytes(),b'foreign')
    def test_09_no_repeated_note_hftc_in_finished_mode(self):
        p=self.wav()
        with patch.object(r.accepted,'run_file',side_effect=AssertionError('double DSP')):
            rep,_=self.export(p,write_mp3=False)
        self.assertFalse(rep['note_hftc_applied'])
    def test_10_raw_mode_calls_frozen_chain_once(self):
        p=self.wav(); fake=self.root/'fake';fake.mkdir();shutil.copyfile(p,fake/'FINISHED.wav')
        with patch.object(r.accepted,'run_file',return_value=({'status':'test_fixture'},fake)) as func:
            rep,_=r.run_file(p,self.root/'work',finished=False,write_mp3=False)
        self.assertEqual(func.call_count,1);self.assertTrue(rep['note_hftc_applied'])
    def test_11_silent_source_refused(self):
        p=self.wav(x=np.zeros((48000,2)))
        with self.assertRaises(ValueError): self.export(p,write_mp3=False)
    def test_12_nonfinite_refused(self):
        x=mix();x[100,0]=np.nan;p=self.wav(x=x)
        with self.assertRaises(ValueError): self.export(p,write_mp3=False)
    def test_13_release_output_refeed_refused(self):
        _,out=self.export(write_mp3=False)
        p=self.inputs/'renamed.wav';shutil.copyfile(out/r.WAV_NAME,p)
        with self.assertRaisesRegex(ValueError,'Already released'):
            self.export(p,write_mp3=False)
    def test_14_resume_after_wav_pcm_exact(self):
        p=self.wav()
        with self.assertRaisesRegex(RuntimeError,'INTERRUPTION'):
            self.export(p,write_mp3=False,interrupt_after='wav')
        a,x=self.export(p,write_mp3=False)
        b,y=r.run_file(p,self.root/'clean',finished=True,write_mp3=False)
        self.assertEqual(r.io.pcm_hash(x/r.WAV_NAME),r.io.pcm_hash(y/r.WAV_NAME))
    def test_15_proportional_stereo_stays_proportional(self):
        _,out=self.export(write_mp3=False);y,sr=sf.read(out/r.WAV_NAME,always_2d=True)
        self.assertLess(np.max(np.abs(y[:,1]-.7*y[:,0])),3e-7)
    def test_16_delay_compensation_and_tail_length(self):
        sr=48000;x=np.zeros((sr*2,2));x[[100,10000,len(x)-1]]=1
        p=self.wav(x=x);q=self.root/'raw.wav'
        r.limited_pass(p,q,self.ff,0,-2.05,r.Config())
        y,_=sf.read(q,always_2d=True)
        self.assertEqual(y.shape,x.shape)
        self.assertEqual(np.argmax(np.abs(y[80:120,0]))+80,100)
        self.assertGreater(abs(y[-1,0]),.2)
    def test_17_truepeak_observes_intersample(self):
        sr=48000;t=np.arange(sr)/sr
        x=.7*np.sin(2*np.pi*(sr/4)*t+np.pi/4);p=self.wav(x=np.stack([x,x],axis=1))
        m=r.measure(p)
        self.assertGreater(m['true_peak_dbtp_estimate']-m['sample_peak_dbfs'],2)
    def test_18_pcm24_silence_and_determinism(self):
        p=self.wav(x=np.zeros((48000,2)));a=self.root/'a.wav';b=self.root/'b.wav'
        r.quantize24(p,a);r.quantize24(p,b)
        self.assertEqual(r.io.pcm_hash(a),r.io.pcm_hash(b));self.assertEqual(np.max(np.abs(sf.read(a)[0])),0)
    def test_19_44100_and_96000_exports(self):
        for sr in (44100,96000):
            p=self.wav(f'input{sr}.wav',sr=sr)
            rep,_=self.export(p)
            self.assertEqual(rep['wave']['output_metrics']['samplerate'],sr)
            self.assertEqual(rep['codec']['samplerate'],sr if sr==44100 else 48000)
    def test_20_no_publish_when_pass_budget_exhausted(self):
        p=self.wav()
        with self.assertRaisesRegex(RuntimeError,'pass budget'):
            self.export(p,write_mp3=False,cfg=replace(r.Config(),max_passes=1,tolerance_lu=.001))
        self.assertFalse(any((self.root/'work').glob('*/RESULT')))
    def test_21_output_inside_input_refused(self):
        p=self.wav()
        with self.assertRaisesRegex(ValueError,'outside'):
            r.run_file(p,self.inputs/'output',finished=True,write_mp3=False)
    def test_22_decoder_pcm_format_not_mp3_as_master(self):
        p=self.inputs/'not_a_source.mp3';p.write_bytes(b'not lossless')
        with self.assertRaisesRegex(ValueError,'Lossless'):
            r.run_file(p,self.root/'work',finished=True)
    def test_23_constant_gain_not_enough_to_fake_target(self):
        rep,_=self.export(write_mp3=False)
        self.assertGreater(rep['wave']['loudness_loss_due_to_peak_processing_lu'],0)
        self.assertGreater(len(rep['wave']['trials']),1)

if __name__=='__main__':unittest.main(verbosity=2)
