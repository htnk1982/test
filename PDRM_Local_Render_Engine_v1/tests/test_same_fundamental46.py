from pathlib import Path
import tempfile,unittest,json
import numpy as np
import soundfile as sf
import event_groove_v37 as event
import physical_add_bridge_v46 as bridge
import joint_lowend_v46 as joint
import joint_lowend_v42 as reduction
import lowend_coordinator_v40 as broad
import integrated_finish_v40 as finish
from integrated_finish_v40 import PlanningContext
from integration_contract_v40 import capture,RenderSnapshot
from target_settings import Targets


def waveform(sr=48000,seconds=2.2,fund=.004):
    t=np.arange(round(sr*seconds))/sr;gate=((t>=.4)&(t<1.6)).astype(float)
    # smooth, explicit bass event with a present-but-underweighted 55 Hz fundamental
    edge=np.minimum(np.clip((t-.4)/.04,0,1),np.clip((1.6-t)/.06,0,1));edge=edge*edge*(3-2*edge)*gate
    bass=edge*(fund*np.cos(2*np.pi*55*t)+.08*np.cos(2*np.pi*110*t)+.04*np.cos(2*np.pi*165*t))
    other=.015*np.sin(2*np.pi*1800*t)
    return np.column_stack((bass+other,bass+.8*other))


def observer(digest,mode='bass'):
    t=np.arange(0,2.2,.01);n=len(t);p=np.ones((2,n,5))*1e-7;p[:,:,0]=.03
    p[:,:,1]=.001;p[:,:,2]=.025;p[:,:,3]=.001;p[:,:,4]=.001
    pitch=np.full((2,n),55.);period=np.full((2,n),.99)
    if mode=='wrong_pitch':pitch[:]=110.
    if mode=='rest':p[:,:,2]=1e-12;p[:,:,3]=.025
    if mode=='gap':period[:,95:100]=.1
    arrays=dict(time=t,low_power=p.copy(),body_power=p.copy(),focus_power=p.copy(),bass_f0_hz=pitch,bass_periodicity=period)
    meta=dict(version='role-observer-0.2.0',source_sha256=digest,source_order=['mix','drums','bass','other','vocals'],start_seconds=0.,end_seconds=2.2)
    return arrays,meta


def keep_reduction(snapshot,low=0.):
    cuts=[]
    if low:
        n=snapshot.source.frames;sr=snapshot.source.samplerate
        cuts=[broad.CutProposal('low','low',(0,round(.3*sr),n-round(.3*sr),n),(0.,low,low,0.),'fixture')]
    bp=broad.compile_plan(snapshot,cuts,planner_id='broad46',calibration_sha256='b'*64,
        assessment='CANDIDATE' if cuts else 'KEEP_SUPPORTED',evidence_scope='engineering_fixture')
    return reduction.compile_plan(snapshot,bp,[],planner_id='reduction46',calibration_sha256='c'*64,
        evidence_scope='engineering_fixture',assessment='CANDIDATE' if cuts else 'KEEP_SUPPORTED')


class BridgeAndRenderer(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name);self.source=self.r/'source.wav';sf.write(self.source,waveform(),48000,subtype='DOUBLE')
        self.snap=RenderSnapshot.bind(capture(self.source),capture(self.source),{'fixture':'same'})
        self.context=PlanningContext(self.source,self.source,self.snap);self.e=dict(start=.4,end=1.6,source_f0_hz=55.,target_hz=55.)
    def tearDown(self):self.tmp.cleanup()
    def confirm(self,mode='bass',event_override=None):return bridge.confirm(self.context,event_override or self.e,*observer(self.snap.source.file_sha256,mode))
    def joint_plan(self,adds=(),low=0.):
        red=keep_reduction(self.snap,low);state='CANDIDATE' if adds or low else 'KEEP_SUPPORTED'
        return joint.compile_plan(self.snap,red,adds,planner_id='joint46',calibration_sha256='d'*64,evidence_scope='engineering_fixture',assessment=state)
    def test_positive_same_fundamental_measured_on_physical(self):
        p,r=self.confirm();self.assertIsNotNone(p);self.assertEqual(r['status'],'PHYSICALLY_CONFIRMED_SAME_FUNDAMENTAL');self.assertLessEqual(p.amplitude,bridge.MAX_ADD_PEAK);self.assertNotEqual(r['source_sha256'],'' )
    def test_octave_down_rejected(self):
        p,r=self.confirm(event_override=dict(self.e,source_f0_hz=110.));self.assertIsNone(p);self.assertIn('DENY_NEW_OCTAVE',r['source_decision']['reason_codes'])
    def test_wrong_pitch_observer_rejected(self):
        p,r=self.confirm('wrong_pitch');self.assertIsNone(p);self.assertIn('ABSTAIN_LOCAL_ROLE_OR_PITCH',r['source_decision']['reason_codes'])
    def test_rest_role_rejected(self):
        p,r=self.confirm('rest');self.assertIsNone(p)
    def test_already_sufficient_is_zero(self):
        sf.write(self.source,waveform(fund=.05),48000,subtype='DOUBLE');self.snap=RenderSnapshot.bind(capture(self.source),capture(self.source),{'fixture':'same'});self.context=PlanningContext(self.source,self.source,self.snap)
        p,r=self.confirm();self.assertIsNone(p);self.assertEqual(r['status'],'KEEP_ALREADY_SUFFICIENT')
    def test_observer_gap_remains_zero_in_envelope(self):
        p,r=self.confirm('gap');self.assertIsNotNone(p);frames=np.array(p.source_frames);values=np.array(p.envelope);t=frames/self.snap.source.samplerate
        self.assertLess(np.max(values[(t>=.95)&(t<1.0)]),1e-8)
    def test_add_and_low_cut_conflict_rejected(self):
        p,_=self.confirm()
        with self.assertRaisesRegex(ValueError,'Conflicting low-cut'):self.joint_plan([p],low=.5)
    def test_addition_render_only_inside_event(self):
        p,_=self.confirm();plan=self.joint_plan([p]);dest=self.r/'out.wav';joint.render(self.source,self.source,dest,self.snap,plan)
        y=sf.read(dest,dtype='float64',always_2d=True)[0];x=sf.read(self.source,dtype='float64',always_2d=True)[0];t=np.arange(len(x))/48000
        self.assertGreater(np.max(abs(y-x)),1e-5);np.testing.assert_array_equal(y[(t<.4)|(t>=1.6)],x[(t<.4)|(t>=1.6)])
    def test_no_addition_delegates_v42_exactly(self):
        plan=self.joint_plan();a=self.r/'a.wav';b=self.r/'b.wav';joint.render(self.source,self.source,a,self.snap,plan);reduction.render(self.source,self.source,b,self.snap,plan['reduction_plan'])
        self.assertEqual(a.read_bytes(),b.read_bytes())
    def test_json_roundtrip(self):
        p,_=self.confirm();plan=json.loads(json.dumps(self.joint_plan([p])));joint.validate_plan(plan,self.snap)
    def test_source_not_modified(self):
        p,_=self.confirm();old=capture(self.source);joint.render(self.source,self.source,self.r/'out.wav',self.snap,self.joint_plan([p]));self.assertEqual(capture(self.source),old)
    def test_overlapping_additions_rejected(self):
        p,_=self.confirm();q=bridge.SameFundamentalAdd('other',p.target_hz,p.source_frames,p.envelope,p.amplitude,p.phase_radians,'f'*64,p.physical_confirmation_sha256)
        with self.assertRaisesRegex(ValueError,'Overlapping'):self.joint_plan([p,q])


class ChainPlanner:
    def __init__(self):self.last_report=None
    def identity(self):return dict(planner_id='same-f0-chain46',calibration_sha256='e'*64,evidence_scope='engineering_fixture')
    def preflight(self):pass
    def build(self,context,progress=None):
        digest=context.snapshot.source.file_sha256;e=dict(start=.4,end=1.6,source_f0_hz=55.,target_hz=55.)
        p,r=bridge.confirm(context,e,*observer(digest))
        bp=broad.compile_plan(context.snapshot,[],planner_id='broad46',calibration_sha256='b'*64,assessment='KEEP_SUPPORTED',evidence_scope='engineering_fixture')
        red=reduction.compile_plan(context.snapshot,bp,[],planner_id='reduction46',calibration_sha256='c'*64,evidence_scope='engineering_fixture',assessment='KEEP_SUPPORTED')
        adds=[] if p is None else [p];state='CANDIDATE' if adds else 'ABSTAIN'
        self.last_report=dict(addition=r,manual_event_fixture=True,stem_samples_in_output=False)
        return joint.compile_plan(context.snapshot,red,adds,planner_id=self.identity()['planner_id'],calibration_sha256=self.identity()['calibration_sha256'],evidence_scope='engineering_fixture',assessment=state,unresolved=() if adds else ('same-fundamental candidate unavailable',))

class FullChain(unittest.TestCase):
    def test_same_fundamental_reaches_wav_mp3_without_legacy_sub(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);inputs=root/'inputs';work=root/'work';inputs.mkdir()
            src=inputs/'source.wav';sf.write(src,waveform(),48000,subtype='DOUBLE');planner=ChainPlanner()
            report,folder=finish.run_lab(src,work,planner,targets=Targets(),enable_lab=True,render_backend='joint-v46')
            self.assertEqual(report['sub_synthesis'],'SAME_FUNDAMENTAL_ONLY_CONNECTED');self.assertFalse(report['old_note_sub_called']);self.assertEqual(report['lowend_report']['same_fundamental_additions'],1)
            self.assertTrue((folder/'MASTER.wav').is_file() and (folder/'LISTEN_320kbps.mp3').is_file());self.assertLessEqual(report['master_metrics']['true_peak_max_dbtp_estimate'],-2)
            self.assertLessEqual(report['codec_metrics']['true_peak_max_dbtp_estimate'],-2);self.assertTrue(report['intermediate_audio_removed'])

if __name__=='__main__':unittest.main(verbosity=2)
