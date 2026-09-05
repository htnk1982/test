from pathlib import Path
import shutil, sys, tempfile, unittest
from unittest.mock import patch, MagicMock
import numpy as np
import soundfile as sf
from scipy import signal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
import distribution_finish as app
import distribution_peak as peak
from test_note_sub_lab import notes

class DistributionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.input=self.root/'input';self.input.mkdir();self.output=self.root/'選択した出力'
        self.source=self.input/'テスト.wav';self.x,self.sr=notes(frequencies=(82.406889,));self.x*=.4
        sf.write(self.source,self.x,self.sr,subtype='FLOAT');self.ff=app.io.ffmpeg_path()
    def tearDown(self):self.tmp.cleanup()
    def run_app(self,**kw):return app.run_file(self.source,self.output,**kw)
    def test_01_frozen_dsp(self):self.assertEqual(app.legacy.verify_dsp(),app.legacy.DSP_SHA256)
    def test_02_he_exact_transfer(self):
        u=np.linspace(-1,1,1000,dtype='float32');a=.105;q=.30
        expected=(u-a*(u**3)+q*(a*a)*(u**5)).astype('float32')
        self.assertTrue(np.array_equal(app.harmonic_elasticity(u),expected))
    def test_03_he_path_and_source_unchanged(self):
        h=app.io.file_hash(self.source);d=self.root/'he.wav';app.render_harmonic(self.source,d)
        up=signal.resample_poly(self.x,4,1,axis=0,window=('kaiser',10.5)).astype('float32')
        expected=signal.resample_poly(app.harmonic_elasticity(up),1,4,axis=0,window=('kaiser',10.5)).astype('float32')
        y,_=sf.read(d,dtype='float32',always_2d=True)
        self.assertTrue(np.array_equal(y,expected));self.assertEqual(h,app.io.file_hash(self.source))
    def test_04_gain_only(self):
        r=peak.fit(self.source,self.root/'fit.wav',self.root/'work',-18,-2,self.ff)
        self.assertFalse(r['limiter_engaged']);self.assertAlmostEqual(r['output_metrics']['lufs_i'],-18,places=4)
    def test_05_high_crest_really_limited(self):
        x=self.x.copy();x[len(x)//2]=.99;sf.write(self.source,x,self.sr,subtype='FLOAT')
        r=peak.fit(self.source,self.root/'fit.wav',self.root/'work',-12,-2,self.ff)
        self.assertTrue(r['limiter_engaged']);self.assertAlmostEqual(r['output_metrics']['lufs_i'],-12,places=3)
        self.assertLessEqual(r['output_metrics']['true_peak_max_dbtp_estimate'],-2)
    def test_06_stereo_link_ratio_and_antiphase(self):
        sr=48000;t=np.arange(sr)/sr;x=.85*np.cos(2*np.pi*997*t)
        for ratio in (.25,-1):
            sf.write(self.source,np.column_stack((x,x*ratio)),sr,subtype='FLOAT')
            d=self.root/'lim.wav';peak.render_limited(self.source,d,3,-2.2,self.ff)
            y,_=sf.read(d,always_2d=True);self.assertLess(np.max(np.abs(y[:,1]-ratio*y[:,0])),2e-7)
    def test_07_latency_edges_and_length(self):
        sr=44100;x=np.zeros((sr+17,2));ix=[0,1234,sr+16];x[ix]=.9
        sf.write(self.source,x,sr,subtype='FLOAT');d=self.root/'lim.wav'
        peak.render_limited(self.source,d,6,-2.2,self.ff);y,r=sf.read(d,always_2d=True)
        self.assertEqual(len(y),len(x));self.assertEqual(r,sr)
        for i in ix:
            a,b=max(0,i-8),min(len(y),i+9);self.assertEqual(a+np.argmax(np.abs(y[a:b,0])),i)
    def test_08_pipeline_targets_and_source(self):
        h=app.io.file_hash(self.source);r,out=self.run_app(write_mp3=True)
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(h,app.io.file_hash(self.source))
        self.assertTrue(r['harmonic_elasticity_applied']);self.assertTrue(r['peak_protection_implemented'])
        for n in app.FILES:self.assertTrue((out/n).is_file())
        for key,target in (('master_metrics',-12),('listen_metrics',-14),('codec_metrics',-14)):
            self.assertLess(abs(r[key]['lufs_i']-target),.1 if key=='codec_metrics' else .03)
            self.assertLessEqual(r[key]['true_peak_max_dbtp_estimate'],-2)
    def test_09_listen_constant_gain_from_master(self):
        r,out=self.run_app(write_mp3=False)
        a,_=sf.read(out/app.FILES[0],always_2d=True);b,_=sf.read(out/app.FILES[1],always_2d=True)
        self.assertLess(np.max(np.abs(b-a*10**(r['listen_gain_db']/20))),2**-23+1e-12)
        for p in app.FILES[:2]:self.assertEqual(sf.info(out/p).subtype,'PCM_24')
    def test_10_mp3_is_encoded_from_minus14_wav(self):
        r,out=self.run_app(write_mp3=True);d=self.root/'again.mp3'
        peak.execute(self.ff,['-i',str(out/app.FILES[1]),'-map','0:a:0','-map_metadata','-1','-ar',str(self.sr),
               '-c:a','libmp3lame','-b:a','320k',str(d)],self.root/'ff.log')
        self.assertEqual(app.io.file_hash(d),app.io.file_hash(out/app.FILES[2]))
    def test_11_idempotence(self):
        _,out=self.run_app(write_mp3=False);h=app.io.file_hash(out/app.FILES[0])
        r,out2=self.run_app(write_mp3=False);self.assertEqual(out,out2)
        self.assertEqual(r['rerun_status'],'IDEMPOTENT_SKIP');self.assertEqual(h,app.io.file_hash(out/app.FILES[0]))
    def test_12_foreign_output_protected(self):
        _,out=self.run_app(write_mp3=False);p=out/app.FILES[0];p.write_bytes(b'edited')
        with self.assertRaisesRegex(RuntimeError,'modified'):self.run_app(write_mp3=False)
        self.assertEqual(p.read_bytes(),b'edited')
    def test_13_resume_after_note_identical(self):
        with self.assertRaisesRegex(RuntimeError,'AFTER_NOTE'):self.run_app(write_mp3=False,interrupt_after='note')
        self.assertFalse(any(self.output.glob('*__PDRM_*')))
        _,a=self.run_app(write_mp3=False);_,b=app.run_file(self.source,self.root/'clean',write_mp3=False)
        self.assertEqual(app.io.pcm_hash(a/app.FILES[0]),app.io.pcm_hash(b/app.FILES[0]))
    def test_14_renamed_result_rejected(self):
        _,out=self.run_app(write_mp3=False);p=self.input/'renamed.wav';shutil.copyfile(out/app.FILES[0],p)
        with self.assertRaisesRegex(ValueError,'already been processed'):app.run_file(p,self.output,write_mp3=False)
        with self.assertRaisesRegex(ValueError,'Already-processed'):app.run_file(out/app.FILES[1],self.root/'new',write_mp3=False)
    def test_15_same_folder_as_source_is_safe(self):
        h=app.io.file_hash(self.source);_,out=app.run_file(self.source,self.input,write_mp3=False)
        self.assertEqual(out.parent,self.input);self.assertEqual(h,app.io.file_hash(self.source))
    def test_16_silence_no_false_completion(self):
        sf.write(self.source,np.zeros((48000,2)),48000,subtype='FLOAT')
        with self.assertRaisesRegex(ValueError,'Silent'):self.run_app(write_mp3=False)
        self.assertFalse(any(self.output.glob('*__PDRM_*')))
    def test_17_nonfinite_rejected(self):
        self.x[100,0]=np.nan;sf.write(self.source,self.x,self.sr,subtype='FLOAT')
        with self.assertRaisesRegex(ValueError,'Non-finite'):self.run_app(write_mp3=False)
    def test_18_mono_rejected(self):
        sf.write(self.source,self.x[:,0],self.sr,subtype='FLOAT')
        with self.assertRaisesRegex(ValueError,'Stereo'):self.run_app(write_mp3=False)
    def test_19_codec_failure_no_publish(self):
        original=peak.execute
        def hook(ff,args,log,progress=None,stage='FFMPEG'):
            if stage=='ENCODE_MP3_FROM_14_WAV':raise RuntimeError('injected codec')
            return original(ff,args,log,progress,stage)
        with patch.object(peak,'execute',side_effect=hook):
            with self.assertRaisesRegex(RuntimeError,'injected codec'):self.run_app(write_mp3=True)
        self.assertFalse(any(self.output.glob('*__PDRM_*')))
    def test_20_flac_44k_and_96k_mp3(self):
        for sr in (44100,96000):
            x,_=notes(sr=sr,frequencies=(82.406889,));p=self.input/f'in{sr}.flac';sf.write(p,x*.4,sr,subtype='PCM_24')
            r,out=app.run_file(p,self.output,write_mp3=True)
            self.assertEqual(r['master_metrics']['samplerate'],sr);self.assertEqual(r['codec_metrics']['samplerate'],min(sr,48000))
            self.assertAlmostEqual(r['master_metrics']['lufs_i'],-12,places=3)
    def test_21_folder_dialog_and_cancel(self):
        import tkinter
        from tkinter import filedialog
        with patch.object(tkinter,'Tk',return_value=MagicMock()),patch.object(filedialog,'askopenfilenames',return_value=[str(self.source)]),patch.object(filedialog,'askdirectory',return_value='') as choose:
            sources,root=app.choose_paths([],None);choose.assert_called_once();self.assertEqual(sources,[]);self.assertIsNone(root)
    def test_22_explicit_output_skips_gui(self):
        sources,root=app.choose_paths([self.source],self.output);self.assertEqual(sources,[self.source]);self.assertEqual(root,self.output)
    def test_23_invalid_config(self):
        for cfg in (peak.PeakConfig(oversample=0),peak.PeakConfig(attack_ms=float('nan'))):
            with self.assertRaises(ValueError):cfg.validate()
    def test_24_production_unchanged_targets(self):
        s=(ROOT/'distribution_finish.py').read_text(encoding='utf-8')
        self.assertNotIn('import pdrm_runtime',s);self.assertNotIn('from pdrm_engine',s)
        self.assertEqual((app.MASTER_LUFS,app.MASTER_TP,app.LISTEN_LUFS),(-12,-2,-14))
    def test_25_ffmpeg_cancellation(self):
        progress=MagicMock();progress.set.side_effect=InterruptedError('CANCEL')
        with self.assertRaises(InterruptedError):
            peak.execute(self.ff,['-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-f','null','-'],self.root/'cancel.log',progress)
    def test_26_limiter_silence_and_no_auto_makeup(self):
        z=np.zeros((48000,2));sf.write(self.source,z,48000,subtype='FLOAT');d=self.root/'zero.wav'
        peak.render_limited(self.source,d,5,-2.2,self.ff);x,_=sf.read(d,always_2d=True);self.assertTrue(np.array_equal(x,z))
        t=np.arange(48000)/48000;y=.03*np.sin(2*np.pi*1000*t);sf.write(self.source,np.column_stack((y,y)),48000,subtype='FLOAT')
        peak.render_limited(self.source,d,0,-2.2,self.ff);x,_=sf.read(d,always_2d=True)
        self.assertLess(abs(np.sqrt(np.mean(x[1000:-1000,0]**2))/np.sqrt(np.mean(y[1000:-1000]**2))-1),.001)
    def test_27_corrupt_he_cache_rebuilt(self):
        d=self.root/'he.wav';app.render_harmonic(self.source,d);h=app.io.pcm_hash(d);d.write_bytes(b'broken');app.render_harmonic(self.source,d)
        self.assertEqual(h,app.io.pcm_hash(d))
    def test_28_pcm24_clipping_rejected(self):
        sf.write(self.source,np.ones((48000,2))*1.1,48000,subtype='FLOAT')
        with self.assertRaisesRegex(RuntimeError,'clip'):app.write_pcm24(self.source,self.root/'bad.wav')
    def test_29_selected_output_used(self):
        _,out=self.run_app(write_mp3=False);self.assertEqual(out.parent,self.output)
    def test_30_peak_cache_tied_to_target(self):
        d=self.root/'fit.wav';a=peak.fit(self.source,d,self.root/'fit',-18,-2,self.ff);b=peak.fit(self.source,d,self.root/'fit',-20,-2,self.ff)
        self.assertAlmostEqual(a['output_metrics']['lufs_i'],-18,places=3);self.assertAlmostEqual(b['output_metrics']['lufs_i'],-20,places=3)

if __name__=='__main__':unittest.main(verbosity=2)
