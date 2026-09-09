from pathlib import Path
from dataclasses import replace
from fractions import Fraction
from unittest.mock import patch
import copy
import tempfile
import unittest
import numpy as np
import soundfile as sf
import integration_contract_v40 as c
import lowend_coordinator_v40 as co
import lowend_boundary_lab as old_render


def tone(sr=48000, seconds=3.1):
    t = np.arange(round(sr*seconds))/sr
    s = .12*np.cos(2*np.pi*61*t)+.04*np.cos(2*np.pi*244*t)+.02*np.sin(2*np.pi*3300*t)
    return np.column_stack((s, s*.95))


class FileCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.source = self.root/'original.wav'; self.physical = self.root/'prepared.wav'
        self.x = tone(); sf.write(self.source, self.x, 48000, subtype='FLOAT')
        sf.write(self.physical, self.x*.8, 48000, subtype='FLOAT')
        self.s = c.capture(self.source); self.p = c.capture(self.physical)
        self.snap = c.RenderSnapshot.bind(self.s, self.p, {'gain':.8})
    def tearDown(self): self.temp.cleanup()
    def proposal(self, name='p1', depth=1., branch='low'):
        return co.CutProposal(name, branch, (12000,24000,96000,120000), (0.,depth,depth,0.), 'engineering fixture only')
    def plan(self, proposals=(), assessment=None):
        proposals = tuple(proposals)
        return co.compile_plan(self.snap, proposals, planner_id='fixture-v1',
            calibration_sha256='a'*64, assessment=assessment or ('CANDIDATE' if proposals else 'KEEP_SUPPORTED'),
            evidence_scope='engineering_fixture')


class IdentityTests(FileCase):
    def test_original_and_physical_hashes_are_distinct(self):
        self.assertNotEqual(self.s.file_sha256,self.p.file_sha256); self.snap.verify(self.source,self.physical)
    def test_pcm_identity_survives_lossless_container_change(self):
        a=self.root/'a.wav'; b=self.root/'b.flac'
        sf.write(a,self.x,48000,subtype='PCM_24'); x,sr=sf.read(a); sf.write(b,x,sr,subtype='PCM_24')
        ia,ib=c.capture(a),c.capture(b)
        self.assertNotEqual(ia.file_sha256,ib.file_sha256); self.assertEqual(ia.pcm_sha256,ib.pcm_sha256)
    def test_changed_source_is_not_name_match(self):
        sf.write(self.source,self.x*.9,48000,subtype='FLOAT')
        with self.assertRaises(ValueError): self.snap.verify(self.source,self.physical)
    def test_changed_physical_is_not_accepted(self):
        sf.write(self.physical,self.x*.7,48000,subtype='FLOAT')
        with self.assertRaises(ValueError): self.snap.verify(self.source,self.physical)
    def test_nonfinite_audio_fails_before_noop(self):
        x=self.x.copy(); x[-2,1]=np.nan; sf.write(self.physical,x,48000,subtype='FLOAT')
        with self.assertRaises(ValueError): self.p.verify(self.physical)
    def test_wrong_stage_rejected(self):
        with self.assertRaises(ValueError): replace(self.snap,stage='RAW').validate()
    def test_recipe_changes_snapshot(self):
        other=c.RenderSnapshot.bind(self.s,self.p,{'gain':.8,'recipe':'different'})
        self.assertNotEqual(self.snap.token,other.token)
    def test_geometry_does_not_implicitly_create_src_map(self):
        p=replace(self.p,samplerate=96000,frames=self.p.frames*2)
        with self.assertRaises(ValueError): c.RenderSnapshot.bind(self.s,p,{})
    def test_declared_geometry_mismatch(self):
        with self.assertRaises(ValueError): replace(self.snap,clock=replace(self.snap.clock,source_rate=44100)).validate()
    def test_bad_hash_is_not_identity(self):
        with self.assertRaises(ValueError): replace(self.s,file_sha256='g'*64).validate()
    def test_nonstereo_rejected(self):
        f=self.root/'mono.wav'; sf.write(f,self.x[:,0],48000)
        with self.assertRaises(ValueError): c.capture(f)
    def test_short_audio_rejected(self):
        f=self.root/'short.wav'; sf.write(f,self.x[:100],48000)
        with self.assertRaises(ValueError): c.capture(f)


class ClockTests(unittest.TestCase):
    def test_44_to_48_exact_long_clock(self):
        m=c.FrameMap(44100,44100*1800,48000,48000*1800)
        self.assertEqual(m.exact(44100*1799),Fraction(48000*1799))
    def test_conservative_fractional_edges(self):
        m=c.FrameMap(44100,44100,48000,48000)
        self.assertEqual(m.span(c.Span(1,2)),c.Span(1,3))
    def test_exact_fractional_delay_recorded(self):
        m=c.FrameMap(48000,48000,48000,48000,1,2)
        self.assertEqual(m.exact(40),Fraction(81,2)); self.assertEqual(m.nearest(40),41)
    def test_negative_frame_not_silently_clamped(self):
        m=c.FrameMap(48000,48000,48000,48000,-1,1)
        with self.assertRaises(ValueError): m.span(c.Span(0,20))
    def test_truncation_rejected(self):
        with self.assertRaises(ValueError): c.FrameMap(48000,96000,48000,48000).validate()
    def test_second_ms_value_not_accepted_as_frame(self):
        with self.assertRaises(ValueError): c.Span(.128,1).validate(48000)
    def test_bool_is_not_integer_clock(self):
        with self.assertRaises(ValueError): c.Span(False,1).validate(48000)
    def test_128ms_coverage_native_frame_count(self):
        m=c.FrameMap(48000,48000*200,48000,48000*200)
        self.assertEqual(m.span(c.Span(48000,48000+6144)),c.Span(48000,54144))


class ScheduleTests(unittest.TestCase):
    def test_full_song_has_no_core_gaps(self):
        n=48000*33+37
        w=c.observation_windows([c.Span(0,n)],length=n,rate=48000)
        self.assertEqual(w[0].core.start,0); self.assertEqual(w[-1].core.stop,n)
        for a,b in zip(w,w[1:]): self.assertEqual(a.core.stop,b.core.start)
    def test_core_is_not_halo(self):
        w=c.observation_windows([c.Span(48000*3,48000*4)],length=48000*10,rate=48000)[0]
        self.assertEqual(w.core,c.Span(144000,192000)); self.assertEqual(w.read,c.Span(48000,288000))
    def test_duplicates_overlap_merge(self):
        spans=[c.Span(50,100),c.Span(0,75),c.Span(50,100)]
        w=c.observation_windows(spans,length=480000,rate=48000)
        self.assertEqual(len(w),1); self.assertEqual(w[0].core,c.Span(0,100))
    def test_separate_regions_remain_unobserved_between(self):
        w=c.observation_windows([c.Span(0,100),c.Span(200,300)],length=480000,rate=48000)
        self.assertEqual(len(w),2)
    def test_file_edges_clipped_only_for_context(self):
        w=c.observation_windows([c.Span(0,480000)],length=480000,rate=48000)
        self.assertEqual(w[0].read.start,0); self.assertEqual(w[-1].read.stop,480000)
    def test_empty_schedule_not_fake_coverage(self):
        self.assertEqual(c.observation_windows([],length=480000,rate=48000),())
    def test_invalid_interval(self):
        with self.assertRaises(ValueError): c.observation_windows([c.Span(5,500001)],length=500000,rate=48000)
    def test_unit_range_for_context(self):
        with self.assertRaises(ValueError): c.observation_windows([],length=480000,rate=48000,halo_seconds=2000)


class CommonPlanTests(FileCase):
    def test_duplicate_cut_is_max_not_sum(self):
        p=self.plan([self.proposal('a',1.5),self.proposal('b',1.5)])
        self.assertAlmostEqual(max(p['low_cut_db']),1.5)
    def test_independent_lowmid_branch(self):
        p=self.plan([self.proposal('a',1.),self.proposal('b',.5,'lowmid')])
        self.assertEqual(max(p['lowmid_cut_db']),.5)
    def test_unknown_synthesis_not_replaced_by_eq(self):
        with self.assertRaises(ValueError): self.plan([self.proposal(branch='SAME_FUNDAMENTAL')])
    def test_duplicate_proposal_id(self):
        with self.assertRaises(ValueError): self.plan([self.proposal(),self.proposal()])
    def test_modified_plan_even_with_new_seal_rejected(self):
        p=self.plan(); p['low_cut_db'][50]=1.; p['sha256']=c.digest({k:v for k,v in p.items() if k!='sha256'})
        with self.assertRaises(ValueError): co.validate_plan(p,self.snap)
    def test_foreign_snapshot_rejected(self):
        p=self.plan(); other=replace(self.snap,recipe_sha256='b'*64)
        with self.assertRaises(ValueError): co.validate_plan(p,other)
    def test_keep_cannot_mask_processing(self):
        with self.assertRaises(ValueError): self.plan([self.proposal()],assessment='KEEP_SUPPORTED')
    def test_abstain_remains_distinct(self):
        p=self.plan(assessment='ABSTAIN'); self.assertEqual(p['assessment'],'ABSTAIN'); self.assertFalse(any(p['low_cut_db']))
    def test_zero_correction_is_not_candidate(self):
        with self.assertRaises(ValueError): self.plan([self.proposal(depth=0)])
    def test_negative_and_excess_depth_rejected(self):
        for dep in (-.1,2.1,float('nan')):
            with self.subTest(depth=dep), self.assertRaises(ValueError): self.plan([self.proposal(depth=dep)])
    def test_endpoint_fade_explicit(self):
        p=replace(self.proposal(),depth_db=(1.,1.,1.,0.))
        with self.assertRaises(ValueError): self.plan([p])
    def test_control_clock_must_be_monotone(self):
        p=replace(self.proposal(),source_frames=(12000,24000,23999,120000))
        with self.assertRaises(ValueError): self.plan([p])
    def test_fractional_src_control_projection(self):
        phys=replace(self.p,samplerate=96000,frames=self.p.frames*2)
        snap=c.RenderSnapshot.bind(self.s,phys,{},c.FrameMap(48000,self.s.frames,96000,phys.frames))
        p=co.compile_plan(snap,[self.proposal()],planner_id='f',calibration_sha256='a'*64,assessment='CANDIDATE',evidence_scope='engineering_fixture')
        self.assertIn(48000,p['physical_frames'])
    def test_missing_calibration_identity(self):
        with self.assertRaises(ValueError): co.compile_plan(self.snap,[],planner_id='f',calibration_sha256='',assessment='KEEP_SUPPORTED',evidence_scope='engineering_fixture')


class RenderTests(FileCase):
    def test_keep_preserves_bytes(self):
        out=self.root/'out.wav'; co.render(self.source,self.physical,out,self.snap,self.plan())
        self.assertEqual(c.file_hash(out),self.p.file_sha256)
    def test_streaming_matches_existing_full_renderer(self):
        p=self.plan([self.proposal(depth=1.5)])
        x,sr=sf.read(self.physical,dtype='float64',always_2d=True)
        cp=dict(time=np.asarray(p['physical_frames'])/sr,low_cut_db=p['low_cut_db'],lowmid_cut_db=p['lowmid_cut_db'])
        expected=old_render.render_array(x,sr,cp)
        out=self.root/'out.wav'; co.render(self.source,self.physical,out,self.snap,p,chunk_frames=sr)
        y,_=sf.read(out,dtype='float64',always_2d=True)
        np.testing.assert_allclose(y,expected,rtol=0,atol=2e-12)
        self.assertGreater(np.max(abs(y-x)),1e-5)
    def test_partition_changes_do_not_change_signal(self):
        p=self.plan([self.proposal()]); a=self.root/'a.wav'; b=self.root/'b.wav'
        co.render(self.source,self.physical,a,self.snap,p,chunk_frames=24000)
        co.render(self.source,self.physical,b,self.snap,p,chunk_frames=72000)
        x,_=sf.read(a);y,_=sf.read(b);np.testing.assert_allclose(x,y,rtol=0,atol=2e-12)
    def test_outside_support_unchanged(self):
        p=self.plan([self.proposal()]); out=self.root/'out.wav'; co.render(self.source,self.physical,out,self.snap,p)
        y,_=sf.read(out);x,_=sf.read(self.physical)
        np.testing.assert_array_equal(y[:12000],x[:12000]);np.testing.assert_array_equal(y[120000:],x[120000:])
    def test_existing_file_never_overwritten(self):
        out=self.root/'out.wav'; out.write_bytes(b'existing')
        with self.assertRaises(FileExistsError): co.render(self.source,self.physical,out,self.snap,self.plan())
        self.assertEqual(out.read_bytes(),b'existing')
    def test_foreign_partial_preserved(self):
        out=self.root/'out.wav'; part=self.root/'out.wav.partial.wav'; part.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError): co.render(self.source,self.physical,out,self.snap,self.plan())
        self.assertEqual(part.read_bytes(),b'foreign')
    def test_failure_cleans_own_partial(self):
        class Cancel:
            def set(self,*args): raise InterruptedError('cancel')
        out=self.root/'out.wav'
        with self.assertRaises(InterruptedError): co.render(self.source,self.physical,out,self.snap,self.plan([self.proposal()]),progress=Cancel())
        self.assertFalse(out.exists()); self.assertFalse((self.root/'out.wav.partial.wav').exists())
    def test_source_mutation_detected_during_render(self):
        source=self.source;x=self.x
        class Mutate:
            def set(self,*args): sf.write(source,x*.5,48000,subtype='FLOAT')
        out=self.root/'out.wav'
        with self.assertRaises(ValueError): co.render(self.source,self.physical,out,self.snap,self.plan([self.proposal()]),progress=Mutate())
        self.assertFalse(out.exists())
    def test_null_does_not_hide_source_nan(self):
        p=self.plan(); x=self.x.copy();x[10,0]=np.nan;sf.write(self.source,x,48000,subtype='FLOAT')
        with self.assertRaises(ValueError): co.render(self.source,self.physical,self.root/'out.wav',self.snap,p)
    def test_bounded_chunk_budget(self):
        with self.assertRaises(ValueError): co.render(self.source,self.physical,self.root/'out.wav',self.snap,self.plan(),chunk_frames=48000*100)


if __name__=='__main__': unittest.main(verbosity=2)
