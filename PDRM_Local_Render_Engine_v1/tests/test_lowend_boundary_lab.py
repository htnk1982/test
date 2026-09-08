import unittest
import copy
import tempfile
from pathlib import Path
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lowend_boundary_lab as c

class Contracts(unittest.TestCase):
    def fixture(self,n=200):
        t=np.arange(n)*.01
        return dict(time=t,full_db=np.full(n,-22.),low_db=np.full(n,-24.),lowmid_db=np.full(n,-30.),mid_db=np.full(n,-24.),deep_db=np.full(n,-28.),present=np.ones(n,bool),low_active=np.ones(n,bool),lufs=-14.,gain_to_anchor_db=0.,configuration=c.asdict(c.Config()))
    def atlas(self):
        return c.calibrate([self.fixture() for _ in range(4)],['a','b','c','d'])
    def test_good_reference_no_action(self):
        p=c.plan(self.fixture(),self.atlas());self.assertEqual(p['status'],'NO_EVIDENCE');self.assertTrue(np.all(p['low_cut_db']==0))
    def test_new_octave_denied(self):
        self.assertEqual(self.gate(f0_hz=110,target_hz=55),'DENY_NEW_OCTAVE')
    def gate(self,**kw):
        d=dict(f0_hz=55,target_hz=55,source_event=True,source_harmonics=True,observer_role='bass',observer_reliable=True,need=True,source_rest=False);d.update(kw)
        return c.authorize_fundamental(**d)
    def test_rest_denied(self):self.assertEqual(self.gate(source_rest=True),'DENY_SOURCE_REST')
    def test_same_note_allowed_not_rendered(self):self.assertEqual(self.gate(),'ALLOW_SAME_FUNDAMENTAL_CANDIDATE')
    def test_observer_absent_abstains(self):self.assertEqual(self.gate(observer_reliable=False),'ABSTAIN_OBSERVER')
    def test_piano_not_bass(self):self.assertEqual(self.gate(observer_role='piano'),'ABSTAIN_OBSERVER')
    def test_insufficient_source_denied(self):self.assertEqual(self.gate(source_harmonics=False),'DENY_NO_SOURCE_EVIDENCE')
    def test_already_sufficient_keep(self):self.assertEqual(self.gate(need=False),'KEEP_ALREADY_SUFFICIENT')
    def test_bad_pitch_raises(self):
        with self.assertRaises(ValueError):self.gate(f0_hz=np.nan)
    def test_duplicate_reference_rejected(self):
        with self.assertRaises(ValueError):c.calibrate([self.fixture()]*4,['a']*4)
    def test_too_few_refs_rejected(self):
        with self.assertRaises(ValueError):c.calibrate([self.fixture()],['a'])
    def test_config_identity(self):
        a=self.atlas();a['config']['max_hit_cut_db']=20
        with self.assertRaises(ValueError):c.plan(self.fixture(),a)
    def test_peak_excess_not_protected(self):
        f=self.fixture();f['low_db'][40:80]=-18
        p=c.plan(f,self.atlas());self.assertIn('EXCESS_HIT_LEVEL',p['reason_codes']);self.assertGreater(p['low_cut_db'][60],0)
    def test_sustain_not_bad_by_duration_alone(self):
        f=self.fixture(2000);p=c.plan(f,self.atlas());self.assertFalse(p['reason_codes'])
    def test_overfull_floor_target_separate(self):
        f=self.fixture();f['lowmid_db'][:]=-25
        p=c.plan(f,self.atlas());self.assertEqual(p['reason_codes'],[]);self.assertIn('LOWMID_FLOOR_REQUIRES_ROLE_ATTRIBUTION',p['deferred_reason_codes'])
    def test_shape_and_nonfinite(self):
        with self.assertRaises(ValueError):c.validate_audio(np.full((48000,2),np.nan),48000)
        with self.assertRaises(ValueError):c.validate_audio(np.zeros((48000,1)),48000)
    def test_silent_abstention(self):
        with self.assertRaises(ValueError):c.extract(np.zeros((48000,2)),48000)
    def test_bypass_exact(self):
        x=np.random.default_rng(3).normal(0,.1,(96000,2));p=c.plan(self.fixture(),self.atlas());np.testing.assert_array_equal(x,c.render_array(x,48000,p))
    def test_zero_strength_exact(self):
        x=np.random.default_rng(3).normal(0,.1,(96000,2));f=self.fixture();f['low_db']+=6;p=c.plan(f,self.atlas());np.testing.assert_array_equal(x,c.render_array(x,48000,p,strength=0))
    def test_bounded_controls(self):
        f=self.fixture();f['low_db']+=30;f['lowmid_db']+=30;p=c.plan(f,self.atlas());self.assertLessEqual(p['low_cut_db'].max(),2.+1e-12);self.assertLessEqual(p['lowmid_cut_db'].max(),1.5+1e-12)
    def test_stereo_mono_and_silence(self):
        sr=48000;t=np.arange(sr*2)/sr;s=.2*np.sin(2*np.pi*60*t);s[:1000]=0;x=np.column_stack((s,s));f=self.fixture();f['low_db']+=5;p=c.plan(f,self.atlas());y=c.render_array(x,sr,p);np.testing.assert_array_equal(y[:,0],y[:,1]);np.testing.assert_array_equal(y[:1000],0)
    def test_antiphase_has_energy(self):
        sr=48000;t=np.arange(sr*2)/sr;s=.2*np.sin(2*np.pi*60*t);x=np.column_stack((s,-s));f=c.extract(x,sr);self.assertGreater(np.median(f['low_db']),-30)
    def test_no_source_mutation(self):
        x=np.random.default_rng(4).normal(0,.05,(96000,2));old=x.copy();f=self.fixture();f['low_db']+=5;c.render_array(x,48000,c.plan(f,self.atlas()));np.testing.assert_array_equal(old,x)
    def test_out_of_budget_plan_rejected(self):
        x=np.zeros((96000,2));p=c.plan(self.fixture(),self.atlas());p['low_cut_db']+=10
        with self.assertRaises(ValueError):c.render_array(x,48000,p)
    def test_input_gain_invariance(self):
        sr=48000;t=np.arange(sr*2)/sr;x=np.column_stack([.1*np.sin(2*np.pi*60*t)+.02*np.sin(2*np.pi*700*t)]*2)
        a=c.signature(c.extract(x,sr));b=c.signature(c.extract(x*.5,sr))
        for k in a:self.assertAlmostEqual(a[k],b[k],places=7)
    def test_highband_not_rebuilt(self):
        sr=48000;t=np.arange(sr*2)/sr;s=.15*np.sin(2*np.pi*60*t)+.04*np.sin(2*np.pi*3000*t);x=np.column_stack((s,s));f=self.fixture();f['low_db']+=5;p=c.plan(f,self.atlas());y=c.render_array(x,sr,p);q=c.evaluate_change(x,y,sr);self.assertLess(q['residual_above1k_db'],-60)
    def test_gate_not_inferred_from_frame_energy(self):
        self.assertEqual(self.gate(observer_role='unknown',observer_reliable=True),'ABSTAIN_OBSERVER')
    def test_invalid_config(self):
        with self.assertRaises(ValueError):c.Config(max_hit_cut_db=30).validate()
        with self.assertRaises(ValueError):c.Config(join_seconds=float('nan')).validate()

if __name__=='__main__':unittest.main(verbosity=2)
