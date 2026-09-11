"""Synthetic contracts for automatic_joint_v48; no private audio.

Fixture observer roles are explicit test evidence only. Event times, pitch and
broad repair spans are discovered by production source/physical analysis code;
no event timestamp is passed to the planner.
"""
from pathlib import Path
import copy,tempfile,unittest,json
import numpy as np
import soundfile as sf
import automatic_joint_v48 as aj
import automatic_lowend_v41 as broad41
import joint_lowend_v46 as joint
import source_events_v41 as events
import integrated_finish_v40 as finish
from integrated_finish_v40 import PlanningContext
from integration_contract_v40 import capture,RenderSnapshot,digest
from target_settings import Targets


def gate(t,a,b,fade=.04):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)


def audio(kind,sr=48000,seconds=7.):
    t=np.arange(round(sr*seconds))/sr;y=.04*np.sin(2*np.pi*1700*t)+.025*np.sin(2*np.pi*2300*t);low=np.zeros_like(t)
    if kind in ('weak','heavyweak'):
        g=gate(t,2.1,4.2);scale=1. if kind=='weak' else 5.
        low=g*scale*(.004*np.cos(2*np.pi*55*t)+.08*np.cos(2*np.pi*110*t)+.04*np.cos(2*np.pi*165*t))
    elif kind=='kick':
        p=(t-.08)%0.5;low=.20*np.sin(2*np.pi*58*t)*np.exp(-38*p)
    elif kind=='vocal':
        g=gate(t,2.1,4.3);low=g*(.055*np.sin(2*np.pi*165*t)+.040*np.sin(2*np.pi*330*t)+.025*np.sin(2*np.pi*495*t))*(1+.15*np.sin(2*np.pi*4.7*t))
    elif kind=='rest':
        g=gate(t,1.5,2.6)+gate(t,4.1,5.2);low=g*(.006*np.cos(2*np.pi*55*t)+.085*np.cos(2*np.pi*110*t)+.04*np.cos(2*np.pi*165*t))
    elif kind=='110':
        g=gate(t,2.0,4.0);low=g*(.08*np.sin(2*np.pi*110*t)+.035*np.sin(2*np.pi*220*t))
    elif kind=='reference':
        for a,d,f in ((.7,.35,55.),(1.7,.45,73.4),(3.0,.55,110.),(4.8,.30,55.)):
            g=gate(t,a,a+d);low+=.03*g*(np.sin(2*np.pi*f*t)+.45*np.sin(4*np.pi*f*t)+.2*np.sin(6*np.pi*f*t))
    else:raise ValueError(kind)
    return np.column_stack((y+low,.94*y+low))


def save(path,x,sr=48000):sf.write(path,x,sr,subtype='DOUBLE');return path


class FixtureObserver:
    def __init__(self,mode,identity_override=None):self.mode=mode;self.calls=[];self.override=identity_override or {}
    def identity(self):
        x=dict(provider=aj.SYNTHETIC_PROVIDER,evidence_scope='engineering_fixture',mode=self.mode,fixture_sha256='a'*64)
        x.update(self.override);return x
    def preflight(self):pass
    def observe(self,source,start,end,progress=None):
        ident=capture(source);t=start+np.arange(round((end-start)*100))*.01;n=len(t);p=np.full((2,n,5),1e-9);p[:,:,0]=.03
        f=np.zeros((2,n));q=np.zeros((2,n))
        if self.mode in ('weak','heavyweak'):
            p[:,:,2]=.027;f[:]=55.;q[:]=.995
        elif self.mode=='kick':
            p[:,:,1]=.027;f[:]=58.;q[:]=.95
        elif self.mode=='vocal':
            p[:,:,3]=.023;p[:,:,4]=.004;f[:]=55.;q[:]=.99
        elif self.mode=='rest':
            active=((t>=1.5)&(t<2.6))|((t>=4.1)&(t<5.2));p[:,:,2]=np.where(active,.027,1e-10)[None,:];f[:]=np.where(active,55.,0);q[:]=np.where(active,.995,0)
        elif self.mode=='110':
            p[:,:,2]=.027;f[:]=110.;q[:]=.995
        else:raise ValueError(self.mode)
        body=p.copy();focus=p.copy();self.calls.append((start,end))
        return dict(time=t,low_power=p,body_power=body,focus_power=focus,bass_f0_hz=f,bass_periodicity=q),dict(
            version='role-observer-0.2.0',provider=aj.SYNTHETIC_PROVIDER,source_sha256=ident.file_sha256,source_frames=ident.frames,
            source_samplerate=ident.samplerate,source_order=['mix','drums','bass','other','vocals'],start_seconds=start,end_seconds=end)


def calibration(root):
    specs=[]
    for i in range(4):
        x=audio('reference');x[:,0]*=(1+i*.003);p=save(root/f'ref{i}.wav',x)
        specs.append(dict(path=p,role='bass',quality='positive'))
    return broad41.make_calibration(specs)


class AutomaticJointContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);cls.bundle=calibration(cls.root)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def case(self,kind):
        r=Path(tempfile.mkdtemp(dir=self.root));src=save(r/(kind+'.wav'),audio(kind));snap=RenderSnapshot.bind(capture(src),capture(src),{'case':kind});return r,src,snap,PlanningContext(src,src,snap)
    def planner(self,mode,override=None):return aj.AutomaticJointPlanner(self.bundle,FixtureObserver(mode,override),allow_fixture=True)
    def test_weak_present_fundamental_is_discovered_and_added(self):
        r,src,snap,ctx=self.case('weak');p=self.planner('weak');plan=p.build(ctx)
        self.assertGreater(len(plan['additions']),0);self.assertFalse(p.last_report['manual_event_times_used']);self.assertGreater(p.last_report['automatically_discovered_events'],0)
        self.assertTrue(any(x.get('planner_resolution')=='ADD_ACCEPTED' for x in p.last_report['addition_records']))
        joint.validate_plan(json.loads(json.dumps(plan)),snap)
    def test_kick_may_reduce_but_never_authorizes_bass_add(self):
        r,src,snap,ctx=self.case('kick');p=self.planner('kick');plan=p.build(ctx)
        self.assertEqual(plan['additions'],[]);self.assertFalse(any(x.get('planner_resolution')=='ADD_ACCEPTED' for x in p.last_report['addition_records']))
    def test_vocal_like_low_is_not_bass_action(self):
        r,src,snap,ctx=self.case('vocal');p=self.planner('vocal');plan=p.build(ctx)
        self.assertEqual(plan['additions'],[]);self.assertFalse(any(plan['reduction_plan']['broad_plan']['low_cut_db']))
    def test_rest_gap_has_no_addition_spanning_gap(self):
        r,src,snap,ctx=self.case('rest');p=self.planner('rest');plan=p.build(ctx)
        self.assertGreaterEqual(len(plan['additions']),1);sr=snap.source.samplerate
        for a in plan['additions']:
            self.assertFalse(a['source_frames'][0]<3.5*sr<a['source_frames'][-1])
    def test_110hz_event_is_not_octave_mapped_to_55(self):
        r,src,snap,ctx=self.case('110');p=self.planner('110');plan=p.build(ctx)
        self.assertEqual(plan['additions'],[]);self.assertEqual(p.last_report['tonal_same_f0_candidates'],0)
    def test_reduction_priority_suppresses_conflicting_add(self):
        r,src,snap,ctx=self.case('heavyweak');p=self.planner('heavyweak');plan=p.build(ctx)
        self.assertTrue(any(plan['reduction_plan']['broad_plan']['low_cut_db']))
        self.assertEqual(plan['additions'],[])
        self.assertTrue(any(x.get('planner_resolution')=='SUPPRESSED_SAME_FUNDAMENTAL_ADD;_BROAD_REDUCTION_PRIORITY' for x in p.last_report['addition_records']))
    def test_fixture_identity_cannot_silently_claim_research(self):
        p=aj.AutomaticJointPlanner(self.bundle,FixtureObserver('weak',{'evidence_scope':'research_observer'}),allow_fixture=True)
        with self.assertRaises(ValueError):p.preflight()
    def test_unknown_observer_is_hard_failure(self):
        p=aj.AutomaticJointPlanner(self.bundle,FixtureObserver('weak',{'provider':'unknown'}),allow_fixture=True)
        with self.assertRaises(ValueError):p.preflight()
    def test_original_never_mutated_and_old_note_sub_absent(self):
        r,src,snap,ctx=self.case('weak');old=capture(src);p=self.planner('weak');plan=p.build(ctx)
        self.assertEqual(capture(src),old);self.assertFalse(p.last_report['old_note_sub_called']);self.assertEqual(p.last_report['sub_synthesis'],'SAME_FUNDAMENTAL_ONLY_CONNECTED')
    def test_candidate_temporaries_are_removed(self):
        r,src,snap,ctx=self.case('heavyweak');self.planner('heavyweak').build(ctx);self.assertFalse(list(r.glob('plan48_*')))
    def test_complete_existing_chain_reaches_wav_and_mp3(self):
        case=Path(tempfile.mkdtemp(dir=self.root));inputs=case/'inputs';inputs.mkdir();src=save(inputs/'weak.wav',audio('weak'));planner=self.planner('weak')
        report,folder=finish.run_lab(src,case/'work',planner,targets=Targets(),enable_lab=True,render_backend='joint-v46')
        self.assertEqual(report['sub_synthesis'],'SAME_FUNDAMENTAL_ONLY_CONNECTED');self.assertFalse(report['old_note_sub_called'])
        self.assertGreaterEqual(report['lowend_report']['same_fundamental_additions'],1);self.assertTrue((folder/'MASTER.wav').is_file());self.assertTrue((folder/'LISTEN_320kbps.mp3').is_file())
        self.assertLessEqual(report['master_metrics']['true_peak_max_dbtp_estimate'],-2);self.assertLessEqual(report['codec_metrics']['true_peak_max_dbtp_estimate'],-2)

if __name__=='__main__':unittest.main(verbosity=2)
