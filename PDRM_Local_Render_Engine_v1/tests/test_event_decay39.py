from pathlib import Path
import sys, unittest, copy, tempfile
from dataclasses import replace
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import event_decay_v39 as e
from decay39_fixtures import event,features,atlas,oracle,local_label,audio_fixture

class DecayDecisionTests(unittest.TestCase):
    def setUp(self):
        self.ev=event(); self.f=features(); self.a=atlas(); self.h='0'*64
        self.o=oracle(self.f['time'],self.ev,self.h)
    def p(self,f=None,o=True,ev=None,a=None):
        return e.plan(self.f if f is None else f,self.ev if ev is None else ev,self.a if a is None else a,self.h,self.o if o else None,allow_test_evidence=True)
    def test_clean_relative_decay_keep(self):
        self.assertEqual(self.p()['status'],'KEEP_NO_EXCESS_RELATIVE_TAIL')
    def test_known_tail_detected(self):
        p=self.p(features(fault_db=6.));self.assertEqual(p['status'],'RELATIVE_TAIL_CANDIDATE');self.assertGreater(p['depth_db'].max(),0)
    def test_constant_color_not_tail_defect(self):
        p=self.p(features(target_color=10));self.assertFalse(p['depth_db'].any());self.assertEqual(p['status'],'KEEP_NO_EXCESS_RELATIVE_TAIL')
    def test_gain_does_not_change_decision(self):
        a=self.p(features(fault_db=6));b=self.p(features(fault_db=6,level_shift=-12));np.testing.assert_allclose(a['depth_db'],b['depth_db'],atol=1e-10)
    def test_same_length_sustain_not_bad(self):
        p=self.p(features(slope=0));self.assertFalse(p['depth_db'].any())
    def test_no_onset_not_permission(self):
        f=features(fault_db=6);f['db'][:]=f['db'][45]
        self.assertEqual(self.p(f)['status'],'ABSTAIN_NO_COMMON_ONSET')
    def test_excess_missing_observer_abstains(self):
        self.assertEqual(self.p(features(fault_db=6),o=False)['status'],'ABSTAIN_LOCAL_ROLE_SUPPORT')
    def test_unknown_family_not_healthy(self):
        ev=replace(self.ev,family='untrained');self.o['event_key']=ev.key()
        self.assertEqual(self.p(features(fault_db=6),ev=ev)['status'],'ABSTAIN_UNCALIBRATED_ROLE_OR_FAMILY')
    def test_observer_source_mismatch_even_clean(self):
        self.o['source_sha256']='1'*64
        with self.assertRaises(ValueError):self.p()
    def test_synthetic_oracle_blocked_by_default(self):
        with self.assertRaises(ValueError):e.plan(self.f,self.ev,self.a,self.h,self.o)
    def test_invalid_observer_clock(self):
        self.o['time']*=1000
        with self.assertRaises(ValueError):self.p()
    def test_invalid_feature_clock(self):
        self.f['time']*=1000
        with self.assertRaises(ValueError):self.p()
    def test_nonfinite_feature_not_bypassed(self):
        self.f['db'][20,1]=np.nan
        with self.assertRaises(ValueError):self.p()
    def test_nonboolean_support_rejected(self):
        self.o['supported']=np.ones(len(self.o['time']))
        with self.assertRaises(ValueError):self.p()
    def test_no_support_outside_coverage(self):
        self.o['time']+=10
        p=self.p(features(fault_db=6));self.assertFalse(p['depth_db'].any());self.assertEqual(p['status'],'ABSTAIN_LOCAL_ROLE_SUPPORT')
    def test_short_excursion_rejected(self):
        f=features();f['db'][95:98,12]+=9
        self.assertFalse(self.p(f)['depth_db'].any())
    def test_disagreeing_companions_not_basis(self):
        f=features(fault_db=6);f['db'][70:,18]+=10
        self.assertFalse(self.p(f)['depth_db'].any())
    def test_heads_protected(self):
        p=self.p(features(fault_db=6));self.assertFalse(p['depth_db'][p['time']<=self.ev.anchor_end_seconds+.08].any())
    def test_only_declared_band(self):
        p=self.p(features(fault_db=6));self.assertFalse(np.delete(p['depth_db'],12,axis=1).any())
    def test_limited_depth(self):
        self.assertLessEqual(self.p(features(fault_db=40))['depth_db'].max(),1.5+1e-12)
    def test_atlas_hash_guard(self):
        self.a['cap_db'][20]+=1
        with self.assertRaises(ValueError):self.p()
    def test_atlas_config_guard(self):
        with self.assertRaises(ValueError):e.plan(self.f,self.ev,self.a,self.h,self.o,e.Config(minimum_run_seconds=.2),allow_test_evidence=True)
    def test_bad_config_rejected(self):
        for cfg in (e.Config(minimum_run_seconds=120),e.Config(maximum_cut_db=5),e.Config(grid_seconds=20)):
            with self.assertRaises(ValueError):cfg.validate()
    def test_duplicate_companion_rejected(self):
        with self.assertRaises(ValueError):replace(self.ev,companion_bands=(6,6)).validate()
    def test_target_as_companion_rejected(self):
        with self.assertRaises(ValueError):replace(self.ev,companion_bands=(6,12)).validate()
    def test_event_seconds_and_bounds(self):
        with self.assertRaises(ValueError):replace(self.ev,end_seconds=3400).validate()
    def test_invalid_anchor(self):
        with self.assertRaises(ValueError):replace(self.ev,anchor_end_seconds=.81).validate()
    def test_no_references_from_same_source(self):
        row=dict(group_id='same',features=self.f,event=self.ev,label=local_label(self.ev))
        with self.assertRaises(ValueError):e.calibrate([row]*4)
    def test_role_positive_is_not_wholemix_positive(self):
        label=local_label(self.ev);other=replace(self.ev,role='other')
        self.assertEqual(e.review_applicability(label,other),'OUTSIDE_ROLE')
    def test_blank_not_good(self):
        self.assertEqual(e.review_applicability({'quality':'-'},self.ev),'UNREVIEWED')
    def test_whole_track_comment_is_weak(self):
        label=local_label(self.ev);label.pop('time_range_seconds')
        self.assertEqual(e.review_applicability(label,self.ev),'WEAK_TRACK_ROLE_LABEL')
    def test_wrong_phenomenon(self):
        label=local_label(self.ev);label['phenomenon']='hit_loudness'
        self.assertEqual(e.review_applicability(label,self.ev),'OUTSIDE_PHENOMENON')
    def test_other_interval_not_transferable(self):
        label=local_label(self.ev);label['time_range_seconds']=[0,.5]
        self.assertEqual(e.review_applicability(label,self.ev),'OUTSIDE_REVIEW_INTERVAL')
    def test_weak_labels_not_calibration(self):
        label=local_label(self.ev);label.pop('time_range_seconds')
        rows=[dict(group_id=str(i),features=self.f,event=self.ev,label=label) for i in range(4)]
        with self.assertRaises(ValueError):e.calibrate(rows)
    def test_mixed_families_not_calibration(self):
        rows=[dict(group_id=str(i),features=self.f,event=self.ev,label=local_label(self.ev)) for i in range(4)]
        rows[2]['event']=replace(self.ev,family='different')
        with self.assertRaises(ValueError):e.calibrate(rows)

class DecayRendererTests(unittest.TestCase):
    def setUp(self):
        self.ev=event();self.f=features(fault_db=6);self.a=atlas();self.h='0'*64;self.o=oracle(self.f['time'],self.ev,self.h)
        self.p=e.plan(self.f,self.ev,self.a,self.h,self.o,allow_test_evidence=True)
        self.x,_,_=audio_fixture(sr=32000);self.sr=32000
    def test_actual_nonzero_renderer(self):
        y=e.render_array(self.x,self.sr,self.p);self.assertGreater(np.max(abs(y-self.x)),0)
    def test_noop_exact(self):
        p=e.plan(features(),self.ev,self.a,self.h,self.o,allow_test_evidence=True)
        np.testing.assert_array_equal(self.x,e.render_array(self.x,self.sr,p))
    def test_zero_strength_exact(self):
        np.testing.assert_array_equal(self.x,e.render_array(self.x,self.sr,self.p,0))
    def test_no_pre_onset_or_outside_tail_change(self):
        y=e.render_array(self.x,self.sr,self.p);t=np.arange(len(y))/self.sr
        mask=(t<=self.ev.anchor_end_seconds+.08)|(t>=self.ev.end_seconds)
        np.testing.assert_array_equal(y[mask],self.x[mask])
    def test_finite_length(self):
        y=e.render_array(self.x,self.sr,self.p);self.assertEqual(y.shape,self.x.shape);self.assertTrue(np.isfinite(y).all())
    def test_original_unchanged(self):
        old=self.x.copy();e.render_array(self.x,self.sr,self.p);np.testing.assert_array_equal(old,self.x)
    def test_mono_relation(self):
        x=np.repeat(self.x[:,:1],2,axis=1);y=e.render_array(x,self.sr,self.p);np.testing.assert_array_equal(y[:,0],y[:,1])
    def test_antiphase_relation(self):
        x=self.x.copy();x[:,1]=-x[:,0];y=e.render_array(x,self.sr,self.p);np.testing.assert_allclose(y[:,0],-y[:,1],atol=1e-14)
    def test_digital_silence(self):
        self.x[50000:50500]=0;y=e.render_array(self.x,self.sr,self.p);np.testing.assert_array_equal(y[50000:50500],0)
    def test_nonfinite_audio_even_bypass(self):
        self.x[0,0]=np.nan
        with self.assertRaises(ValueError):e.render_array(self.x,self.sr,self.p,0)
    def test_bad_depth(self):
        self.p['depth_db'][80,12]=2
        with self.assertRaises(ValueError):e.render_array(self.x,self.sr,self.p)
    def test_undeclared_band_blocked(self):
        self.p['depth_db'][80,13]=1
        with self.assertRaises(ValueError):e.render_array(self.x,self.sr,self.p)
    def test_wrong_file_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'source.wav';sf.write(p,self.x,self.sr,subtype='DOUBLE')
            with self.assertRaises(ValueError):e.render_verified(p,self.p)
    def test_verified_file_and_source_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            src=Path(folder)/'source.wav';sf.write(src,self.x,self.sr,subtype='DOUBLE');h=e.file_hash(src);self.p['source_sha256']=h
            y,sr=e.render_verified(src,self.p);self.assertEqual(sr,self.sr);self.assertEqual(h,e.file_hash(src));self.assertGreater(np.max(abs(y-self.x)),0)
    def test_short_source_rejected(self):
        with self.assertRaises(ValueError):e.render_array(self.x[:32000],self.sr,self.p)
    def test_timing_units_render_rejected(self):
        self.p['time']*=1000
        with self.assertRaises(ValueError):e.render_array(self.x,self.sr,self.p)
    def test_negative_strength(self):
        with self.assertRaises(ValueError):e.render_array(self.x,self.sr,self.p,-1)
    def test_unsupported_samplerate(self):
        with self.assertRaises(ValueError):e.render_array(self.x,22050,self.p)

if __name__=='__main__':unittest.main(verbosity=2)
