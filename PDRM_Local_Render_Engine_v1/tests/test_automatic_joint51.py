"""Contracts for automatic_joint_v51 observer pruning; synthetic audio only."""
from pathlib import Path
from unittest import mock
import json,tempfile,unittest
import numpy as np
import soundfile as sf

import automatic_joint_v50 as v50
import automatic_joint_v51 as v51
from integrated_finish_v40 import PlanningContext
from integration_contract_v40 import capture,RenderSnapshot


def gate(t,a,b,fade=.05):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)


def audio(kind,sr=48000,seconds=7.):
    t=np.arange(round(sr*seconds))/sr;bed=.04*np.sin(2*np.pi*1700*t)+.024*np.sin(2*np.pi*2300*t);g=gate(t,2.1,4.4)
    if kind=='weak':low=g*(.004*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    elif kind=='strongfund':low=g*(.040*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    elif kind=='110':low=g*(.080*np.cos(2*np.pi*110*t)+.035*np.cos(2*np.pi*220*t))
    elif kind=='reference':
        low=np.zeros_like(t)
        for a,b,f in ((.7,1.1,55.),(1.6,2.1,73.4),(3.0,3.6,110.),(4.9,5.3,55.)):
            q=gate(t,a,b);low+=.11*q*(np.sin(2*np.pi*f*t)+.45*np.sin(4*np.pi*f*t)+.2*np.sin(6*np.pi*f*t))
    else:raise ValueError(kind)
    return np.column_stack((bed+low,.94*bed+low))


def save(path,x):sf.write(path,x,48000,subtype='DOUBLE');return path


class FixtureObserver:
    def __init__(self,mode='weak'):self.mode=mode;self.calls=[]
    def identity(self):return dict(provider=v51.SYNTHETIC_PROVIDER,evidence_scope='engineering_fixture',mode=self.mode,fixture_sha256='a'*64)
    def preflight(self):return self
    def observe(self,source,start,end,progress=None):
        self.calls.append((float(start),float(end)));ident=capture(source);t=start+np.arange(round((end-start)*100))*.01;n=len(t)
        p=np.full((2,n,5),1e-9);p[:,:,0]=.03;p[:,:,2]=.027
        f=np.full((2,n),55.);q=np.full((2,n),.995)
        if self.mode=='110':f[:]=110.
        return dict(time=t,low_power=p,body_power=p.copy(),focus_power=p.copy(),bass_f0_hz=f,bass_periodicity=q),dict(version='role-observer-0.2.0',provider=v51.SYNTHETIC_PROVIDER,source_sha256=ident.file_sha256,source_frames=ident.frames,source_samplerate=ident.samplerate,source_order=['mix','drums','bass','other','vocals'],start_seconds=float(start),end_seconds=float(end))


class FailObserver(FixtureObserver):
    def observe(self,*a,**k):raise AssertionError('observer must not run on non-improvable reduction score')


def semantics(plan):
    broad=plan['reduction_plan']['broad_plan']
    adds=[]
    for a in plan['additions']:
        adds.append(dict(target_hz=round(float(a['target_hz']),9),source_frames=list(a['source_frames']),envelope=[round(float(x),12) for x in a['envelope']],amplitude=round(float(a['amplitude']),12),phase=round(float(a['phase']),12)))
    return dict(low_cut_db=[round(float(x),12) for x in broad['low_cut_db']],additions=adds)


class V51Contracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.root=Path(cls.tmp.name);specs=[]
        for i in range(4):
            x=audio('reference');x[:,0]*=(1+i*.003);p=save(cls.root/f'ref{i}.wav',x);specs.append(dict(path=p,role='bass',quality='positive'))
        cls.bundle=v51.make_calibration(specs)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def case(self,kind):
        d=Path(tempfile.mkdtemp(dir=self.root));p=save(d/f'{kind}.wav',audio(kind));snap=RenderSnapshot.bind(capture(p),capture(p),{'v51':kind});return p,snap,PlanningContext(p,p,snap)

    def test_weak_f0_matches_v50_semantics_with_fewer_observer_calls(self):
        source,snap,ctx=self.case('weak');o50=FixtureObserver('weak');o51=FixtureObserver('weak')
        p50=v50.AutomaticJointPlanner(self.bundle,o50,allow_fixture=True);p51=v51.AutomaticJointPlanner(self.bundle,o51,allow_fixture=True)
        a=p50.build(ctx);b=p51.build(ctx)
        self.assertEqual(semantics(a),semantics(b));self.assertGreaterEqual(len(b['additions']),1,p51.last_report)
        self.assertLess(len(o51.calls),len(o50.calls),(len(o50.calls),len(o51.calls),p51.last_report['observer_optimization']))
        self.assertEqual(p51.last_report['observer_optimization']['observer_calls_executed'],len(o51.calls))

    def test_source_veto_is_decidable_without_neural_evidence(self):
        source,snap,ctx=self.case('strongfund')
        proof=dict(method='ORIGINAL_COMPONENT_PRESENT;_HARMONIC_SUPPORTED;_NO_MISSING_FUNDAMENTAL',fundamental_to_upper_ratio=.50,f0_hz=55.)
        row=dict(start_seconds=2.1,end_seconds=4.4)
        shape,reasons,ratio,upper=v51._source_veto(source,row,proof)
        self.assertIn('ABSTAIN_F0_NOT_WEAK_ENOUGH_FOR_REPAIR',reasons);self.assertGreater(ratio,.15)

    def test_non_improvable_relative_score_never_invokes_observer(self):
        source,snap,ctx=self.case('weak');t=np.arange(0,7,.01);physical={'time':t};rel=dict(low_cut_db=np.where((t>2)&(t<3),.5,0.),candidate=True)
        pid=dict(planner_id=v51.VERSION,calibration_sha256=self.bundle['sha256'],evidence_scope='engineering_fixture')
        with mock.patch.object(v51.dominance,'score',return_value=.05):
            r=v51._compile_relative(ctx,self.bundle,FailObserver(),FixtureObserver().identity(),pid,physical,rel,t,snap)
        self.assertTrue(r['zero_score_short_circuit']);self.assertEqual(r['observer_calls'],0);self.assertEqual(r['reduction_state'],'ABSTAIN');self.assertFalse(any(r['broad_plan']['low_cut_db']))

    def test_pure_110_never_becomes_new_55(self):
        source,snap,ctx=self.case('110');o50=FixtureObserver('110');o51=FixtureObserver('110')
        a=v50.AutomaticJointPlanner(self.bundle,o50,allow_fixture=True).build(ctx);p51=v51.AutomaticJointPlanner(self.bundle,o51,allow_fixture=True);b=p51.build(ctx)
        self.assertEqual(semantics(a),semantics(b));self.assertEqual(b['additions'],[]);self.assertEqual(p51.last_report['accepted_additions'],0)

if __name__=='__main__':unittest.main(verbosity=2)
