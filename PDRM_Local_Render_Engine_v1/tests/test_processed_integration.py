"""Publication lifecycle contracts using outputs from the real audio chain.

Fixture completion is generated once, then copied into each isolated call by a
mock of run_lab. Publication/proof/sidecar/backup/retry/cleanup are real. A separate
packaging verifier runs the new wrapper without this render mock end-to-end.
"""
from pathlib import Path
import copy,json,tempfile,unittest,shutil
from unittest.mock import patch
import numpy as np
import soundfile as sf
import integrated_finish_v40 as finish
import processed_integration as subject
import lowend_coordinator_v40 as broad
from joint42_selftest import FixturePlanner
from decay39_fixtures import audio_fixture
from target_settings import Targets
from integration_contract_v40 import capture,digest


class AbstainPlanner:
    def identity(self):
        return dict(planner_id='publication-test-abstain',calibration_sha256='d'*64,evidence_scope='engineering_fixture')
    def preflight(self):pass
    def build(self,context,progress=None):
        return broad.compile_plan(context.snapshot,[],assessment='ABSTAIN',**self.identity())


class PublicationContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base=tempfile.TemporaryDirectory();cls.root=Path(cls.base.name)
        inp=cls.root/'inputs';inp.mkdir();cls.seed=inp/'seed.wav'
        _,bad,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.)
        sf.write(cls.seed,bad,48000,subtype='DOUBLE');cls.bytes=cls.seed.read_bytes()
        cls.fixtures={}
        for key,lufs,planner,backend in [('normal',-12.,FixturePlanner('tail'),'joint-v42'),
                                       ('changed',-13.,FixturePlanner('tail'),'joint-v42'),
                                       ('abstain',-12.,AbstainPlanner(),'broad-v40')]:
            cls.fixtures[key]=finish.run_lab(cls.seed,cls.root/key,planner,
                targets=Targets(wav_lufs=lufs),enable_lab=True,render_backend=backend)

    @classmethod
    def tearDownClass(cls):cls.base.cleanup()

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=self.root);self.r=Path(self.tmp.name)
        self.inputs=self.r/'日本語 音源';self.inputs.mkdir()
        self.source=self.inputs/'01 音源.wav';self.source.write_bytes(self.bytes)
        self.work=self.r/'work';self.planner=FixturePlanner('tail');self.calls=0

    def tearDown(self):self.tmp.cleanup()

    def render_fixture(self,source,root,planner,**kw):
        self.calls+=1
        name='abstain' if kw.get('render_backend')=='broad-v40' else ('changed' if kw['targets'].wav_lufs==-13 else 'normal')
        report,where=self.fixtures[name]
        dest=Path(root)/'VERIFIED_FIXTURE';shutil.copytree(where,dest)
        return copy.deepcopy(report),dest

    def invoke(self,**kwargs):
        args=dict(planner=self.planner,enable_lab=True)
        args.update(kwargs)
        with patch.object(finish,'run_lab',side_effect=self.render_fixture):
            return subject.run_file(self.source,self.work,**args)

    def no_owned_cache(self):
        self.assertFalse(list(self.work.glob('.publish-integration-*')))

    def test_exact_same_name_audio_bytes(self):
        r,folder=self.invoke();_,fixtures=self.fixtures['normal']
        self.assertEqual(folder,self.inputs/'processed')
        self.assertEqual((folder/'01 音源.wav').read_bytes(),(fixtures/'MASTER.wav').read_bytes())
        self.assertEqual((folder/'01 音源.mp3').read_bytes(),(fixtures/'LISTEN_320kbps.mp3').read_bytes())
        self.assertEqual(self.source.read_bytes(),self.bytes)
        self.assertTrue(r['final_cache_removed']);self.no_owned_cache()

    def test_idempotent_skips_audio_engine(self):
        first,_=self.invoke();self.calls=0;again,_=self.invoke()
        self.assertEqual(self.calls,0);self.assertEqual(again['rerun_status'],'IDEMPOTENT_SKIP')
        self.assertEqual(first['files'],again['files']);self.no_owned_cache()

    def test_lab_opt_in_required(self):
        with self.assertRaises(RuntimeError):self.invoke(enable_lab=False)
        self.assertEqual(self.calls,0)

    def test_missing_planner_not_default_keep(self):
        with self.assertRaises(ValueError):self.invoke(planner=None)

    def test_unknown_renderer_rejected(self):
        with self.assertRaises(ValueError):self.invoke(render_backend='import:arbitrary')

    def test_output_not_fresh_source(self):
        r,folder=self.invoke();self.source=folder/'01 音源.wav'
        with self.assertRaises(ValueError):self.invoke()

    def test_changed_targets_need_explicit_backup(self):
        r,f=self.invoke();old=(f/'01 音源.wav').read_bytes();self.calls=0
        with self.assertRaises(RuntimeError):self.invoke(targets=Targets(wav_lufs=-13.))
        self.assertEqual(self.calls,0);self.assertEqual((f/'01 音源.wav').read_bytes(),old)

    def test_managed_replacement_preserves_old_audio(self):
        old,f=self.invoke();before=(f/'01 音源.wav').read_bytes()
        new,_=self.invoke(targets=Targets(wav_lufs=-13.),replace_managed=True)
        self.assertNotEqual(new['files'],old['files'])
        backups=list((f/'.pdrm'/'backups').glob('*/01 音源.wav'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),before)
        self.no_owned_cache()

    def test_interrupt_after_wav_then_safe_retry(self):
        with self.assertRaisesRegex(RuntimeError,'TEST_INTERRUPTION_PUBLISH_1'):self.invoke(interrupt_after=1)
        f=self.inputs/'processed';self.assertTrue((f/'01 音源.wav').exists());self.assertFalse((f/'01 音源.mp3').exists())
        self.no_owned_cache();r,_=self.invoke();self.assertEqual(r['status'],'COMPLETE');self.no_owned_cache()

    def test_interrupt_after_pair_then_safe_retry(self):
        with self.assertRaisesRegex(RuntimeError,'TEST_INTERRUPTION_PUBLISH_2'):self.invoke(interrupt_after=2)
        self.no_owned_cache();r,_=self.invoke();self.assertEqual(r['status'],'COMPLETE')

    def test_interrupted_replacement_retains_backup(self):
        old,f=self.invoke();before=(f/'01 音源.wav').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'TEST_INTERRUPTION_PUBLISH_1'):
            self.invoke(targets=Targets(wav_lufs=-13.),replace_managed=True,interrupt_after=1)
        new,_=self.invoke(targets=Targets(wav_lufs=-13.),replace_managed=True)
        self.assertEqual(new['status'],'COMPLETE')
        backups=list((f/'.pdrm'/'backups').glob('*/01 音源.wav'))
        self.assertEqual(len(backups),1);self.assertEqual(backups[0].read_bytes(),before)

    def test_user_modified_output_never_overwritten(self):
        _,f=self.invoke();p=f/'01 音源.wav';p.write_bytes(b'user-edited')
        with self.assertRaises(RuntimeError):self.invoke(replace_managed=True)
        self.assertEqual(p.read_bytes(),b'user-edited')

    def test_unmanaged_name_never_overwritten(self):
        f=self.inputs/'processed';f.mkdir();p=f/'01 音源.mp3';p.write_bytes(b'unmanaged')
        with self.assertRaises(RuntimeError):self.invoke(replace_managed=True)
        self.assertEqual(p.read_bytes(),b'unmanaged')

    def test_bad_sidecar_not_healthy_skip(self):
        r,_=self.invoke();p=Path(r['processing_evidence']);j=json.loads(p.read_text(encoding='utf-8'))
        j['quality_status']='APPROVED';p.write_text(json.dumps(j),encoding='utf-8')
        with self.assertRaises(RuntimeError):self.invoke()

    def test_abstain_retained_beside_technical_completion(self):
        r,f=self.invoke(planner=AbstainPlanner(),render_backend='broad-v40')
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(r['lowend_assessment'],'ABSTAIN')
        self.assertEqual(r['quality_status'],'NOT_EVALUATED')
        evidence=json.loads(Path(r['processing_evidence']).read_text(encoding='utf-8'))
        self.assertEqual(evidence['lowend_assessment'],'ABSTAIN')
        self.assertEqual(evidence['publication_scope'],'LAB_TECHNICAL_ONLY')
        self.assertEqual(self.invoke(planner=AbstainPlanner(),render_backend='broad-v40')[0]['lowend_assessment'],'ABSTAIN')

    def test_cancel_removes_only_owned_directory(self):
        self.work.mkdir();sentinel=self.work/'unrelated.bin';sentinel.write_bytes(b'keep')
        def cancel(source,root,*args,**kw):
            (Path(root)/'intermediate.wav').write_bytes(b'x'*100000)
            raise InterruptedError('cancel')
        with patch.object(finish,'run_lab',side_effect=cancel):
            with self.assertRaises(InterruptedError):subject.run_file(self.source,self.work,planner=self.planner,enable_lab=True)
        self.no_owned_cache();self.assertEqual(sentinel.read_bytes(),b'keep')
        self.assertFalse((self.inputs/'processed'/'01 音源.wav').exists())

    def test_failed_engine_removes_cache_no_published_audio(self):
        def fail(source,root,*args,**kw):
            (Path(root)/'intermediate.wav').write_bytes(b'x'*100000)
            raise RuntimeError('engine failed')
        with patch.object(finish,'run_lab',side_effect=fail):
            with self.assertRaises(RuntimeError):subject.run_file(self.source,self.work,planner=self.planner,enable_lab=True)
        self.no_owned_cache();self.assertFalse((self.inputs/'processed'/'01 音源.wav').exists())

    def test_forged_engine_completion_rejected(self):
        def wrong(*a,**kw):
            report,p=self.render_fixture(*a,**kw);report['source_unchanged']=False;return report,p
        with patch.object(finish,'run_lab',side_effect=wrong):
            with self.assertRaises(RuntimeError):subject.run_file(self.source,self.work,planner=self.planner,enable_lab=True)
        self.no_owned_cache();self.assertFalse((self.inputs/'processed'/'01 音源.wav').exists())

    def test_no_work_inside_original_folder(self):
        with self.assertRaises(ValueError):subject.run_file(self.source,self.inputs/'cache',planner=self.planner,enable_lab=True)

    def test_flag_validation(self):
        for value in (True,4,'1'):
            with self.assertRaises(ValueError):self.invoke(interrupt_after=value)
        with self.assertRaises(ValueError):self.invoke(replace_managed='yes')

    def test_missing_model_preflight_before_any_publication(self):
        class Missing(FixturePlanner):
            def preflight(self):raise RuntimeError('model missing')
        with self.assertRaisesRegex(RuntimeError,'model missing'):self.invoke(planner=Missing('tail'))
        self.assertFalse((self.inputs/'processed').exists())

if __name__=='__main__':unittest.main(verbosity=2)
