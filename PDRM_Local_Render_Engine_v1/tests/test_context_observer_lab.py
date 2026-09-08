import unittest
import numpy as np
import lowend_boundary_lab as b
import context_occupancy_lab as c
from stem_observer_lab import describe

class ContextContracts(unittest.TestCase):
 def features(self,floor=-35,high=-16,n=2400):
  t=np.arange(n)*.01;y=floor+(high-floor)*(np.sin(t*8)>0)
  return dict(time=t,low_db=y,lowmid_db=y-5,mid_db=np.full(n,-23.),deep_db=y-3,
              present=np.ones(n,dtype=bool),configuration=b.asdict(b.Config()))
 def atlas(self):
  return c.calibrate([self.features(v) for v in (-40,-37,-34,-31)],['a','b','c','d'])
 def test_correct_twelve_second_window(self):
  f=self.features();w=c.windows(f)
  self.assertEqual(w[0]['end_index']-w[0]['start_index'],1200)
  self.assertAlmostEqual(w[0]['end_seconds']-w[0]['start_seconds'],12.)
 def test_file_edge_range(self):
  f=self.features(n=2501)
  for w in c.windows(f):self.assertLessEqual(w['end_index'],len(f['time']))
 def test_null_input_kept(self):
  p=c.plan(self.features(),self.atlas());self.assertEqual(p['status'],'NO_CONTEXT_EXCESS')
  self.assertTrue(np.all(p['low_cut_db']==0))
 def test_late_excess_localized(self):
  f=self.features(n=6000);f['low_db'][4000:]=-20
  p=c.plan(f,self.atlas());self.assertGreater(p['low_cut_db'][4500],0)
  self.assertTrue(np.all(p['low_cut_db'][:2500]==0))
 def test_bounds(self):
  f=self.features(floor=-15,high=-5);p=c.plan(f,self.atlas())
  self.assertLessEqual(p['low_cut_db'].max(),b.Config().max_tail_cut_db+1e-12)
 def test_no_lowmid_actuation(self):
  p=c.plan(self.features(floor=-15,high=-5),self.atlas())
  self.assertTrue(np.all(p['lowmid_cut_db']==0))
 def test_mismatched_config_rejected(self):
  a=self.atlas();a['version']='wrong'
  with self.assertRaises(ValueError):c.plan(self.features(),a)
 def test_nan_cap_rejected(self):
  a=self.atlas();a['floor_cap_db']=float('nan')
  with self.assertRaises(ValueError):c.plan(self.features(),a)
 def test_duplicate_groups_rejected(self):
  with self.assertRaises(ValueError):c.calibrate([self.features()]*4,['a']*4)
 def test_reference_exclusion_metadata(self):
  a=self.atlas();self.assertEqual(a['reference_ids'],['a','b','c','d'])
 def test_score_uses_same_source_intervals(self):
  f=self.features(floor=-20,high=-10);p=c.plan(f,self.atlas());e=c.score(f,p)
  g=dict(f,low_db=f['low_db']-1);self.assertLess(c.score(g,p),e)
 def test_absence_not_low_bass(self):
  f=self.features(floor=-10);f['present'][:]=False
  self.assertEqual(c.plan(f,self.atlas())['selected_windows'],[])

class ObserverContracts(unittest.TestCase):
 def test_shapes_and_metadata(self):
  sr=44100;t=np.arange(sr)/sr
  x=np.column_stack([np.sin(2*np.pi*60*t),np.sin(2*np.pi*60*t)])*.1
  s=np.zeros((4,2,len(t)));s[1]=x.T
  r=describe(x,s,sr)
  self.assertGreater(r['energy_shares']['low']['bass'],.9999)
  self.assertIn('neither additive mixture powers',r['ratio_warning'])
 def test_energy_share_is_not_confidence(self):
  sr=44100;t=np.arange(sr)/sr;x=np.column_stack([np.sin(2*np.pi*80*t)]*2)*.1
  s=np.repeat(x.T[None],4,axis=0)
  r=describe(x,s,sr)
  self.assertNotIn('bass_confidence',r)
  self.assertIn('nor source probabilities',r['ratio_warning'])
 def test_sum_error_retained(self):
  sr=44100;x=np.ones((sr,2))*.01;s=np.zeros((4,2,sr))
  r=describe(x,s,sr);self.assertAlmostEqual(r['sum_stems_relative_error_db'],0,places=5)
 def test_original_not_modified(self):
  sr=44100;rng=np.random.default_rng(4);x=rng.normal(0,.01,(sr,2));before=x.copy();s=np.zeros((4,2,sr))
  describe(x,s,sr);np.testing.assert_array_equal(x,before)

if __name__=='__main__':unittest.main()
