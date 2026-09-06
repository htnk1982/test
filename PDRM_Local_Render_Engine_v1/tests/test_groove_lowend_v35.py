from pathlib import Path
import sys,tempfile,unittest
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import groove_lowend_lab as g

SR=48000

def write(path,x):
    x=np.asarray(x,dtype=np.float64)
    if x.ndim==1:x=np.column_stack((x,x))
    sf.write(path,x,SR,subtype='FLOAT')
    return path

def observer(duration,conf=.95,mode='PRECOMPUTED_STEMS'):
    t=np.arange(0,duration+.02,.02)
    return dict(mode=mode,times=t,bass_confidence=np.full(len(t),conf),claim='test')

def event(start,end,f0,target,amp=.02,knots=7):
    tt=np.linspace(start,end,knots)
    return dict(start=start,end=end,times=tt.tolist(),frequencies=np.full(knots,target).tolist(),
        amplitudes=np.full(knots,amp).tolist(),integral_cycles=np.r_[0,np.cumsum(np.diff(tt)*target)].tolist(),
        median_f0_hz=float(f0),median_sub_hz=float(target),phase=0.0)

def transient_mix(seconds=1.6,start=.55,end=.80):
    t=np.arange(round(seconds*SR))/SR
    env=np.zeros_like(t);m=(t>=start)&(t<end);r=(t[m]-start)/(end-start)
    env[m]=np.sin(np.pi*np.clip(r,0,1))**2
    x=env*(.18*np.sin(2*np.pi*100*t)+.004*np.sin(2*np.pi*50*t))
    return np.column_stack((x,x*.98))

class Permission(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
        self.phys=write(self.root/'physical.wav',transient_mix())
    def tearDown(self):self.t.cleanup()
    def test_octave_down_is_prohibited_before_amount(self):
        a,d=g.gate_and_shape_events([event(.55,.75,110,55)],self.phys,observer(1.6))
        self.assertEqual(a,[]);self.assertEqual(d[0]['reason'],'automatic_octave_down_prohibited')
    def test_missing_observer_never_authorizes_addition(self):
        a,d=g.gate_and_shape_events([event(.55,.75,50,50)],self.phys,None)
        self.assertEqual(a,[]);self.assertEqual(d[0]['reason'],'semantic_observer_unavailable')
    def test_low_semantic_confidence_never_authorizes_addition(self):
        a,d=g.gate_and_shape_events([event(.55,.75,50,50)],self.phys,observer(1.6,.2))
        self.assertEqual(a,[]);self.assertEqual(d[0]['reason'],'semantic_bass_confidence_low')
    def test_same_fundamental_transient_can_be_accented(self):
        a,d=g.gate_and_shape_events([event(.55,.75,50,50)],self.phys,observer(1.6,.98))
        self.assertEqual(len(a),1);self.assertEqual(d[0]['action'],'SUB_ACCENT')
        self.assertGreater(max(a[0]['amplitudes']),0);self.assertLessEqual(a[0]['groove_scale'],g.Config().add_scale_cap)
    def test_sustained_event_does_not_get_automatic_sub(self):
        a,d=g.gate_and_shape_events([event(.30,1.30,50,50)],self.phys,observer(1.6,.99))
        self.assertEqual(a,[]);self.assertEqual(d[0]['reason'],'sustained_event_no_automatic_sub')

class TemporalControl(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
    def tearDown(self):self.t.cleanup()
    def test_trim_plan_is_constant_gain_invariant(self):
        p=write(self.root/'a.wav',transient_mix(2.0,.35,1.45))
        x,_=sf.read(p,always_2d=True);write(self.root/'b.wav',x*.2)
        pa=g.plan_trim(g.analyze_mix(p));pb=g.plan_trim(g.analyze_mix(self.root/'b.wav'))
        np.testing.assert_allclose(pa['depth_db'],pb['depth_db'],atol=5e-8,rtol=0)
    def test_attack_is_protected_but_tail_can_trim(self):
        cfg=g.Config();dt=cfg.grid_seconds;n=180
        times=np.arange(n)*dt;slow=np.full(n,-28.0);slow[30]=-8.0;slow[31:120]=-14.0
        fast=slow.copy();fast[30]=-5.0
        ratio=np.full(n,-2.0);ratio[30:120]=5.0
        f=dict(times=times,fast_db=fast,low_db=slow,deep_power=np.ones(n),body_power=np.ones(n),mid_power=np.ones(n),
            low_mid_ratio_db=ratio,ratio_context_db=np.full(n,3.5),p20_db=np.full(n,-28.0),p90_db=np.full(n,-8.0),onsets=[30])
        p=g.plan_trim(f,cfg);d=p['depth_db']
        pre=int(round(cfg.attack_protect_before/dt));post=int(round(cfg.attack_protect_after/dt))
        self.assertTrue(np.all(d[30-pre:30+post]==0.0));self.assertGreater(np.max(d[50:110]),.1)
    def test_render_trim_preserves_exact_digital_silence(self):
        t=np.arange(2*SR)/SR;x=np.zeros((len(t),2));m=(t>.45)&(t<1.25);x[m,0]=.1*np.sin(2*np.pi*55*t[m]);x[m,1]=x[m,0]
        src=write(self.root/'sil.wav',x);plan=dict(times=np.arange(0,2,.01),depth_db=np.full(200,2.0))
        out=self.root/'out.wav';g.render_trim(src,out,plan);y,_=sf.read(out,always_2d=True)
        self.assertTrue(np.all(y[:round(.40*SR)]==0));self.assertTrue(np.all(y[round(1.30*SR):]==0))

class Observer(unittest.TestCase):
    def setUp(self):self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name)
    def tearDown(self):self.t.cleanup()
    def test_precomputed_stem_shape_mismatch_rejected(self):
        src=write(self.root/'src.wav',np.zeros((SR,2)));bass=write(self.root/'bass.wav',np.zeros((SR,2)))
        sf.write(self.root/'drum.wav',np.zeros((SR//2,2)),SR,subtype='FLOAT')
        with self.assertRaisesRegex(ValueError,'shape mismatch'):g.analyze_precomputed_stems(src,bass,self.root/'drum.wav')
    def test_precomputed_stems_are_analysis_only_values(self):
        t=np.arange(SR)/SR;src=write(self.root/'src.wav',.02*np.sin(2*np.pi*440*t));bass=write(self.root/'bass.wav',.1*np.sin(2*np.pi*55*t));dr=write(self.root/'dr.wav',np.zeros_like(t))
        h0=g.io.file_hash(src);o=g.analyze_precomputed_stems(src,bass,dr);self.assertEqual(o['mode'],'PRECOMPUTED_STEMS');self.assertEqual(g.io.file_hash(src),h0)
        self.assertGreater(float(np.median(o['bass_confidence'])),.9)

if __name__=='__main__':unittest.main(verbosity=2)
