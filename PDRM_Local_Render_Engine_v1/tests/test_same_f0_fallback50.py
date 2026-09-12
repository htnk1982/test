from pathlib import Path
import tempfile,unittest
import numpy as np
import soundfile as sf
import event_groove_v37 as legacy
import same_f0_permission_v50 as permission
import physical_add_bridge_v50 as bridge
import automatic_joint_v48 as v48
from integrated_finish_v40 import PlanningContext
from integration_contract_v40 import capture,RenderSnapshot


def gate(t,a,b,fade=.06):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)

def audio(kind,sr=48000,seconds=7.):
    t=np.arange(round(sr*seconds))/sr;g=gate(t,2.15,5.0);bed=.02*np.sin(2*np.pi*1700*t)+.012*np.sin(2*np.pi*2300*t)
    if kind=='weak':x=g*(.004*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    elif kind=='voice':
        amps=(.018,.052,.047,.038,.030,.025,.020,.016);x=g*sum(a*np.sin(2*np.pi*55*(i+1)*t+.17*i) for i,a in enumerate(amps))*(1+.22*np.sin(2*np.pi*4.6*t))
    elif kind=='kick':
        p=(t-.08)%0.5;x=.20*np.sin(2*np.pi*58*t)*np.exp(-38*p)
    elif kind=='110':x=g*(.08*np.sin(2*np.pi*110*t)+.035*np.sin(2*np.pi*220*t))
    else:raise ValueError(kind)
    return np.column_stack((x+bed,x+.88*bed))

def observer(source_digest,kind='weak'):
    t=1.8+np.arange(350)*.01;n=len(t);p=np.full((2,n,5),1e-9);p[:,:,0]=.03;f=np.full((2,n),55.);q=np.full((2,n),.99)
    if kind=='weak':
        # Reproduce deployable-observer ambiguity: moderate drum leakage and a
        # bass/other swap between contexts. No single semantic stem is stable.
        p[:,:,1]=.012
        p[0,:,2]=.022;p[0,:,3]=.005;p[1,:,2]=.005;p[1,:,3]=.022
    elif kind=='voice':
        p[:,:,2]=.027;p[:,:,3]=.0002
    elif kind=='kick':
        p[:,:,1]=.027;p[:,:,2]=.0002;p[:,:,3]=.0002;f[:]=0;q[:]=0
    meta=dict(version='role-observer-0.2.0',source_sha256=source_digest,source_order=['mix','drums','bass','other','vocals'],start_seconds=1.8,end_seconds=5.3)
    return dict(time=t,low_power=p,body_power=p.copy(),focus_power=p.copy(),bass_f0_hz=f,bass_periodicity=q),meta

def event(f0=55,target=55):return dict(start=2.15,end=5.0,source_f0_hz=float(f0),target_hz=float(target))
def source_event(pitch=55):return dict(start_frame=round(2.15*48000),stop_frame=round(5*48000),start_seconds=2.15,end_seconds=5.0,pitch_status='PERIODIC_CANDIDATE',pitch_hz=float(pitch))

class SameF0Fallback(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def write(self,kind):
        p=self.root/(kind+'.wav');sf.write(p,audio(kind),48000,subtype='DOUBLE');return p
    def evidence(self,kind,pitch=55):
        p=self.write(kind);proof=v48._present_fundamental(p,source_event(pitch));shape=bridge.source_shape(p,2.15,5.0);arr,meta=observer(capture(p).file_sha256,'kick' if kind=='kick' else ('voice' if kind=='voice' else 'weak'));return p,proof,shape,arr,meta
    def test_weak_existing_f0_rescues_only_local_role_ambiguity(self):
        p,proof,shape,arr,meta=self.evidence('weak');source_sha=capture(p).file_sha256
        old=legacy.permit(event(),arr,meta,source_sha);self.assertFalse(old['allowed'],old);self.assertEqual(old['reason_codes'],['ABSTAIN_LOCAL_ROLE_OR_PITCH'])
        d=permission.permit(event(),arr,meta,source_sha,proof,shape)
        self.assertTrue(d['allowed'],d);self.assertEqual(d['permission_path'],'EXISTING_WEAK_F0_FALLBACK');self.assertEqual(d['envelope_role_indices'],[2,3]);self.assertLess(d['fallback_drum_share_q80'],.5)
    def test_role_and_pitch_are_independent_event_evidence(self):
        p,proof,shape,arr,meta=self.evidence('weak');source_sha=capture(p).file_sha256
        t=np.asarray(arr['time']);keep=np.flatnonzero((t>=2.25)&(t<4.90));k=max(1,len(keep)//5)
        # Pitch evidence fails on the first fifth; role evidence fails on a disjoint
        # final fifth. Each event-level gate still has >=75% support while their
        # same-frame intersection is intentionally below 75%.
        arr['bass_f0_hz'][:,keep[:k]]=0.;arr['bass_periodicity'][:,keep[:k]]=0.
        arr['low_power'][:,keep[-k:],1]=.20;arr['body_power'][:,keep[-k:],1]=.20
        d=permission.permit(event(),arr,meta,source_sha,proof,shape)
        self.assertTrue(d['allowed'],d)
        self.assertGreaterEqual(d['fallback_role_supported_fraction'],.75)
        self.assertGreaterEqual(d['fallback_pitch_supported_fraction'],.75)
        self.assertLess(d['fallback_joint_supported_fraction'],.75)
        self.assertGreaterEqual(d['fallback_render_supported_fraction'],.75)
    def test_deep_voice_legacy_allow_is_overridden_by_source_veto(self):
        p,proof,shape,arr,meta=self.evidence('voice');source_sha=capture(p).file_sha256
        old=legacy.permit(event(),arr,meta,source_sha);self.assertTrue(old['allowed'],old)
        d=permission.permit(event(),arr,meta,source_sha,proof,shape)
        self.assertFalse(d['allowed'],d);self.assertEqual(d['permission_path'],'STRICT_ROLE_SOURCE_VETO')
        self.assertTrue(any(x in d['reason_codes'] for x in ('ABSTAIN_F0_NOT_WEAK_ENOUGH_FOR_REPAIR','ABSTAIN_SOURCE_TOO_HARMONICALLY_BRIGHT_FOR_SUB_REPAIR')),d)
    def test_kick_denied_by_drum_pitch_veto(self):
        p,proof,shape,arr,meta=self.evidence('kick',58);proof=proof or dict(method='ORIGINAL_COMPONENT_PRESENT;_HARMONIC_SUPPORTED;_NO_MISSING_FUNDAMENTAL',fundamental_to_upper_ratio=.05)
        d=permission.permit(event(58,58),arr,meta,capture(p).file_sha256,proof,shape);self.assertFalse(d['allowed']);self.assertIn('ABSTAIN_FALLBACK_ROLE_OR_PITCH',d['reason_codes'])
    def test_octave_denial_is_never_rescued(self):
        p,proof,shape,arr,meta=self.evidence('110',110);proof=proof or dict(method='ORIGINAL_COMPONENT_PRESENT;_HARMONIC_SUPPORTED;_NO_MISSING_FUNDAMENTAL',fundamental_to_upper_ratio=.05)
        d=permission.permit(event(110,55),arr,meta,capture(p).file_sha256,proof,shape);self.assertFalse(d['allowed']);self.assertIn('DENY_NEW_OCTAVE',d['reason_codes']);self.assertEqual(d['permission_path'],'LEGACY_DENIAL_PRESERVED')
    def test_physical_bridge_adds_weak_f0_from_original_two_mix_only(self):
        p,proof,shape,arr,meta=self.evidence('weak');snap=RenderSnapshot.bind(capture(p),capture(p),{'fixture':'fallback50'});ctx=PlanningContext(p,p,snap)
        proposal,ev=bridge.confirm(ctx,event(),arr,meta,proof)
        self.assertIsNotNone(proposal,ev);self.assertEqual(ev['source_decision']['permission_path'],'EXISTING_WEAK_F0_FALLBACK');self.assertEqual(ev['envelope_role_indices'],[2,3]);self.assertFalse(ev['stem_samples_in_output'])

if __name__=='__main__':unittest.main(verbosity=2)
