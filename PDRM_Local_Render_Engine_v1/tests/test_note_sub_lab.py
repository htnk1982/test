from __future__ import annotations
from pathlib import Path
import math
import subprocess
import sys
import tempfile
import unittest
import numpy as np
import soundfile as sf
import pyloudnorm as pyln

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import note_sub_lab as lab


def notes(sr=48000, frequencies=(82.406889,92.498606,97.998859), missing=False, pure=False):
    length=1.2*len(frequencies)+0.5
    t=np.arange(int(round(length*sr)))/sr
    x=np.zeros(len(t))
    for i,f in enumerate(frequencies):
        start=.25+1.2*i; stop=start+.9
        local=t-start; use=(t>=start)&(t<stop)
        env=lab.smoother(local/.04)*lab.smoother((stop-t)/.04)*use
        terms=((1,.075),(2,.05),(3,.035),(4,.018))
        if missing: terms=((2,.075),(3,.05),(4,.035))
        if pure: terms=((1,.10),)
        for h,a in terms: x+=env*a*np.cos(2*np.pi*f*h*local+.13*h)
    stereo=np.stack((x,x),axis=1)
    stereo*=10**((-14-pyln.Meter(sr).integrated_loudness(stereo))/20)
    return stereo.astype('float32'),sr


def simple_event(f=41.2034445):
    tt=np.arange(.25,1.51,.02)
    return dict(start=float(tt[0]),end=float(tt[-1]),times=tt.tolist(),
                frequencies=np.full(len(tt),f).tolist(),amplitudes=np.full(len(tt),.03).tolist(),
                integral_cycles=np.r_[0,np.cumsum(np.diff(tt)*f)].tolist(),phase=.23)


class NoteSubDSP(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.inputs=self.root/'inputs';self.inputs.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def input_file(self,name,x,sr):
        p=self.inputs/name;sf.write(p,x,sr,subtype='FLOAT');return p
    def frame_rows(self,x,sr):
        p=self.input_file('input.wav',x,sr)
        j=self.root/'job';(j/'analysis').mkdir(parents=True,exist_ok=True)
        rows,cache=lab.collect_frames(p,j,lab.Progress())
        return rows,p,cache
    def test_01_nsdf_continuous_frequency(self):
        sr=4000;t=np.arange(768)/sr
        for hz in (32.7,41.2,55.3,82.406889,97.998859,123.47,164.81):
            x=.7*np.cos(2*np.pi*hz*t)+.3*np.cos(4*np.pi*hz*t)
            f,p=lab.nsdf_pitch(x,sr)
            self.assertIsNotNone(f,(hz,p));self.assertLess(lab.cents(f,hz),5);self.assertGreater(p,.95)
    def test_02_no_tonic_or_semitone_quantization(self):
        hz=82.406889*2**(17/1200);sr=4000;t=np.arange(768)/sr
        f,p=lab.nsdf_pitch(np.cos(2*np.pi*hz*t)+.5*np.cos(4*np.pi*hz*t))
        self.assertLess(lab.cents(f,hz),4);self.assertGreater(lab.cents(f,82.406889),10)
    def test_03_only_one_octave_and_floor(self):
        self.assertAlmostEqual(lab.sub_frequency(82.4),41.2)
        self.assertAlmostEqual(lab.sub_frequency(41.2),41.2)
        self.assertIsNone(lab.sub_frequency(20.6));self.assertIsNone(lab.sub_frequency(150))
    def test_04_silence_abstains(self):
        z=np.zeros(768);r=lab.analyze_frame(z,z,np.zeros((768,2)),np.zeros((768,2)),.5)
        self.assertEqual(r['amplitude'],0);self.assertEqual(r['state'],'ABSTAIN')
    def test_05_noise_abstains(self):
        x=np.random.default_rng(23).normal(0,.02,(48000*2,2))
        rows,p,_=self.frame_rows(x,48000)
        self.assertEqual(sum(r['amplitude']>0 for r in rows),0)
    def test_06_sine_drum_ambiguity_abstains(self):
        x,sr=notes(frequencies=(82.4,),pure=True);rows,p,_=self.frame_rows(x,sr)
        ev,rej=lab.make_events(rows,p);self.assertEqual(len(ev),0)
    def test_07_harmonic_bass_detected(self):
        x,sr=notes();rows,p,_=self.frame_rows(x,sr);ev,rej=lab.make_events(rows,p)
        self.assertGreaterEqual(len(ev),3,(ev,rej))
        for i,f in enumerate((82.406889,92.498606,97.998859)):
            valid=[r for r in rows if .5+1.2*i<r['time']<.95+1.2*i and r.get('amplitude',0)>0]
            self.assertTrue(valid,(i,rows))
            self.assertLess(abs(np.median([1200*math.log2(r['f0_hz']/f) for r in valid])),12)
    def test_08_missing_fundamental_supported(self):
        x,sr=notes(frequencies=(41.2034445,),missing=True)
        rows,p,_=self.frame_rows(x,sr);ev,rej=lab.make_events(rows,p)
        self.assertTrue(ev,[(r['reason'],r.get('f0_hz')) for r in rows])
        self.assertLess(lab.cents(ev[0]['median_sub_hz'],41.2034445),12)
    def test_09_already_low_bass_not_lowered_again(self):
        x,sr=notes(frequencies=(41.2034445,));rows,p,_=self.frame_rows(x,sr)
        ev,rej=lab.make_events(rows,p);self.assertFalse(ev)
        self.assertTrue(any(r['state']=='KEEP' for r in rows))
    def test_10_chirp_kick_not_added(self):
        sr=48000;t=np.arange(sr*2)/sr;x=np.zeros(len(t))
        for start in (.3,1.0):
            local=t-start;m=(local>=0)&(local<.18)
            x+=m*.18*np.exp(-np.maximum(local,0)/.035)*np.cos(2*np.pi*(100*local-140*local*local))
        rows,p,_=self.frame_rows(np.stack([x,x],axis=1),sr)
        ev,rej=lab.make_events(rows,p);self.assertFalse(ev)
    def test_11_antiphase_not_reinterpreted(self):
        x,sr=notes(frequencies=(82.4,));x[:,1]*=-1
        rows,p,_=self.frame_rows(x,sr);ev,rej=lab.make_events(rows,p);self.assertFalse(ev)
    def test_12_event_wave_frequency_correct(self):
        sr=48000;e=simple_event();y=lab.layer_chunk([e],0,sr*2,sr)
        t=np.arange(len(y))/sr;sel=(t>.4)&(t<1.3)
        a,_=lab.component(y[sel],41.2034445,sr);b,_=lab.component(y[sel],82.406889,sr)
        self.assertGreater(a,.029);self.assertLess(b,.001)
    def test_13_no_samples_outside_authorized_event(self):
        sr=48000;e=simple_event();y=lab.layer_chunk([e],0,sr*2,sr);t=np.arange(len(y))/sr
        outside=(t<e['start'])|(t>=e['end'])
        self.assertTrue(np.array_equal(y[outside],np.zeros(np.count_nonzero(outside))))
    def test_14_chunk_phase_is_invariant(self):
        sr=48000;e=simple_event();full=lab.layer_chunk([e],0,sr*2,sr)
        edges=[0,17993,24000,67001,sr*2]
        other=np.concatenate([lab.layer_chunk([e],a,b-a,sr) for a,b in zip(edges[:-1],edges[1:])])
        self.assertTrue(np.array_equal(full,other))
    def test_15_gain_zero_layer_is_zero(self):
        self.assertTrue(np.array_equal(lab.layer_chunk([simple_event()],0,100000,48000,0),np.zeros(100000)))
    def test_16_spectral_leakage_budget(self):
        sr=48000;y=lab.layer_chunk([simple_event()],0,sr*2,sr)
        p=self.root/'layer.wav';sf.write(p,y,sr,subtype='FLOAT');m=lab.measure(p)
        self.assertLess(m['above_110_energy_db'],-35,m);self.assertLess(m['below_20_energy_db'],-20,m)
    def test_17_streaming_lufs_matches_library(self):
        for sr in (44100,48000):
            x,_=notes(sr=sr);p=self.input_file(f'm_{sr}.wav',x,sr)
            m=lab.measure(p);expected=pyln.Meter(sr).integrated_loudness(x.astype('float64'))
            self.assertLess(abs(m['lufs_i']-expected),.01,(m,expected))
    def test_18_input_not_modified_by_analysis(self):
        x,sr=notes();rows,p,_=self.frame_rows(x,sr);h=lab.file_hash(p)
        ev,rej=lab.make_events(rows,p);self.assertEqual(h,lab.file_hash(p))
    def test_19_analysis_resume_skips_committed_chunks(self):
        x,sr=notes();p=self.input_file('resume.wav',x,sr)
        j=self.root/'resume_job';(j/'analysis').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError,'TEST_INTERRUPTION'):
            lab.collect_frames(p,j,lab.Progress(),interrupt_after=1)
        rows,c=lab.collect_frames(p,j,lab.Progress())
        self.assertEqual(c['reused_chunks'],1);self.assertEqual(c['computed_chunks'],0)
    def test_20_corrupt_analysis_cache_is_recomputed(self):
        x,sr=notes();rows,p,_=self.frame_rows(x,sr)
        cache=self.root/'job/analysis/frames_00000.json';cache.write_text('{broken',encoding='utf-8')
        rows2,c=lab.collect_frames(p,self.root/'job',lab.Progress())
        self.assertEqual(c['computed_chunks'],1);self.assertEqual(rows,rows2)
    def test_21_render_resume_identical_pcm(self):
        x,sr=notes();p=self.input_file('render.wav',x,sr)
        j=self.root/'rjob';j.mkdir();e=simple_event()
        with self.assertRaisesRegex(RuntimeError,'TEST_INTERRUPTION'):
            lab.render(p,j,[e],lab.Progress(),1,label='x',interrupt_after=1)
        resumed,c=lab.render(p,j,[e],lab.Progress(),1,label='x')
        clean,_=lab.render(p,j,[e],lab.Progress(),1,label='clean')
        self.assertGreater(c['reused_chunks'],0);self.assertEqual(lab.file_hash(resumed),lab.file_hash(clean))
    def test_22_invalid_nonfinite_rejected(self):
        x=np.zeros(2000);x[30]=np.nan
        with self.assertRaises(ValueError):lab.finite(x)
    def test_23_short_stable_run_not_generated(self):
        p=self.input_file('quiet.wav',np.zeros((48000,2)),48000)
        rows=[dict(time=.5+i*.02,amplitude=.01,f0_hz=82.4,sub_hz=41.2) for i in range(3)]
        ev,rej=lab.make_events(rows,p);self.assertFalse(ev);self.assertTrue(rej)
    def test_24_wrong_c_hash_rejected(self):
        job=self.root/'r9';(job/'LAB_INTERNAL').mkdir(parents=True);(job/'RENDERS').mkdir()
        lab.atomic_json(job/'manifest.json',{'experiment_id':'PDRM-v0.6-Round9-HarmonicLoudness-exp1'})
        lab.atomic_json(job/'LAB_INTERNAL/blind_mapping.json',{'C':'HarmonicElasticity'})
        sf.write(job/'RENDERS/HarmonicElasticity.wav',np.zeros((48000,2)),48000)
        with self.assertRaises(ValueError):lab.validate_manifest(job/'manifest.json')
    def test_25_full_render_and_idempotence(self):
        x,sr=notes(frequencies=(82.406889,92.498606));p=self.input_file('full.wav',x,sr);h=lab.file_hash(p)
        r,out=lab.run_job(p,self.root/'work',write_mp3=False)
        self.assertEqual(r['status'],'RENDERED_EXPERIMENT_NOT_QUALITY_APPROVAL',r)
        self.assertGreater(r['selected_seconds'],.30)
        self.assertLess(abs(r['output_metrics']['lufs_i']+14),.05)
        self.assertEqual(lab.file_hash(p),h);self.assertEqual(lab.file_hash(out/'CONTROL_C.wav'),h)
        d,_=sf.read(out/'DELTA_SUB_FLOAT.wav');z,_=sf.read(out/'SUB_AUGMENTED.wav');c,_=sf.read(p)
        g=10**(r['matched_output_gain_db']/20)
        self.assertLess(np.max(np.abs(z-g*(c+d[:,None]))),2e-7)
        r2,out2=lab.run_job(p,self.root/'work',write_mp3=False)
        self.assertEqual(r2['rerun_status'],'IDEMPOTENT_SKIP');self.assertEqual(out,out2)
    def test_26_foreign_result_not_overwritten(self):
        x,sr=notes(frequencies=(82.4,));p=self.input_file('f.wav',x,sr)
        r,out=lab.run_job(p,self.root/'w',write_mp3=False)
        q=out/'SUB_AUGMENTED.wav';q.write_bytes(b'foreign data')
        with self.assertRaises(RuntimeError):lab.run_job(p,self.root/'w',write_mp3=False)
        self.assertEqual(q.read_bytes(),b'foreign data')
    def test_27_pcm_resume_after_actual_process_kill(self):
        x,sr=notes(frequencies=(82.4,));p=self.input_file('kill.wav',x,sr)
        script=self.root/'child.py';work=self.root/'kwork';marker=self.root/'entered'
        script.write_text('import sys,time\nfrom pathlib import Path\nsys.path.insert(0,'+repr(str(ROOT))+')\nimport note_sub_lab as l\norig=l.collect_frames\ndef hook(*a,**kw):\n r=orig(*a,**kw)\n Path('+repr(str(marker))+').write_text("ready")\n time.sleep(120)\n return r\nl.collect_frames=hook\nl.run_job('+repr(str(p))+','+repr(str(work))+',write_mp3=False)\n',encoding='utf-8')
        import time
        proc=subprocess.Popen([sys.executable,str(script)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        try:
            end=time.monotonic()+60
            while not marker.exists() and proc.poll() is None and time.monotonic()<end:time.sleep(.05)
            self.assertTrue(marker.exists(),proc.communicate(timeout=1)[1] if proc.poll() is not None else 'timeout')
            proc.kill();proc.wait(timeout=10)
        finally:
            if proc.poll() is None:proc.kill();proc.wait(timeout=10)
            if proc.stderr:proc.stderr.close()
        self.assertFalse(any(work.glob('*/RESULT')))
        resumed,o1=lab.run_job(p,work,write_mp3=False)
        clean,o2=lab.run_job(p,self.root/'cleanwork',write_mp3=False)
        self.assertEqual(lab.file_hash(o1/'SUB_AUGMENTED.wav'),lab.file_hash(o2/'SUB_AUGMENTED.wav'))
        self.assertGreater(resumed['analysis_cache']['reused_chunks'],0)
    def test_28_existing_sub_noop_is_bit_exact(self):
        x,sr=notes(frequencies=(41.2034445,));p=self.input_file('low.wav',x,sr)
        r,out=lab.run_job(p,self.root/'nop',write_mp3=False)
        self.assertEqual(r['status'],'NO_ELIGIBLE_ADDITION')
        self.assertEqual(lab.file_hash(p),lab.file_hash(out/'SUB_AUGMENTED.wav'))
    def test_29_mp3_roundtrip_pair(self):
        if not lab.ffmpeg_path():self.skipTest('ffmpeg unavailable')
        x,sr=notes(frequencies=(82.4,));p=self.input_file('codec.wav',x,sr)
        r,out=lab.run_job(p,self.root/'codecwork',write_mp3=True)
        self.assertEqual(len(r['codec']),2)
        self.assertEqual(len(list((out/'BLIND_TEST').glob('*.mp3'))),2)
    def test_30_production_round9_lock_unchanged(self):
        source=(ROOT/'note_sub_lab.py').read_text(encoding='utf-8')
        self.assertNotIn('from pdrm_engine',source);self.assertNotIn('import pdrm_runtime',source)
    def test_31_two_unrelated_bass_pitches_abstain(self):
        sr=48000;t=np.arange(2*sr)/sr
        a=.08*np.cos(2*np.pi*82.406889*t)+.05*np.cos(4*np.pi*82.406889*t)
        b=.08*np.cos(2*np.pi*110*t)+.05*np.cos(4*np.pi*110*t)
        rows,p,_=self.frame_rows(np.stack([a+b,a+b],axis=1),sr)
        ev,rej=lab.make_events(rows,p);self.assertFalse(ev)
    def test_32_source_directory_protection_retained(self):
        x,sr=notes(frequencies=(82.4,));p=self.input_file('protected.wav',x,sr)
        with self.assertRaisesRegex(ValueError,'outside'):
            lab.run_job(p,self.inputs/'output',write_mp3=False)
        self.assertFalse((self.inputs/'output').exists())


if __name__=='__main__':unittest.main(verbosity=2)
