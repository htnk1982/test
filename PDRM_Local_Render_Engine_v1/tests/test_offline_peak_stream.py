from pathlib import Path
from unittest.mock import patch
import json, tempfile, unittest
import numpy as np
import soundfile as sf
import offline_peak_lab as k
import offline_peak_stream as s
import note_sub_conditioned as conditioned
import natural_finish as natural
import processed_finish as pub
from target_settings import Targets
from test_offline_peak_lab import mixture

class StreamingRegression(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name)
        self.x=mixture();self.src=self.r/'in.wav';sf.write(self.src,self.x,48000,subtype='DOUBLE')
    def tearDown(self):self.tmp.cleanup()
    def test_frozen_kernel(self):self.assertEqual(s.verify_kernel(),s.KERNEL_SHA256)
    def test_stream_meter_matches_reference(self):
        for n in (24201,52800):
            x=self.x[:n];sf.write(self.src,x,48000,subtype='DOUBLE')
            self.assertAlmostEqual(s.measure(self.src)['lufs_i'],k.loudness(x,48000),places=8)
    def test_array_renderer_equivalence(self):
        drive=-12-k.loudness(self.x,48000);ceiling=10**(-2.12/20)
        expected,_=k.render_fixed_gain(self.x*10**(drive/20),48000,ceiling,k.Config())
        out,_=s.render_fixed_gain(self.src,self.r/'w',drive,ceiling,chunk_seconds=.11)
        actual,_=sf.read(out,always_2d=True);np.testing.assert_array_equal(expected,actual)
    def test_chunk_width_independence(self):
        a,_=s.render_fixed_gain(self.src,self.r/'a',6.6,.78,chunk_seconds=.11)
        b,_=s.render_fixed_gain(self.src,self.r/'b',6.6,.78,chunk_seconds=.39)
        np.testing.assert_array_equal(sf.read(a)[0],sf.read(b)[0])
    def test_44100_window_grid(self):
        x=mixture(sr=44100);sf.write(self.src,x,44100,subtype='DOUBLE')
        expected,_=k.render_fixed_gain(x*2,44100,.55,k.Config())
        p,_=s.render_fixed_gain(self.src,self.r/'r',20*np.log10(2),.55,chunk_seconds=.19)
        np.testing.assert_allclose(sf.read(p)[0],expected,atol=1e-13,rtol=0)
    def test_quality_parity(self):
        drive=6.6;p,_=s.render_fixed_gain(self.src,self.r/'r',drive,.75,chunk_seconds=.17)
        y,_=sf.read(p);a=k.quality_report(self.x*10**(drive/20),y,48000,k.Config());b=s.quality_report(self.src,p,drive)
        for key in ('residual_relative_db','envelope_20ms_abs_p95_db','ms_ratio_change_db'):
            self.assertAlmostEqual(a[key],b[key],places=8)
        self.assertEqual(a['gates'],b['gates'])
    def test_interrupted_chunks_resume(self):
        with self.assertRaises(InterruptedError):s.render_fixed_gain(self.src,self.r/'r',6.6,.75,chunk_seconds=.1,interrupt_after=2)
        a,stat=s.render_fixed_gain(self.src,self.r/'r',6.6,.75,chunk_seconds=.1)
        b,_=s.render_fixed_gain(self.src,self.r/'clean',6.6,.75,chunk_seconds=.1)
        self.assertGreaterEqual(stat['reused_chunks'],2);self.assertEqual(pub.io.pcm_hash(a),pub.io.pcm_hash(b))
    def test_corrupt_chunk_recomputed(self):
        out,_=s.render_fixed_gain(self.src,self.r/'r',6.6,.75,chunk_seconds=.1);before=pub.io.pcm_hash(out)
        p=next(out.parent.glob('000000.wav'));p.write_bytes(b'broken')
        out,stat=s.render_fixed_gain(self.src,self.r/'r',6.6,.75,chunk_seconds=.1)
        self.assertEqual(stat['computed_chunks'],1);self.assertEqual(before,pub.io.pcm_hash(out))
    def test_whole_fit_and_idempotence(self):
        p=self.r/'f.wav';a=s.fit(self.src,p,self.r/'work',-12,-2);h=pub.io.file_hash(p)
        b=s.fit(self.src,p,self.r/'work',-12,-2)
        self.assertEqual(b['rerun_status'],'IDEMPOTENT_SKIP');self.assertEqual(h,pub.io.file_hash(p))
        self.assertLessEqual(a['output_tp'],-2);self.assertLessEqual(abs(a['output_lufs']+12),.03)
    def test_modified_final_refused(self):
        p=self.r/'f.wav';s.fit(self.src,p,self.r/'w',-24,-2);p.write_bytes(b'modified')
        with self.assertRaises(RuntimeError):s.fit(self.src,p,self.r/'w',-24,-2)
        self.assertEqual(p.read_bytes(),b'modified')
    def test_no_fallback_on_failure(self):
        with patch.object(k,'solve_block',side_effect=k.NotFeasible('forced')):
            with self.assertRaises(k.NotFeasible):s.fit(self.src,self.r/'bad.wav',self.r/'w',-12,-2)
        self.assertFalse((self.r/'bad.wav').exists())
    def test_no_source_overwrite(self):
        with self.assertRaises(ValueError):s.fit(self.src,self.src,self.r/'w',-12,-2)
    def test_duration_and_bad_parameters(self):
        with self.assertRaises(ValueError):s.render_fixed_gain(self.src,self.r/'w',0,.5,chunk_seconds=0)
        with self.assertRaises(ValueError):s.fit(self.src,self.r/'f',self.r/'w',-12,float('nan'))
    def test_no_whole_audio_read(self):
        # SoundFile streaming API is used; sf.read() would allocate the full file.
        with patch.object(s.sf,'read',side_effect=AssertionError('whole file read')):
            s.fit(self.src,self.r/'p.wav',self.r/'w',-12,-2)
    def test_exact_silence(self):
        p=self.r/'out.wav';s.fit(self.src,p,self.r/'w',-12,-2)
        y,_=sf.read(p);np.testing.assert_array_equal(y[self.x==0],0)
    def test_gain_only_bypass(self):
        with patch.object(k,'solve_block',side_effect=AssertionError('unneeded optimizer')):
            r=s.fit(self.src,self.r/'o.wav',self.r/'w',-24,-2)
        self.assertEqual(r['status'],'GAIN_ONLY')

class ConditionedAndIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name)
        self.src=self.r/'original'/'曲.wav';self.src.parent.mkdir()
        sf.write(self.src,mixture(),48000,subtype='DOUBLE')
    def tearDown(self):self.tmp.cleanup()
    def test_conditioning_is_gain_only(self):
        with patch.object(natural.common.peak,'fit',side_effect=AssertionError('limiter')):
            output,report=conditioned.run(self.src,self.r/'work')
        self.assertFalse(report['prep_limiter_used']);self.assertLessEqual(report['prepared_metrics']['true_peak_max_dbtp_estimate'],-2.5+1e-8)
        safe=output.parent/'SAFE_GAIN.wav';a,_=sf.read(self.src);b,_=sf.read(safe)
        np.testing.assert_allclose(b,a*10**(report['preparation_gain_db']/20),atol=0,rtol=0)
    def test_analysis_reference_and_amplitude_mapping(self):
        output,report=conditioned.run(self.src,self.r/'work');j=pub.io.read_json(output.parent/'EVENTS.json')
        self.assertAlmostEqual(s.measure(output.parent/'ANALYSIS_REFERENCE.wav')['lufs_i'],-14,places=7)
        for a,b in zip(j['analysis_events'],j['render_events']):
            np.testing.assert_allclose(np.array(a['amplitudes'])*j['analysis_to_render_gain'],b['amplitudes'],atol=0,rtol=0)
            self.assertEqual(a['phase'],b['phase']);self.assertEqual(a['times'],b['times'])
    def test_conditioned_resume(self):
        with self.assertRaises(InterruptedError):conditioned.run(self.src,self.r/'w',interrupt_after='analysis')
        a,report=conditioned.run(self.src,self.r/'w');self.assertGreater(report['analysis_cache']['reused_chunks'],0)
    def test_natural_chain_no_conventional_limiter(self):
        with patch.object(natural.common.peak,'fit',side_effect=AssertionError('conventional limiter called')):
            r,p=natural.run_file(self.src,self.r/'w',targets=Targets(-18,-2,-20,-2))
        self.assertTrue(r['harmonic_elasticity_applied']);self.assertFalse(r['conventional_limiter_used'])
        self.assertLessEqual(abs(r['master_metrics']['lufs_i']+18),.03)
        self.assertLessEqual(abs(r['codec_metrics']['lufs_i']+20),.03)
        self.assertLessEqual(r['codec_metrics']['true_peak_max_dbtp_estimate'],-2)
        self.assertEqual(pub.io.file_hash(self.src),r['identity']['source_sha256'])
    def test_master_checkpoint_and_resume(self):
        with self.assertRaises(InterruptedError):natural.run_file(self.src,self.r/'w',targets=Targets(-18,-2,-20,-2),interrupt_after='master')
        self.assertFalse(list((self.r/'w').glob('*__OPPO_*')))
        r,p=natural.run_file(self.src,self.r/'w',targets=Targets(-18,-2,-20,-2))
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(r['master_peak']['rerun_status'],'IDEMPOTENT_SKIP')
    def test_targets_cache_separate(self):
        a,pa=natural.run_file(self.src,self.r/'w',targets=Targets(-20,-2,-22,-2),write_mp3=False)
        b,pb=natural.run_file(self.src,self.r/'w',targets=Targets(-21,-3,-23,-3),write_mp3=False)
        self.assertNotEqual(pa,pb)
    def test_publisher_backend_and_same_names(self):
        r,p=pub.run_file(self.src,self.r/'w',targets=Targets(-20,-2,-22,-2),backend=natural)
        self.assertEqual(set(r['files']),{'曲.wav','曲.mp3'});self.assertEqual(p.name,'processed')
        self.assertEqual(r['request']['engine_version'],natural.VERSION)
        self.assertIn('offline_peak_stream.py',r['request']['code'])
        q,_=pub.run_file(self.src,self.r/'w',targets=Targets(-20,-2,-22,-2),backend=natural)
        self.assertEqual(q['rerun_status'],'IDEMPOTENT_SKIP')
    def test_publisher_failure_no_pair(self):
        with patch.object(natural,'run_file',side_effect=k.NotFeasible('forced')):
            with self.assertRaises(k.NotFeasible):pub.run_file(self.src,self.r/'w',backend=natural)
        self.assertFalse((self.src.parent/'processed'/'曲.wav').exists())
    def test_invalid_prevents_any_work(self):
        with self.assertRaises(ValueError):natural.run_file(self.src,self.r/'w',targets=Targets(wav_tp=0))
        self.assertFalse((self.r/'w').exists())

if __name__=='__main__':unittest.main(verbosity=2)
