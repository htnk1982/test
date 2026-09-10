from pathlib import Path
import json,tempfile,unittest
import numpy as np,soundfile as sf
import gui_runtime_v44 as g
from target_settings import Targets

class RuntimeContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.r=Path(self.tmp.name);self.s=self.r/'a.wav'
        sf.write(self.s,np.zeros((48000,2)),48000,subtype='FLOAT');self.session=self.r/'session';self.work=self.r/'work'
        self.m=g.make_manifest([self.s],Targets(),False,self.work,self.session,runtime_id='engineering_fixture_tail')
        self.mp=self.r/'manifest.json';g.atomic_json(self.mp,self.m)
    def tearDown(self):self.tmp.cleanup()
    def test_roundtrip(self):self.assertEqual(g.read_manifest(self.mp),self.m)
    def test_manifest_tamper(self):
        x=json.loads(self.mp.read_text());x['targets']['wav_lufs']=-20;g.atomic_json(self.mp,x)
        with self.assertRaises(ValueError):g.read_manifest(self.mp)
    def test_duplicate_source_rejected(self):
        with self.assertRaises(ValueError):g.make_manifest([self.s,self.s],Targets(),False,self.work,self.session,runtime_id='x')
    def test_same_stem_wav_flac_collision_rejected_before_batch(self):
        flac=self.r/'a.flac';sf.write(flac,np.zeros((48000,2)),48000,format='FLAC')
        with self.assertRaisesRegex(ValueError,'output collision'):
            g.make_manifest([self.s,flac],Targets(),False,self.work,self.session,runtime_id='x')
        self.assertFalse((self.r/'processed').exists())
    def test_same_stem_different_folders_allowed(self):
        other=self.r/'other';other.mkdir();p=other/'a.flac';sf.write(p,np.zeros((48000,2)),48000,format='FLAC')
        m=g.make_manifest([self.s,p],Targets(),False,self.work,self.session,runtime_id='x');self.assertEqual(len(m['sources']),2)
    def test_empty_rejected(self):
        with self.assertRaises(ValueError):g.make_manifest([],Targets(),False,self.work,self.session,runtime_id='x')
    def test_bad_target_rejected(self):
        with self.assertRaises(ValueError):g.make_manifest([self.s],Targets(wav_lufs=float('nan')),False,self.work,self.session,runtime_id='x')
    def test_run_success_status(self):
        def processor(source,targets,replace,work,progress):progress.set('DSP',2,4);return dict(lowend_assessment='KEEP_SUPPORTED')
        out=g.run_batch(self.mp,processor);self.assertEqual(out['overall'],'COMPLETE');self.assertEqual(out['completed'][0]['file'],'a.wav')
    def test_file_failure_continues(self):
        b=self.r/'b.wav';b.write_bytes(self.s.read_bytes());m=g.make_manifest([self.s,b],Targets(),False,self.work,self.session,runtime_id='engineering_fixture_tail');g.atomic_json(self.mp,m)
        calls=[]
        def processor(source,*args):
            calls.append(source.name)
            if source.name=='a.wav':raise RuntimeError('bad one')
            return dict(lowend_assessment='KEEP_SUPPORTED')
        out=g.run_batch(self.mp,processor);self.assertEqual(out['overall'],'COMPLETE_WITH_ERRORS');self.assertEqual(calls,['a.wav','b.wav']);self.assertEqual(len(out['failures']),1)
    def test_cancel_stops_queue(self):
        b=self.r/'b.wav';b.write_bytes(self.s.read_bytes());m=g.make_manifest([self.s,b],Targets(),False,self.work,self.session,runtime_id='engineering_fixture_tail');g.atomic_json(self.mp,m)
        calls=[]
        def processor(source,targets,replace,work,progress):
            calls.append(source.name);g.request_cancel(self.session);progress.set('NEXT_SAFE_POINT',0,1)
        out=g.run_batch(self.mp,processor);self.assertEqual(out['overall'],'CANCELLED');self.assertEqual(calls,['a.wav'])
    def test_status_identity(self):
        g.StatusProgress(self.session,self.m['sha256'])
        with self.assertRaises(ValueError):g.read_status(self.session,'b'*64)
    def test_cancel_is_durable_file(self):self.assertTrue(g.request_cancel(self.session).read_text().startswith('cancel'))
    def test_processor_receives_exact_targets_and_replace(self):
        expected=Targets(wav_lufs=-13,wav_tp=-2.5,mp3_lufs=-15,mp3_tp=-3)
        m=g.make_manifest([self.s],expected,True,self.work,self.session,runtime_id='engineering_fixture_tail');g.atomic_json(self.mp,m);seen={}
        def processor(source,targets,replace,work,progress):seen.update(targets=targets.to_dict(),replace=replace,source=source);return dict(lowend_assessment='KEEP_SUPPORTED')
        g.run_batch(self.mp,processor);self.assertEqual(seen['targets'],expected.to_dict());self.assertTrue(seen['replace']);self.assertEqual(seen['source'],self.s.absolute())
    def test_unknown_status_schema_rejected(self):
        self.session.mkdir();g.atomic_json(self.session/'status.json',dict(schema=99,version=g.VERSION))
        with self.assertRaises(ValueError):g.read_status(self.session)

if __name__=='__main__':unittest.main(verbosity=2)
