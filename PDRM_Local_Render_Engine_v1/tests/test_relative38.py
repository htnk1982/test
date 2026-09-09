from pathlib import Path
import sys,copy,tempfile,unittest,math
import numpy as np,soundfile as sf
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code' if (ROOT/'code').is_dir() else ROOT))
import relative_spectral_v38 as c
from stem_observer_lab import CHECKPOINT_SHA256,sha

def features(n=300):
 return dict(time=np.arange(n)*.02,fc=c.legacy.centers(),full_db=np.full(n,-20.),db=np.full((n,20),-45.))
def obs(digest='source',role='other'):
 n=300;t=np.arange(n)*.02;p=np.ones((2,n,5,20))*.00001;p[:,:,0,:]=.03;p[:,:,["mix","drums","bass","other","vocals"].index(role),:]=.02
 a=dict(band_time=t,fc=c.legacy.centers(),band_power=p)
 m=dict(version='role-observer-0.3.0',source_sha256=digest,source_order=c.ROLE_ORDER.copy(),start_seconds=0.,end_seconds=6.,model_sha256=CHECKPOINT_SHA256)
 return a,m
class Boundary38(unittest.TestCase):
 def setUp(self):
  self.f=features();self.a=c.calibrate([features() for _ in range(4)],['a','b','c','d']);self.o=obs()
 def plan(self,f=None,o=None):return c.plan(self.f if f is None else f,self.a,'source',self.o if o is None else o)
 def excess(self):
  f=features();f['db'][:,13]+=6;return f
 def test_keep_with_evidence_not_missing_observer(self):
  p=self.plan();self.assertTrue(p['observer_used']);self.assertEqual(p['status'],'KEEP_NO_RELATIVE_EXCESS');self.assertFalse(p['depth_db'].any())
 def test_sustained_excess_acts(self):self.assertGreater(self.plan(self.excess())['depth_db'].max(),0)
 def test_missing_observer_not_counted_healthy(self):
  p=c.plan(self.excess(),self.a,'source');self.assertEqual(p['status'],'ABSTAIN_OBSERVER_OR_VOCAL');self.assertFalse(p['healthy_audio_claim'])
 def test_neutral_is_not_universal_bypass(self):
  self.assertFalse(self.plan()['depth_db'].any());self.assertTrue(self.plan(self.excess())['depth_db'].any())
 def test_whole_gain_cancels(self):
  f=self.excess();g=copy.deepcopy(f);g['db']+=2;g['full_db']+=2
  np.testing.assert_allclose(c.signature(f),c.signature(g),atol=1e-12)
 def test_neighbour_reference_transfer(self):
  fs=[features() for _ in range(4)];fs[0]['db'][:,9]=-35
  at=c.calibrate(fs,['a','b','c','d']);f=features();f['db'][:,11]=-35
  self.assertFalse(c.screen(f,at)['eligible'][11]);self.assertGreater(at['caps_db'][11],at['caps_db'][12])
 def test_no_global_unbounded_reference_pool(self):
  fs=[features() for _ in range(4)];fs[0]['db'][:,9]=-35
  at=c.calibrate(fs,['a','b','c','d']);f=features();f['db'][:,15]=-35
  self.assertTrue(c.screen(f,at)['eligible'][15])
 def test_same_frequency_old_signature_not_reused(self):
  self.assertFalse('absolute' in self.a['scope']);self.assertTrue(np.allclose(self.a['reference_signatures_db'][0],-25.))
 def test_duplicate_groups_rejected(self):
  with self.assertRaises(ValueError):c.calibrate([features()]*4,['a']*4)
 def test_calibration_config_tamper(self):
  self.a['caps_db'][2]+=2
  with self.assertRaises(ValueError):self.plan()
 def test_nan_feature_fails(self):
  self.f['db'][0,0]=np.nan
  with self.assertRaises(ValueError):self.plan()
 def test_nothing_audible_is_not_healthy_keep(self):
  self.f['full_db'][:]=-100
  with self.assertRaises(ValueError):self.plan()
 def test_millisecond_feature_clock_rejected(self):
  self.f['time']*=1000
  with self.assertRaises(ValueError):self.plan()
 def test_millisecond_observer_clock_rejected(self):
  self.o[0]['band_time']*=1000
  with self.assertRaises(ValueError):self.plan()
 def test_metadata_time_mismatch(self):
  self.o[1]['end_seconds']=6000
  with self.assertRaises(ValueError):self.plan()
 def test_source_mismatch_even_when_noop(self):
  self.o[1]['source_sha256']='another'
  with self.assertRaises(ValueError):self.plan()
 def test_model_mismatch(self):
  self.o[1]['model_sha256']='another'
  with self.assertRaises(ValueError):self.plan()
 def test_order_mismatch(self):
  self.o[1]['source_order'][2]='piano'
  with self.assertRaises(ValueError):self.plan()
 def test_wrong_frequency_observer(self):
  self.o[0]['fc']*=2
  with self.assertRaises(ValueError):self.plan()
 def test_nan_observer_even_if_noop(self):
  self.o[0]['band_power'][0,20,2,10]=np.nan
  with self.assertRaises(ValueError):self.plan()
 def test_vocal_region_no_actuation(self):
  self.o=obs(role='vocals');p=self.plan(self.excess());self.assertFalse(p['depth_db'].any())
 def test_context_disagreement_no_actuation(self):
  self.o[0]['band_power'][1,:,1,:]=.20
  self.assertFalse(self.plan(self.excess())['depth_db'].any())
 def test_high_relative_share_with_negligible_energy_rejected(self):
  p=self.o[0]['band_power'];p[:,:,1:,:]*=1e-6
  self.assertFalse(self.plan(self.excess())['depth_db'].any())
 def test_transient_only_not_persistence(self):
  f=features();f['db'][100:103,13]+=20
  self.assertFalse(self.plan(f)['depth_db'].any())
 def test_source_attack_protected(self):
  f=self.excess();f['full_db'][120:140]+=10;p=self.plan(f)
  self.assertFalse(p['depth_db'][120:126].any())
 def test_curve_boundaries(self):
  p=self.plan(self.excess());self.assertFalse(p['depth_db'][p['time']<.4].any());self.assertFalse(p['depth_db'][p['time']>5.6].any());self.assertLessEqual(p['depth_db'].max(),1.5)
 def test_no_support_at_unobserved_time(self):
  self.o[0]['band_time']+=10;self.o[1]['start_seconds']=10;self.o[1]['end_seconds']=16
  self.assertFalse(self.plan(self.excess())['depth_db'].any())
 def test_zero_depth_render_bitwise(self):
  x=np.random.default_rng(8).normal(0,.02,(32000,2));np.testing.assert_array_equal(x,c.render(x,32000,self.plan()))
 def test_zero_strength_bitwise(self):
  x=np.random.default_rng(8).normal(0,.02,(32000,2));np.testing.assert_array_equal(x,c.render(x,32000,self.plan(self.excess()),0))
 def test_plan_budget_rejected(self):
  p=self.plan();p['depth_db'][50,12]=9
  with self.assertRaises(ValueError):c.render(np.zeros((32000,2)),32000,p)
 def test_physical_source_identity(self):
  with tempfile.TemporaryDirectory() as td:
   f=Path(td)/'source.wav';sf.write(f,np.ones((32000,2))*.01,32000,subtype='FLOAT')
   p=self.plan()
   with self.assertRaises(ValueError):c.render_verified(f,p)
 def test_silence_stereo_source_not_mutated(self):
  sr=32000;t=np.arange(sr*6)/sr;s=.1*np.cos(2*np.pi*359*t);s[:3200]=0;x=np.column_stack((s,-s));original=x.copy();y=c.render(x,sr,self.plan(self.excess()))
  np.testing.assert_array_equal(x,original);np.testing.assert_array_equal(y[:3200],0);np.testing.assert_allclose(y[:,0],-y[:,1],atol=1e-14);self.assertGreater(abs(x-y).max(),0)
 def test_config_integer_radius(self):
  with self.assertRaises(ValueError):c.Config(reference_radius_bands=2.1).validate()
  with self.assertRaises(ValueError):c.Config(reference_radius_bands=128).validate()
 def test_no_model_probabilities_claimed(self):
  e=c.observer_evidence(*self.o,'source');self.assertFalse(e['probability_claim'])

if __name__=='__main__':unittest.main(verbosity=2)
