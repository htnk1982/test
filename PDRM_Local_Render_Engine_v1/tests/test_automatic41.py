"""No private songs. Timings for assertions are not passed into the planner.

Role fixture is explicitly synthetic; the source scanner, reference calibration,
physical candidate measurement and final chain are the actual implementations.
A separate optional run exercises the neural observer without pretending it is
an oracle or promising that the neural model recognises synthetic instruments.
"""
from pathlib import Path
from dataclasses import asdict
import tempfile,unittest,json
import numpy as np
import soundfile as sf
import source_events_v41 as ev
import automatic_lowend_v41 as ap
from integration_contract_v40 import capture,RenderSnapshot,digest
from integrated_finish_v40 import PlanningContext
import lowend_coordinator_v40 as coord

ONSET_CASES=((.52,.27,55.),(1.41,.42,55.),(2.37,.64,73.416),(3.67,.3,110.))

def song(sr=48000,seconds=5.2,low=.04,phase=.0,sustain=False):
    t=np.arange(round(sr*seconds))/sr
    # A high-frequency independent layer; no fake bass from stereo cancellation.
    y=.06*np.sin(2*np.pi*1700*t+phase)+.04*np.sin(2*np.pi*2300*t)
    bass=np.zeros(len(t))
    for onset,duration,f0 in ONSET_CASES:
        age=t-onset;sel=(age>=0)&(age<duration)
        envelope=np.clip(age/.01,0,1)*np.clip((duration-age)/.035,0,1)*sel
        if not sustain:envelope*=np.exp(-np.maximum(age,0)*1.2)
        bass+=low*envelope*(np.sin(2*np.pi*f0*t+phase)+.45*np.sin(2*np.pi*f0*2*t)+.2*np.sin(2*np.pi*f0*3*t))
    return np.column_stack((y+bass,.94*y+bass))

class FixtureRoles:
    def __init__(self,mode='support'):self.mode=mode;self.calls=[]
    def identity(self):return dict(provider='synthetic_roles41',evidence_scope='engineering_fixture',mode=self.mode)
    def preflight(self):pass
    def observe(self,source,start,end,progress=None):
        ident=capture(source);t=start+np.arange(round((end-start)*100))*.01;n=len(t)
        p=np.full((2,n,5),.0001);p[:,:,0]=.03;p[:,:,2]=.027
        if self.mode=='voice':p[:,:,2]=.0001;p[:,:,4]=.027
        if self.mode=='disagree':p[1,:,2]=.0001;p[1,:,4]=.027
        if self.mode=='zero':p[:]=0
        if self.mode=='nan':p[0,1,2]=np.nan
        self.calls.append((start,end))
        return dict(time=t,low_power=p),dict(provider='synthetic_roles41',source_sha256=ident.file_sha256,
          source_frames=ident.frames,source_samplerate=ident.samplerate,source_order=['mix','drums','bass','other','vocals'],start_seconds=start,end_seconds=end)


def save(path,x,sr=48000):sf.write(path,x,sr,subtype='DOUBLE');return path

def calibration(root):
    specs=[]
    for i in range(4):
        p=save(root/f'ref{i}.wav',song(phase=i*.21,low=.028+i*.002))
        specs.append(dict(path=p,role='bass',quality='positive',group_id=f'fixture_{i}'))
    return ap.make_calibration(specs)

class SourceTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.p=save(self.root/'source.wav',song())
    def tearDown(self):self.tmp.cleanup()
    def test_source_only_events_near_actual_onsets(self):
        f,c=ev.analyze_source(self.p);times=[e['start_seconds'] for e in c['events']]
        for onset,_,_ in ONSET_CASES:self.assertLess(min(abs(t-onset) for t in times),.06,(onset,times))
    def test_repeated_same_pitch_rearticulated(self):
        _,c=ev.analyze_source(self.p);ts=[e['start_seconds'] for e in c['events']]
        self.assertTrue(any(abs(t-.52)<.06 for t in ts));self.assertTrue(any(abs(t-1.41)<.06 for t in ts))
    def test_detected_55_not_octave_transposed(self):
        _,c=ev.analyze_source(self.p);a=min(c['events'],key=lambda e:abs(e['start_seconds']-.52))
        self.assertIsNotNone(a['pitch_hz']);self.assertLess(abs(a['pitch_hz']-55),2.)
    def test_periodic_evidence_never_permits_synthesis(self):
        _,c=ev.analyze_source(self.p);self.assertTrue(c['events']);self.assertFalse(any(e['synthesis_authorized'] for e in c['events']))
    def test_antiphase_does_not_erase_events(self):
        x=song();x[:,1]=-x[:,0];save(self.p,x);_,c=ev.analyze_source(self.p);self.assertGreater(len(c['events']),1)
    def test_no_bpm_or_grid_quantization(self):
        _,c=ev.analyze_source(self.p);a=min(c['events'],key=lambda e:abs(e['start_seconds']-2.37));self.assertLess(abs(a['start_seconds']-2.37),.06)
    def test_pure_sine_not_bass_authorization(self):
        sr=48000;t=np.arange(sr*2)/sr;z=.1*np.sin(2*np.pi*110*t)*((t>.5)&(t<1.5));save(self.p,np.column_stack((z,z)))
        _,c=ev.analyze_source(self.p);self.assertTrue(c['events']);self.assertFalse(any(e['synthesis_authorized'] for e in c['events']))
    def test_source_bitwise_preserved(self):
        old=capture(self.p);ev.analyze_source(self.p);self.assertEqual(capture(self.p),old)
    def test_gain_does_not_move_onsets(self):
        f=ev.extract_features(self.p);c=ev.discover(f);x,sr=sf.read(self.p,always_2d=True);q=save(self.root/'quiet.wav',x*.5)
        f2=ev.extract_features(q);c2=ev.discover(f2)
        self.assertEqual([e['start_frame'] for e in c['events']],[e['start_frame'] for e in c2['events']])
    def test_partition_agreement(self):
        f=ev.extract_features(self.p,cfg=ev.Config(chunk_seconds=2));g=ev.extract_features(self.p,cfg=ev.Config(chunk_seconds=8))
        active=(f['full_db']>-100)
        for key in ('low_db','mid_db','fast_db'):np.testing.assert_allclose(f[key][active],g[key][active],atol=.002,rtol=0)
    def test_read_memory_is_bounded(self):
        f=ev.extract_features(self.p,cfg=ev.Config(chunk_seconds=2));self.assertLessEqual(f['max_analysis_read_frames'],4*12000+2)
    def test_silence_no_fake_music(self):
        save(self.p,np.zeros((48000,2)));f,c=ev.analyze_source(self.p);self.assertEqual(c['events'],[]);self.assertFalse(c['healthy_audio_claim'])
    def test_nonfinite_is_error(self):
        x=song();x[4500,0]=np.nan;save(self.p,x)
        with self.assertRaises(ValueError):ev.analyze_source(self.p)
    def test_wrong_ms_clock_rejected(self):
        f=ev.extract_features(self.p);f['time']*=1000
        with self.assertRaises(ValueError):ev.discover(f)
    def test_bounded_config(self):
        for cfg in (ev.Config(chunk_seconds=128),ev.Config(halo_seconds=1000),ev.Config(minimum_rise_db=float('nan'))):
            with self.assertRaises(ValueError):cfg.validate()
    def test_native_rates(self):
        for sr in (32000,44100,96000):
            p=save(self.root/f'{sr}.wav',song(sr=sr),sr);f,c=ev.analyze_source(p)
            self.assertTrue(c['events']);self.assertTrue(all(0<=e['start_frame']<e['stop_frame']<=sf.info(p).frames for e in c['events']))
    def test_cancel_propagates(self):
        class Cancel:
            def set(self,*a):raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError):ev.analyze_source(self.p,Cancel())
    def test_empty_observation_schedule_not_coverage(self):
        s=ev.schedule([],rate=48000,length=48000*60);self.assertEqual(s['windows'],[]);self.assertFalse(s['observed'])
    def test_overlapping_core_seams(self):
        from integration_contract_v40 import Span
        sr=48000;sc=ev.schedule([Span(sr,19*sr)],rate=sr,length=20*sr)
        covered=np.zeros(20*sr,dtype=bool)
        for w in sc['windows']:
            self.assertLessEqual(w['core_stop_frame']-w['core_start_frame'],8*sr)
            covered[w['trusted_start_frame']:w['trusted_stop_frame']]=True
        self.assertTrue(covered[sr:19*sr].all())
    def test_schedule_no_fake_edge_support(self):
        from integration_contract_v40 import Span
        s=ev.schedule([Span(0,96000)],rate=48000,length=96000)
        self.assertGreater(s['windows'][0]['trusted_start_frame'],0)

class PlannerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.bundle=calibration(cls.root)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def setUp(self):
        self.case=tempfile.TemporaryDirectory(dir=self.root);self.r=Path(self.case.name)
        self.source=save(self.r/'source.wav',song(low=.5))
        # Real preparation in chain tests; this direct contract uses a declared
        # snapshot of the same source, not a forged observer-source hash.
        self.snapshot=RenderSnapshot.bind(capture(self.source),capture(self.source),{'case':'direct_unit'})
        self.context=PlanningContext(self.source,self.source,self.snapshot)
    def tearDown(self):self.case.cleanup()
    def planner(self,mode='support'):
        return ap.AutomaticRepairPlanner(self.bundle,FixtureRoles(mode),allow_fixture=True)
    def test_reference_null_not_forced_processing(self):
        p=self.root/'ref1.wav';s=RenderSnapshot.bind(capture(p),capture(p),{'case':'ref'})
        planner=self.planner();out=planner.build(PlanningContext(p,p,s))
        self.assertFalse(any(out['low_cut_db']));self.assertEqual(out['assessment'],'KEEP_SUPPORTED')
    def test_real_source_drives_correction_not_manual_curve(self):
        p=self.planner();out=p.build(self.context);self.assertTrue(any(out['low_cut_db']))
        self.assertTrue(p.observer.calls);self.assertFalse(p.last_report['manual_event_times_used'])
        self.assertTrue(p.last_report['trials']);self.assertGreater(p.last_report['automatically_discovered_events'],0)
    def test_voice_dominant_is_not_cut(self):
        p=self.planner('voice');out=p.build(self.context);self.assertFalse(any(out['low_cut_db']));self.assertEqual(out['assessment'],'ABSTAIN')
    def test_disagreeing_roles_abstain(self):
        p=self.planner('disagree');out=p.build(self.context);self.assertFalse(any(out['low_cut_db']));self.assertEqual(out['assessment'],'ABSTAIN')
    def test_no_energy_role_not_high_confidence(self):
        p=self.planner('zero');out=p.build(self.context);self.assertFalse(any(out['low_cut_db']))
    def test_invalid_roles_fail(self):
        with self.assertRaises(ValueError):self.planner('nan').build(self.context)
    def test_bad_bundle_stops_preflight(self):
        import copy
        bundle=copy.deepcopy(self.bundle);bundle['broad']['caps']['hit_q90_db']+=10
        with self.assertRaises(ValueError):ap.AutomaticRepairPlanner(bundle,FixtureRoles(),allow_fixture=True).preflight()
    def test_fixture_not_production_default(self):
        with self.assertRaises(ValueError):ap.AutomaticRepairPlanner(self.bundle,FixtureRoles()).preflight()
    def test_empty_and_wrong_role_reviews_not_calibrated(self):
        for quality in ('','negative','unreviewed'):
            spec=dict(path=self.root/'ref0.wav',role='bass',quality=quality)
            with self.assertRaises(ValueError):ap.make_calibration([spec]*4)
    def test_duplicate_pcm_rejected(self):
        spec=dict(path=self.root/'ref0.wav',role='bass',quality='positive')
        with self.assertRaises(ValueError):ap.make_calibration([spec]*4)
    def test_saved_plan_rebuilds(self):
        p=self.planner();plan=p.build(self.context);coord.validate_plan(json.loads(json.dumps(plan)),self.snapshot)
    def test_source_identity_stays_separate(self):
        x,sr=sf.read(self.source,always_2d=True);physical=save(self.r/'physical.wav',x*.5)
        snap=RenderSnapshot.bind(capture(self.source),capture(physical),{'case':'gain_half'})
        p=self.planner();out=p.build(PlanningContext(self.source,physical,snap))
        self.assertNotEqual(out['source_sha256'],out['physical_sha256']);self.assertTrue(any(out['low_cut_db']))
    def test_sub_and_narrow_ops_not_faked(self):
        p=self.planner();out=p.build(self.context);self.assertEqual(out['sub_synthesis'],'NOT_CONNECTED')
        self.assertTrue(all(v['branch']=='low' for v in out['proposals']))
    def test_never_mutates_original(self):
        old=capture(self.source);self.planner().build(self.context);self.assertEqual(capture(self.source),old)
    def test_candidate_temporaries_cleaned(self):
        self.planner().build(self.context);self.assertFalse(list(self.r.glob('plan41_*')))

if __name__=='__main__':unittest.main(verbosity=2)
