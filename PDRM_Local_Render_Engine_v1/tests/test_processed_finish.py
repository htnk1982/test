from pathlib import Path
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
import processed_finish as app
from test_note_sub_lab import notes


class ProcessedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.inputs = self.root / '日本語 入力'
        self.inputs.mkdir()
        self.source = self.inputs / '01 - 返事は私.v2.wav'
        self.source.write_bytes(b'original-test-data')
        self.work = self.root / 'private_work'
        self.final = self.work / 'finished'
        self.final.mkdir(parents=True)
        for name, body in zip(app.engine.FILES, (b'24-bit-master', b'14-WAV', b'14-MP3')):
            (self.final / name).write_bytes(body)
        self.calls = 0
        self.patchers = [patch.object(app, 'request_identity', side_effect=self.identity),
                         patch.object(app.engine, 'run_file', side_effect=self.backend),
                         patch.object(app.engine, 'verify_final', return_value={})]
        for p in self.patchers: p.start()
    def tearDown(self):
        for p in reversed(self.patchers): p.stop()
        self.tmp.cleanup()
    def identity(self, source):
        return dict(source_name=source.name, source_sha256=app.io.file_hash(source), engine_version='frozen')
    def backend(self, source, root, **kw):
        self.calls += 1
        self.assertTrue(kw['write_mp3'])
        r = dict(status='COMPLETE', source_unchanged=True, identity=self.identity(source),
                 master_metrics={'lufs_i':-12}, codec_metrics={'lufs_i':-14})
        return r, self.final
    def run_app(self, source=None, **kw):
        return app.run_file(source or self.source, self.work, **kw)
    def paths(self): return app.output_paths(self.source)

    def test_01_exact_unicode_stem_and_only_two_audio_files(self):
        r, folder = self.run_app()
        self.assertTrue(folder.parent.samefile(self.inputs))
        self.assertEqual(folder.name, 'processed')
        self.assertEqual({p.name for p in folder.iterdir() if p.is_file()},
                         {'01 - 返事は私.v2.wav','01 - 返事は私.v2.mp3'})
        self.assertEqual(r['status'], 'COMPLETE')
    def test_02_publish_is_byte_copy_not_reencode(self):
        _, folder = self.run_app()
        for ext, name in (('wav',app.engine.FILES[0]),('mp3',app.engine.FILES[2])):
            self.assertEqual(app.io.file_hash(folder/(self.source.stem+'.'+ext)),
                             app.io.file_hash(self.final/name))
        self.assertEqual(self.source.read_bytes(), b'original-test-data')
    def test_03_same_source_rerun_never_calls_backend(self):
        _, folder = self.run_app(); before = {p.name:p.stat().st_mtime_ns for p in folder.iterdir() if p.is_file()}
        r, _ = self.run_app()
        self.assertEqual(r['rerun_status'], 'IDEMPOTENT_SKIP');self.assertEqual(self.calls,1)
        self.assertEqual(before, {p.name:p.stat().st_mtime_ns for p in folder.iterdir() if p.is_file()})
    def test_04_foreign_wav_is_not_overwritten(self):
        folder,paths = self.paths();folder.mkdir();paths['wav'].write_bytes(b'precious')
        with self.assertRaisesRegex(RuntimeError,'conflict'):self.run_app()
        self.assertEqual(paths['wav'].read_bytes(),b'precious');self.assertEqual(self.calls,0)
    def test_05_foreign_mp3_blocks_both(self):
        folder,paths=self.paths();folder.mkdir();paths['mp3'].write_bytes(b'precious')
        with self.assertRaisesRegex(RuntimeError,'conflict'):self.run_app()
        self.assertFalse(paths['wav'].exists());self.assertEqual(self.calls,0)
    def test_06_modified_managed_output_refused(self):
        _,folder=self.run_app();p=folder/(self.source.stem+'.wav');p.write_bytes(b'edited')
        with self.assertRaisesRegex(RuntimeError,'modified'):self.run_app()
        self.assertEqual(p.read_bytes(),b'edited');self.assertEqual(self.calls,1)
    def test_07_changed_source_same_name_refused(self):
        self.run_app();self.source.write_bytes(b'new source')
        with self.assertRaisesRegex(RuntimeError,'another source'):self.run_app()
        self.assertEqual(self.calls,1)
    def test_08_resume_after_first_publish(self):
        with self.assertRaisesRegex(RuntimeError,'PUBLISH_1'):self.run_app(interrupt_after=1)
        folder, paths=self.paths();self.assertTrue(paths['wav'].exists());self.assertFalse(paths['mp3'].exists())
        wav_mtime=paths['wav'].stat().st_mtime_ns
        r,_=self.run_app();self.assertEqual(r['status'],'COMPLETE')
        self.assertEqual(wav_mtime,paths['wav'].stat().st_mtime_ns);self.assertTrue(paths['mp3'].is_file())
    def test_09_resume_after_both_before_receipt(self):
        with self.assertRaisesRegex(RuntimeError,'PUBLISH_2'):self.run_app(interrupt_after=2)
        r,_=self.run_app();self.assertEqual(r['status'],'COMPLETE')
    def test_10_missing_owned_file_restored(self):
        self.run_app();folder,paths=self.paths();paths['mp3'].unlink()
        r,_=self.run_app();self.assertTrue(paths['mp3'].is_file());self.assertEqual(r['status'],'COMPLETE')
    def test_11_processed_input_rejected(self):
        self.run_app();_,paths=self.paths()
        with self.assertRaisesRegex(ValueError,'not a fresh'):self.run_app(paths['wav'])
    def test_12_flac_uses_stem_and_wav_extension(self):
        p=self.source.with_suffix('.flac');self.source.rename(p)
        _,folder=self.run_app(p);self.assertTrue((folder/(p.stem+'.wav')).is_file())
        self.assertFalse((folder/(p.stem+'.flac')).exists())
    def test_13_same_stem_other_extension_refused(self):
        self.run_app();p=self.source.with_suffix('.flac');p.write_bytes(b'flac data')
        with self.assertRaisesRegex(RuntimeError,'another source'):self.run_app(p)
    def test_14_different_parents_have_separate_processed(self):
        r1,a=self.run_app();parent=self.root/'other';parent.mkdir();p=parent/self.source.name
        p.write_bytes(self.source.read_bytes());r2,b=self.run_app(p)
        self.assertNotEqual(a,b);self.assertTrue((a/p.name).is_file());self.assertTrue((b/p.name).is_file())
    def test_15_case_only_collision_is_refused(self):
        folder,paths=self.paths();folder.mkdir();(folder/(self.source.stem.upper()+'.wav')).write_bytes(b'foreign')
        with self.assertRaisesRegex(RuntimeError,'conflict'):self.run_app()
    def test_16_processed_is_file_refused(self):
        folder,_=self.paths();folder.write_bytes(b'do not touch')
        with self.assertRaisesRegex(ValueError,'real directory'):self.run_app()
        self.assertEqual(folder.read_bytes(),b'do not touch')
    def test_17_redirected_directory_refused(self):
        with patch.object(app,'_redirected',side_effect=lambda p:p.name=='processed'):
            with self.assertRaisesRegex(ValueError,'real directory'):self.run_app()
    def test_18_engine_failure_exposes_no_audio(self):
        with patch.object(app.engine,'run_file',side_effect=RuntimeError('engine failure')):
            with self.assertRaisesRegex(RuntimeError,'engine failure'):self.run_app()
        folder,paths=self.paths();self.assertFalse(any(p.exists() for p in paths.values()))
    def test_19_copy_failure_does_not_touch_original(self):
        with patch.object(app.shutil,'copyfileobj',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):self.run_app()
        folder,paths=self.paths();self.assertFalse(any(p.exists() for p in paths.values()))
        self.assertEqual(self.source.read_bytes(),b'original-test-data')
        self.assertFalse(list((folder/'.pdrm').glob('*.partial')))
        self.run_app();self.assertTrue(paths['mp3'].exists())
    def test_20_no_clobber_if_file_appears_at_publication(self):
        temp=self.root/'t';dest=self.root/'d';temp.write_bytes(b'new');dest.write_bytes(b'existing')
        with self.assertRaises(FileExistsError):app._install_new(temp,dest)
        self.assertEqual(dest.read_bytes(),b'existing')
    def test_21_cli_no_output_directory_dialog(self):
        with patch.object(app,'choose_sources',return_value=[self.source]) as chooser,patch.object(app.os,'startfile',create=True):
            self.assertEqual(app.main(['--work-root',str(self.work)]),0)
            chooser.assert_called_once_with([])
        self.assertTrue((self.inputs/'processed'/self.source.name).is_file())
    def test_22_batch_same_stem_is_rejected_before_render(self):
        p=self.source.with_suffix('.flac');p.write_bytes(b'f')
        self.assertEqual(app.main([str(self.source),str(p),'--work-root',str(self.work)]),1)
        self.assertEqual(self.calls,0)
    def test_23_cancel_has_no_side_effect(self):
        with patch.object(app,'choose_sources',return_value=[]):self.assertEqual(app.main([]),0)
        self.assertFalse((self.inputs/'processed').exists())
    def test_24_work_root_cannot_be_inside_public_folder(self):
        with self.assertRaisesRegex(ValueError,'outside processed'):
            app.run_file(self.source,self.inputs/'processed'/'work')
    def test_25_true_engine_integration_and_targets(self):
        for p in reversed(self.patchers):p.stop()
        x,sr=notes(frequencies=(82.406889,));sf.write(self.source,x*.4,sr,subtype='FLOAT')
        before=app.io.file_hash(self.source)
        r,folder=self.run_app()
        self.assertEqual(r['status'],'COMPLETE');self.assertEqual(before,app.io.file_hash(self.source))
        for key,target,tol in (('master_metrics',-12,.03),('codec_metrics',-14,.10)):
            self.assertLess(abs(r[key]['lufs_i']-target),tol)
            self.assertLessEqual(r[key]['true_peak_max_dbtp_estimate'],-2)
        self.assertEqual(sf.info(folder/self.source.name).subtype,'PCM_24')
        backend=Path(r['render_result'])
        self.assertEqual(app.io.file_hash(folder/self.source.name),app.io.file_hash(backend/app.engine.FILES[0]))
        self.assertEqual(app.io.file_hash(folder/(self.source.stem+'.mp3')),app.io.file_hash(backend/app.engine.FILES[2]))
        self.assertFalse((folder/app.engine.FILES[1]).exists())


if __name__=='__main__':unittest.main(verbosity=2)
