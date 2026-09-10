"""Joint engine tests. Synthetic controls are explicit; no private music."""
from pathlib import Path
from dataclasses import replace
import copy,json,tempfile,unittest
import numpy as np
import soundfile as sf
from scipy import signal
import joint_lowend_v42 as joint
import lowend_coordinator_v40 as broad
from integration_contract_v40 import capture,RenderSnapshot,FrameMap,digest
from integrated_finish_v40 import PlanningContext
from physical_decay_bridge_v42 import confirm_relative_tail
from decay39_fixtures import audio_fixture,audio_atlas,oracle


def broad_plan(snapshot,low=0.,mid=0.):
    sr=snapshot.source.samplerate;n=snapshot.source.frames
    proposals=[]
    for name,d in (('low',low),('lowmid',mid)):
        if d:proposals.append(broad.CutProposal(name,name,(0,round(.2*sr),n-round(.2*sr),n),(0.,d,d,0.),'fixture'))
    return broad.compile_plan(snapshot,proposals,planner_id='fixture',calibration_sha256='c'*64,
        assessment='CANDIDATE' if proposals else 'KEEP_SUPPORTED',evidence_scope='engineering_fixture')


def cut(snapshot,*,ident='tail',center=320.,depth=1.5,start=.9,stop=3.4):
    sr=snapshot.source.samplerate
    return joint.NarrowCut(ident,center,tuple(round(t*sr) for t in (start,start+.3,stop-.3,stop)),
        (0.,depth,depth,0.),'synthetic_narrow','e'*64,snapshot.physical.file_sha256)


def plan(snapshot,cuts=(),low=0.,mid=0.,assessment=None,unresolved=()):
    bp=broad_plan(snapshot,low,mid)
    state=assessment or ('CANDIDATE' if cuts or low or mid else 'KEEP_SUPPORTED')
    return joint.compile_plan(snapshot,bp,cuts,planner_id='joint_fixture',calibration_sha256='d'*64,
        assessment=state,evidence_scope='engineering_fixture',unresolved=unresolved)


class JointContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sr=32000
        t=np.arange(self.sr*4)/self.sr
        s=.10*np.cos(2*np.pi*320*t)+.05*np.cos(2*np.pi*80*t)+.03*np.cos(2*np.pi*2300*t)
        self.x=np.column_stack((s,s*.95));self.x[:500]=0
        self.source=self.root/'source.wav';sf.write(self.source,self.x,self.sr,subtype='DOUBLE')
        self.snap=RenderSnapshot.bind(capture(self.source),capture(self.source),{'fixture':'same'})
    def tearDown(self):self.tmp.cleanup()
    def run_render(self,p,name='out',chunk=None):
        dest=self.root/(name+'.wav');r=joint.render(self.source,self.source,dest,self.snap,p,chunk_frames=chunk)
        return sf.read(dest,dtype='float64',always_2d=True)[0],r
    def test_null_exact_file_bytes(self):
        y,r=self.run_render(plan(self.snap));self.assertTrue(r['broad_delegate_exact']);np.testing.assert_array_equal(y,self.x)
        self.assertEqual(self.source.read_bytes(),(self.root/'out.wav').read_bytes())
    def test_broad_only_matches_existing_renderer(self):
        p=plan(self.snap,low=1.2,mid=.7);y,r=self.run_render(p)
        dest=self.root/'old.wav';broad.render(self.source,self.source,dest,self.snap,p['broad_plan'])
        np.testing.assert_array_equal(y,sf.read(dest,always_2d=True)[0])
    def test_narrow_changes_real_samples(self):
        y,r=self.run_render(plan(self.snap,[cut(self.snap)]));self.assertGreater(np.max(abs(y-self.x)),1e-4)
        self.assertEqual(r['narrow_operations'],1)
    def test_two_identical_requests_do_not_double_cut(self):
        p1=plan(self.snap,[cut(self.snap)]);p2=plan(self.snap,[cut(self.snap),cut(self.snap,ident='tail2')])
        a,_=self.run_render(p1,'one');b,_=self.run_render(p2,'two');np.testing.assert_allclose(a,b,rtol=0,atol=2e-12)
    def test_plan_order_independent(self):
        a=cut(self.snap);b=cut(self.snap,ident='b',center=360.)
        self.assertEqual(plan(self.snap,[a,b]),plan(self.snap,[b,a]))
    def test_duplicate_id_rejected(self):
        a=cut(self.snap)
        with self.assertRaises(ValueError):plan(self.snap,[a,a])
    def test_seal_rebuilds_from_json(self):
        p=json.loads(json.dumps(plan(self.snap,[cut(self.snap)],mid=.5)));joint.validate_plan(p,self.snap)
    def test_resealed_geometry_edit_rejected(self):
        p=plan(self.snap,[cut(self.snap)]);p['narrow_cuts'][0]['physical_confirmation_sha256']='a'*64
        p.pop('sha256');p['sha256']=digest(p)
        with self.assertRaises(ValueError):joint.validate_plan(p,self.snap)
    def test_mask_sum_budget(self):
        n,hop,w,f,A,B=joint.geometry(self.sr);shape=np.ones((2,len(f)))
        h,split,q=joint.frame_response(2.,1.5,[1.5,1.5],shape,A,B)
        goal=h+split.sum(axis=0)
        self.assertGreaterEqual(goal.min(),10**(-2.001/20))
        self.assertLessEqual(q['max_joint_db'],2.001)
    def test_broad_already_meets_requested_frequency(self):
        A=np.ones(8);B=np.ones(8)
        h,d,q=joint.frame_response(2.,0.,[1.5],np.ones((1,8)),A,B)
        np.testing.assert_array_equal(d,0.)
    def test_frame_response_uses_max_not_sum(self):
        A=np.zeros(8);B=np.zeros(8)
        h,d,q=joint.frame_response(0.,0.,[1.5,1.5],np.ones((2,8)),A,B)
        np.testing.assert_allclose(h+d.sum(axis=0),10**(-1.5/20),atol=1e-14)
    def test_exact_head_and_outside_preservation(self):
        y,_=self.run_render(plan(self.snap,[cut(self.snap)]));t=np.arange(len(y))/self.sr
        np.testing.assert_array_equal(y[(t<=.9)|(t>=3.4)],self.x[(t<=.9)|(t>=3.4)])
    def test_other_operation_cannot_authorize_this_band_outside_event(self):
        a=cut(self.snap,start=.9,stop=2.);b=cut(self.snap,ident='later',center=500.,start=2.3,stop=3.4)
        p=plan(self.snap,[a,b]);y,_=self.run_render(p)
        t=np.arange(len(y))/self.sr;quiet=(t>=2)&(t<=2.3)
        np.testing.assert_array_equal(y[quiet],self.x[quiet])
    def test_internal_unsupported_gap(self):
        a=replace(cut(self.snap),source_frames=tuple(round(v*self.sr) for v in (.9,1.2,1.8,2.1,2.5,3.4)),depth_db=(0.,1.5,0.,0.,1.5,0.))
        y,_=self.run_render(plan(self.snap,[a]));t=np.arange(len(y))/self.sr
        np.testing.assert_array_equal(y[(t>=1.8)&(t<=2.1)],self.x[(t>=1.8)&(t<=2.1)])
    def test_partition_independent(self):
        p=plan(self.snap,[cut(self.snap),cut(self.snap,ident='later',center=500.,start=2.3,stop=3.4)],mid=.6)
        a,_=self.run_render(p,'one',self.sr);b,_=self.run_render(p,'two',2*self.sr)
        np.testing.assert_allclose(a,b,rtol=0,atol=2e-12)
    def test_highband_residual_small(self):
        y,_=self.run_render(plan(self.snap,[cut(self.snap)]));d=y-self.x
        high=signal.sosfilt(signal.butter(6,1500,btype='highpass',fs=self.sr,output='sos'),d,axis=0)
        ratio=20*np.log10(max(np.sqrt(np.mean(high*high)),1e-15)/np.sqrt(np.mean(self.x*self.x)))
        self.assertLess(ratio,-60.)
    def test_stereo_relationship_and_silence(self):
        y,_=self.run_render(plan(self.snap,[cut(self.snap)]));np.testing.assert_allclose(y[:,1],.95*y[:,0],rtol=0,atol=2e-13)
        np.testing.assert_array_equal(y[:500],0)
    def test_source_not_modified(self):
        h=capture(self.source);self.run_render(plan(self.snap,[cut(self.snap)]));self.assertEqual(capture(self.source),h)
    def test_existing_output_not_overwritten(self):
        dest=self.root/'out.wav';dest.write_bytes(b'owned elsewhere')
        with self.assertRaises(FileExistsError):self.run_render(plan(self.snap,[cut(self.snap)]))
        self.assertEqual(dest.read_bytes(),b'owned elsewhere')
    def test_existing_partial_preserved(self):
        dest=self.root/'out.wav.partial.wav';dest.write_bytes(b'foreign')
        with self.assertRaises(FileExistsError):self.run_render(plan(self.snap,[cut(self.snap)]))
        self.assertEqual(dest.read_bytes(),b'foreign')
    def test_cancel_cleans_new_partial(self):
        class Cancel:
            def set(self,*a):raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError):joint.render(self.source,self.source,self.root/'out.wav',self.snap,plan(self.snap,[cut(self.snap)]),progress=Cancel())
        self.assertFalse((self.root/'out.wav.partial.wav').exists());self.assertFalse((self.root/'out.wav').exists())
    def test_wrong_confirmation_rejected(self):
        with self.assertRaises(ValueError):plan(self.snap,[replace(cut(self.snap),physical_confirmation_sha256='f'*64)])
    def test_bad_frequencies(self):
        for hz in (55.,1000.,float('nan'),True):
            with self.assertRaises(ValueError):plan(self.snap,[replace(cut(self.snap),center_hz=hz)])
    def test_bad_depths(self):
        for d in (-1.,2.,float('nan'),True):
            with self.assertRaises(ValueError):plan(self.snap,[replace(cut(self.snap),depth_db=(0.,d,d,0.))])
    def test_undeclared_clock(self):
        with self.assertRaises(ValueError):plan(self.snap,[replace(cut(self.snap),source_frames=(0.,1.,2.,3.))])
    def test_abstention_not_promoted(self):
        with self.assertRaises(ValueError):plan(self.snap,unresolved=('missing role',))
    def test_partial_required_with_unresolved_and_edit(self):
        with self.assertRaises(ValueError):plan(self.snap,[cut(self.snap)],unresolved=('missing role',))
        p=plan(self.snap,[cut(self.snap)],assessment='PARTIAL',unresolved=('missing role',));self.assertEqual(p['assessment'],'PARTIAL')
    def test_nonfinite_not_hidden_in_noop(self):
        p=plan(self.snap);self.x[1000]=np.nan;sf.write(self.source,self.x,self.sr,subtype='DOUBLE')
        with self.assertRaises(ValueError):self.run_render(p)
    def test_excessive_overlap_rejected(self):
        with self.assertRaises(ValueError):plan(self.snap,[cut(self.snap,ident=str(i)) for i in range(17)])
    def test_44k_to48k_projection(self):
        src=self.root/'44.wav';out=self.root/'48.wav';a=signal.resample_poly(self.x,441,320,axis=0);b=signal.resample_poly(a,160,147,axis=0)
        sf.write(src,a,44100,subtype='DOUBLE');sf.write(out,b,48000,subtype='DOUBLE')
        si,pi=capture(src),capture(out);snap=RenderSnapshot.bind(si,pi,{'src':True},FrameMap(si.samplerate,si.frames,pi.samplerate,pi.frames))
        p=plan(snap,[cut(snap)]);dest=self.root/'render.wav';joint.render(src,out,dest,snap,p)
        self.assertEqual(sf.info(dest).frames,pi.frames)


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.atlas=audio_atlas()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sr=32000
        self.clean,self.bad,self.event=audio_fixture(self.sr,phase=.35,decay=.74,fault_db=6.)
        self.source=self.root/'source.wav';self.physical=self.root/'physical.wav'
        sf.write(self.source,self.bad,self.sr,subtype='DOUBLE');sf.write(self.physical,self.bad,self.sr,subtype='DOUBLE')
    def tearDown(self):self.tmp.cleanup()
    def prepare(self):
        snap=RenderSnapshot.bind(capture(self.source),capture(self.physical),{'fixture':'prepared'})
        ctx=PlanningContext(self.source,self.physical,snap)
        support=oracle(np.arange(200)*.02,self.event,snap.source.file_sha256)
        return ctx,support
    def test_source_and_physical_need_produce_candidate(self):
        ctx,support=self.prepare();p,r=confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)
        self.assertIsNotNone(p);self.assertTrue(r['physical_remeasurement_used'])
    def test_source_defect_but_already_repaired_physical_no_cut(self):
        sf.write(self.physical,self.clean,self.sr,subtype='DOUBLE');ctx,support=self.prepare()
        p,r=confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)
        self.assertIsNone(p);self.assertEqual(r['status'],'KEEP_PHYSICAL_RELATIVE_NEED_CLEARED')
    def test_constant_physical_gain_not_a_new_need(self):
        ctx,support=self.prepare();a,_=confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)
        sf.write(self.physical,self.bad*.5,self.sr,subtype='DOUBLE');ctx,support=self.prepare()
        b,r=confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)
        np.testing.assert_allclose(a.depth_db,b.depth_db,atol=1e-8,rtol=0)
        self.assertNotEqual(r['source_sha256'],r['physical_sha256']);self.assertFalse(r['source_observation_hash_substituted'])
    def test_test_evidence_denied_by_default(self):
        ctx,support=self.prepare()
        with self.assertRaises(ValueError):confirm_relative_tail(ctx,self.event,self.atlas,support)
    def test_foreign_observer_rejected(self):
        ctx,support=self.prepare();support['source_sha256']='a'*64
        with self.assertRaises(ValueError):confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)
    def test_missing_observer_abstains(self):
        ctx,_=self.prepare();p,r=confirm_relative_tail(ctx,self.event,self.atlas,None)
        self.assertIsNone(p);self.assertIn('ABSTAIN',r['status'])
    def test_bridge_reaches_joint_renderer(self):
        ctx,support=self.prepare();p,r=confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)
        jp=plan(ctx.snapshot,[p]);dest=self.root/'processed.wav'
        joint.render(self.source,self.physical,dest,ctx.snapshot,jp)
        y=sf.read(dest,always_2d=True)[0];before=np.sum((self.bad-self.clean)**2);after=np.sum((y-self.clean)**2)
        self.assertLess(after,before);t=np.arange(len(y))/self.sr
        np.testing.assert_array_equal(y[t<=1.06],self.bad[t<=1.06])
    def test_no_stale_snapshot_acceptance(self):
        ctx,support=self.prepare();sf.write(self.physical,self.clean,self.sr,subtype='DOUBLE')
        with self.assertRaises(ValueError):confirm_relative_tail(ctx,self.event,self.atlas,support,allow_test_evidence=True)

if __name__=='__main__':unittest.main(verbosity=2)
