from pathlib import Path
import sys,tempfile,unittest,copy
import numpy as np,soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import spectral_persistence_lab as sp
import event_groove_v37 as ev


def feature(n=300):
 t=np.arange(n)*.02
 return dict(time=t,fc=sp.centers(),db=np.full((n,20),-40.),full_db=np.full(n,-20.))

def observer(seconds=6,digest='source',role='other',pitch=55.):
 t=np.arange(round(seconds*100))*.01;n=len(t)
 p=np.zeros((2,n,5))+1e-10;p[:,:,0]=.04
 for roleidx in range(1,5):p[:,:,roleidx]=.0001
 idx=['mix','drums','bass','other','vocals'].index(role);p[:,:,idx]=.03
 a=dict(time=t,low_power=p.copy(),body_power=p.copy(),focus_power=p.copy(),bass_f0_hz=np.full((2,n),pitch),bass_periodicity=np.full((2,n),.99))
 m=dict(version='role-observer-0.2.0',source_sha256=digest,source_order=['mix','drums','bass','other','vocals'],start_seconds=0.,end_seconds=float(seconds))
 return a,m

class SpectralContracts(unittest.TestCase):
 def setUp(self):
  self.f=feature();self.a=sp.calibrate([feature() for _ in range(4)],['a','b','c','d']);self.o=observer()
 def plan(self,f=None,o=True):return sp.plan(self.f if f is None else f,self.a,'source',self.o if o else None)
 def excess(self):
  f=feature();f['db'][:,13]+=4;return f
 def test_clean_noop(self):self.assertEqual(self.plan()['status'],'NO_EVIDENCE')
 def test_absent_observer_not_healthy(self):self.assertEqual(self.plan(self.excess(),o=False)['status'],'ABSTAIN_ROLE_OR_COVERAGE')
 def test_excess_with_observer(self):self.assertGreater(self.plan(self.excess())['depth_db'].max(),0)
 def test_wrong_source_rejected(self):
  with self.assertRaises(ValueError):sp.plan(self.excess(),self.a,'another',self.o)
 def test_missing_coverage_no_change(self):
  a,m=self.o;m['start_seconds']=20;m['end_seconds']=26;a['time']+=20
  self.assertFalse(np.any(self.plan(self.excess())['depth_db']))
 def test_voice_protection(self):
  self.o=observer(role='vocals');self.assertFalse(np.any(self.plan(self.excess())['depth_db']))
 def test_context_disagreement(self):
  self.o[0]['focus_power'][1,:,1:]=1e-5;self.o[0]['focus_power'][1,:,1]=.05
  self.assertFalse(np.any(self.plan(self.excess())['depth_db']))
 def test_bad_calibration_hash(self):
  self.a['caps_db'][0]+=1
  with self.assertRaises(ValueError):self.plan()
 def test_duplicate_ref_ids(self):
  with self.assertRaises(ValueError):sp.calibrate([self.f]*4,['a']*4)
 def test_invalid_ms_conversion(self):
  f=feature();f['time']*=1000
  with self.assertRaises(ValueError):self.plan(f)
 def test_nan_input(self):
  f=feature();f['db'][3,1]=np.nan
  with self.assertRaises(ValueError):self.plan(f)
 def test_fixed_time_guard(self):
  p=self.plan(self.excess());self.assertFalse(np.any(p['depth_db'][p['time']<.4]));self.assertFalse(np.any(p['depth_db'][p['time']>5.6]))
 def test_unsupported_role_frequency_abstains(self):
  f=feature();f['db'][:,17]+=6;p=self.plan(f)
  self.assertEqual(p['status'],'ABSTAIN_ROLE_OR_COVERAGE');self.assertFalse(p['depth_db'].any())
 def test_band_budget(self):self.assertLessEqual(self.plan(self.excess())['depth_db'].max(),1.5)
 def test_transient_not_persistent(self):
  f=feature();f['db'][100:104,13]+=12
  self.assertFalse(self.plan(f)['depth_db'].any())
 def test_neutral_render_exact(self):
  x=np.random.default_rng(4).normal(0,.03,(48000,2));np.testing.assert_array_equal(x,sp.render(x,48000,self.plan()))
 def test_zero_strength_exact(self):
  x=np.random.default_rng(4).normal(0,.03,(48000,2));np.testing.assert_array_equal(x,sp.render(x,48000,self.plan(self.excess()),0))
 def test_bad_plan_rejected(self):
  p=self.plan();p['depth_db'][50,13]=-2
  with self.assertRaises(ValueError):sp.render(np.zeros((48000,2)),48000,p)
 def test_source_unchanged_and_shape(self):
  sr=12000*4;t=np.arange(sr*6)/sr;s=.1*np.sin(2*np.pi*359*t)+.02*np.sin(2*np.pi*3000*t);x=np.column_stack((s,s));x[:1000]=0;before=x.copy()
  y=sp.render(x,sr,self.plan(self.excess()));np.testing.assert_array_equal(x,before);self.assertEqual(y.shape,x.shape);np.testing.assert_array_equal(y[:1000],0);np.testing.assert_array_equal(y[:,0],y[:,1]);self.assertGreater(np.max(abs(y-x)),0)
 def test_antiphase_preserved(self):
  sr=32000;t=np.arange(sr*6)/sr;s=.1*np.sin(2*np.pi*359*t);x=np.column_stack((s,-s));y=sp.render(x,sr,self.plan(self.excess()));np.testing.assert_allclose(y[:,0],-y[:,1],atol=1e-14)
 def test_energy_not_mono_cancelled(self):
  sr=32000;t=np.arange(sr)/sr;s=.1*np.sin(2*np.pi*359*t);x=np.column_stack((s,-s));f=sp.extract(x,sr,0);self.assertGreater(f['db'][:,13].max(),-30)
 def test_gain_invariance(self):
  sr=32000;t=np.arange(sr)/sr;s=.1*np.sin(2*np.pi*359*t);x=np.column_stack((s,s));a=sp.extract(x,sr,0);b=sp.extract(x*.5,sr,20*np.log10(2));np.testing.assert_allclose(a['db'],b['db'],atol=1e-9)

class EventContracts(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.p=Path(self.tmp.name)/'source.wav';self.sr=48000;t=np.arange(self.sr*2)/self.sr
  s=.004*np.cos(2*np.pi*55*t)+.08*np.cos(2*np.pi*110*t)+.04*np.cos(2*np.pi*165*t);self.x=np.column_stack((s,s));sf.write(self.p,self.x,self.sr,subtype='FLOAT')
  self.o=observer(2,ev.file_hash(self.p),role='bass');self.event=dict(start=.4,end=1.4,source_f0_hz=55.,target_hz=55.)
 def tearDown(self):self.tmp.cleanup()
 def process(self,e=None):return ev.process_event(self.p,e or self.event,*self.o)
 def test_actual_positive_synthesizes(self):
  d,r=self.process();self.assertTrue(r['allowed']);self.assertEqual(r['action'],'SAME_FUNDAMENTAL_CANDIDATE');self.assertGreater(np.max(abs(d)),0);self.assertLessEqual(r['added_rms_fraction'],.1+1e-12)
 def test_octave_rejected(self):
  e=dict(self.event,source_f0_hz=110.);d,r=self.process(e);self.assertIn('DENY_NEW_OCTAVE',r['reason_codes']);self.assertFalse(d.any())
 def test_forced_wrong_pitch_rejected(self):
  self.o[0]['bass_f0_hz'][:]=110.;d,r=self.process();self.assertFalse(d.any());self.assertIn('ABSTAIN_LOCAL_ROLE_OR_PITCH',r['reason_codes'])
 def test_local_not_wide_average(self):
  a,m=self.o;sel=(a['time']>=.4)&(a['time']<1.4)
  for k in ('low_power','body_power'):a[k][:,sel,2]=1e-13;a[k][:,sel,3]=.05
  d,r=self.process();self.assertFalse(r['allowed']);self.assertFalse(d.any())
 def test_missing_observer_abstains(self):
  d,r=ev.process_event(self.p,self.event,None,None);self.assertFalse(d.any());self.assertIn('ABSTAIN_NO_OBSERVER',r['reason_codes'])
 def test_source_mismatch_error(self):
  self.o[1]['source_sha256']='wrong'
  with self.assertRaises(ValueError):self.process()
 def test_outside_coverage(self):
  e=dict(self.event,start=.05,end=.6);self.o[1]['start_seconds']=.2;self.o[0]['time']+=.2;self.o[1]['end_seconds']=2.2
  d,r=self.process(e);self.assertFalse(d.any());self.assertIn('ABSTAIN_OUTSIDE_OBSERVATION',r['reason_codes'])
 def test_nonfinite_observer(self):
  self.o[0]['low_power'][0,50,1]=np.nan
  with self.assertRaises(ValueError):self.process()
 def test_low_periodicity(self):
  self.o[0]['bass_periodicity'][:]=.3;d,r=self.process();self.assertFalse(d.any())
 def test_observer_order_invalid(self):
  self.o[1]['source_order'][1]='bass'
  with self.assertRaises(ValueError):self.process()
 def test_no_stem_samples_used(self):
  d,r=self.process();self.assertFalse(r['stem_samples_in_output']);np.testing.assert_array_equal(d[:,0],d[:,1])
 def test_exact_endpoints_zero(self):
  d,r=self.process();np.testing.assert_array_equal(d[0],0);np.testing.assert_allclose(d[-1],0,atol=1e-14)
 def test_source_unchanged(self):
  h=ev.file_hash(self.p);self.process();self.assertEqual(h,ev.file_hash(self.p))
 def test_already_full_no_addition(self):
  t=np.arange(self.sr*2)/self.sr;s=.1*np.cos(2*np.pi*55*t)+.05*np.cos(2*np.pi*110*t);sf.write(self.p,np.column_stack((s,s)),self.sr,subtype='FLOAT');self.o[1]['source_sha256']=ev.file_hash(self.p)
  d,r=self.process();self.assertFalse(d.any());self.assertIn('KEEP_ALREADY_SUFFICIENT',r['reason_codes'])
 def test_missing_fundamental_deferred(self):
  t=np.arange(self.sr*2)/self.sr;s=.1*np.cos(2*np.pi*110*t)+.05*np.cos(2*np.pi*165*t);sf.write(self.p,np.column_stack((s,s)),self.sr,subtype='FLOAT');self.o[1]['source_sha256']=ev.file_hash(self.p)
  d,r=self.process();self.assertFalse(d.any());self.assertIn('ABSTAIN_MISSING_FUNDAMENTAL_REPAIR_UNIMPLEMENTED',r['reason_codes'])
 def test_observer_ms_clock_rejected(self):
  self.o[0]['time']*=1000
  with self.assertRaises(ValueError):self.process()
 def test_disagreement_refused(self):
  for k in ('low_power','body_power'):self.o[0][k][1,:,1]=.1
  d,r=self.process();self.assertFalse(d.any())
 def test_uncertain_internal_span_not_filled(self):
  a,m=self.o;bad=(a['time']>=.85)&(a['time']<.90)
  a['bass_periodicity'][:,bad]=.1
  d,r=self.process();self.assertTrue(r['allowed']);self.assertGreater(np.max(abs(d)),0)
  lo=round((.85-.4)*self.sr);hi=round((.9-.4)*self.sr)
  np.testing.assert_array_equal(d[lo:hi],0)
 def test_nonfinite_source_never_hidden_by_abstain(self):
  self.x[25000]=np.nan;sf.write(self.p,self.x,self.sr,subtype='FLOAT');self.o[1]['source_sha256']=ev.file_hash(self.p)
  with self.assertRaises(ValueError):self.process(dict(self.event,source_f0_hz=110.))
 def test_bad_event(self):
  with self.assertRaises(ValueError):self.process(dict(self.event,start=float('nan')))

if __name__=='__main__':unittest.main(verbosity=2)
