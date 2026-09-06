from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import offline_peak_lab as old
import offline_peak_stream as stream0
import offline_peak_stream_v31 as stream1
import offline_peak_stream_v32 as stream2
import offline_peak_context as ctx
import workspace_cleanup as clean
import processed_finish_v32 as pub32

SR=48000

def gentle(seconds=.8):
    t=np.arange(round(SR*seconds))/SR
    x=np.column_stack((.10*np.sin(2*np.pi*83*t)+.07*np.sin(2*np.pi*760*t),
                       .095*np.sin(2*np.pi*83*t)+.065*np.sin(2*np.pi*820*t)))
    x[:128]=0;x[-128:]=0
    return x

def broad(seconds=.8):
    t=np.arange(round(SR*seconds))/SR;x=gentle(seconds)
    for when in (.17,.39,.58):x+=.86*np.exp(-.5*((t-when)/.000055)**2)[:,None]
    return x

class ContextSolver(unittest.TestCase):
    def test_context_reduces_peak_and_passes_local_gates(self):
        r=np.repeat(broad(.256),4,axis=0)[:round(.256*SR*4)]
        # Use interpolation-like high-rate input; force a crest over the box.
        ceiling=.78
        y,st=ctx.solve_context(r,SR*4,ceiling,old.Config())
        self.assertTrue(st['active']);self.assertLessEqual(np.max(abs(y)),ceiling+2e-10)
        self.assertTrue(all(st['local_metrics']['gates'].values()))
    def test_large_peak_still_refused(self):
        r=np.zeros((SR,2));r[SR//2]=10
        with self.assertRaises(old.NotFeasible):ctx.solve_context(r,SR*4,.5,old.Config())
    def test_boundary_requirement_is_not_diluted(self):
        r=np.zeros((20000,2));r[1]=1.2
        with self.assertRaises(old.NotFeasible):ctx.solve_context(r,SR*4,.7,old.Config())
    def test_exact_mono_and_antiphase(self):
        t=np.arange(40000)/(SR*4);s=.25*np.sin(2*np.pi*900*t);s[20000]+=1
        for sign in (1,-1):
            r=np.column_stack((s,sign*s));y,_=ctx.solve_context(r,SR*4,.75,old.Config())
            np.testing.assert_array_equal(y[:,0],sign*y[:,1])

class WholeTrackV32(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.g=self.root/'gentle.wav';self.b=self.root/'broad.wav'
        sf.write(self.g,gentle(),SR,subtype='FLOAT');sf.write(self.b,broad(),SR,subtype='FLOAT')
    def tearDown(self):self.tmp.cleanup()
    def test_old_feasible_track_is_sample_identical(self):
        a,_=stream0.render_fixed_gain(self.g,self.root/'a',5.0,.72,chunk_seconds=.25)
        b,st=stream2.render_fixed_gain(self.g,self.root/'b',5.0,.72,chunk_seconds=.25)
        xa,_=sf.read(a,dtype='float64',always_2d=True);xb,_=sf.read(b,dtype='float64',always_2d=True)
        np.testing.assert_array_equal(xa,xb);self.assertEqual(st['context_rescue_regions'],0)
    def test_context_rescues_broader_transient_class(self):
        # v3.1 is intentionally shown with its independent local gate tightened:
        # this reproduces the exact second-stage failure class from the field log.
        import offline_peak_rescue as r31
        with self.assertRaises(old.NotFeasible):
            stream1.render_fixed_gain(self.b,self.root/'v31',2.4,10**(-2.2/20),
                rescue_cfg=r31.RescueConfig(local_residual_budget_db=-50),chunk_seconds=.25)
        out,st=stream2.render_fixed_gain(self.b,self.root/'v32',2.4,10**(-2.2/20),chunk_seconds=.25)
        self.assertTrue(out.is_file());self.assertGreater(st['old_infeasible_frames'],0);self.assertGreater(st['context_rescue_regions'],0)
    def test_restart_reuses_provisional_chunks(self):
        with self.assertRaises(InterruptedError):stream2.render_fixed_gain(self.b,self.root/'resume',2.4,10**(-2.2/20),chunk_seconds=.25,interrupt_after=1)
        out,st=stream2.render_fixed_gain(self.b,self.root/'resume',2.4,10**(-2.2/20),chunk_seconds=.25)
        self.assertTrue(out.is_file());self.assertGreaterEqual(st['reused_chunks'],1)
    def test_no_limiter_fallback(self):
        text=Path(stream2.__file__).read_text(encoding='utf-8')+Path(ctx.__file__).read_text(encoding='utf-8')
        self.assertNotIn('alimiter=',text);self.assertNotIn('distribution_peak',text)

class Cleanup(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'song.wav'
        sf.write(self.src,gentle(.5),SR,subtype='FLOAT');self.sha=clean.io.file_hash(self.src)
    def tearDown(self):self.tmp.cleanup()
    def make_job(self,version='old'):
        d=self.root/'work'/'.oppo_work_v3'/'job';d.mkdir(parents=True)
        (d/'identity.json').write_text(json.dumps(dict(source_sha256=self.sha,version=version)),encoding='utf-8')
        (d/'large.wav').write_bytes(b'0'*1024*1024);return d
    def test_success_cleanup_removes_large_job(self):
        d=self.make_job();r=clean.cleanup_source(self.root/'work',self.src,current_version='new',success=True)
        self.assertFalse(d.exists());self.assertGreaterEqual(r['bytes_freed'],1024*1024)
    def test_failure_keeps_small_diagnostic_not_audio(self):
        d=self.make_job();(d/'FAILURE.json').write_text(json.dumps(dict(error='x')),encoding='utf-8')
        r=clean.cleanup_source(self.root/'work',self.src,current_version='new',error=RuntimeError('boom'))
        self.assertFalse(d.exists());self.assertTrue(Path(r['diagnostic']).is_file());self.assertFalse(list((self.root/'work').rglob('*.wav')))
    def test_prestart_keeps_same_version_resume(self):
        d=self.make_job('natural-finish-3.2.0');clean.cleanup_source(self.root/'work',self.src,current_version='natural-finish-3.2.0',prestart=True)
        self.assertTrue(d.exists())
    def test_prestart_deletes_old_version(self):
        d=self.make_job('natural-finish-3.1.0');clean.cleanup_source(self.root/'work',self.src,current_version='natural-finish-3.2.0',prestart=True)
        self.assertFalse(d.exists())
    def test_publisher_calls_cleanup_per_item(self):
        class Backend:
            VERSION='b';IDENTITY_MODULES=();calls=[]
            @staticmethod
            def cleanup_source_workspace(source,root,**kw):Backend.calls.append((Path(source).name,kw));return {}
        with patch.object(pub32,'choose_sources',return_value=[self.src]),patch.object(pub32,'run_file',side_effect=RuntimeError('fail')):
            rc=pub32.main([],backend=Backend,default_root=self.root/'work2')
        self.assertEqual(rc,1);self.assertTrue(any(c[1].get('error') for c in Backend.calls))

if __name__=='__main__':unittest.main(verbosity=2)
