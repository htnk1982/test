from pathlib import Path
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(Path(__file__).parent))
from target_settings import Targets,load_settings,save_settings
import distribution_finish as engine
import processed_finish as app
from test_note_sub_lab import notes

class TargetValidation(unittest.TestCase):
    def test_defaults(self):self.assertEqual(Targets().to_dict(),dict(wav_lufs=-12,wav_tp=-2,mp3_lufs=-14,mp3_tp=-2))
    def test_four_independent_values(self):
        t=Targets(-16,-3,-12,-5);self.assertEqual(t.validate(),t)
    def test_outside_ranges(self):
        for name,value in [('wav_lufs',-31),('mp3_lufs',-7),('wav_tp',0),('mp3_tp',-13)]:
            with self.subTest(name=name),self.assertRaises(ValueError):Targets(**{name:value}).validate()
    def test_nan_inf_booleans(self):
        for value in (float('nan'),float('inf'),True):
            with self.subTest(value=value),self.assertRaises(ValueError):Targets(wav_lufs=value).validate()
    def test_unicode_numbers(self):
        t=Targets.from_fields(dict(wav_lufs='−１２.５',wav_tp='-2',mp3_lufs='-14.5',mp3_tp='-3'))
        self.assertEqual(t,Targets(-12.5,-2,-14.5,-3))
    def test_empty_nonnumeric(self):
        for value in ('','hello','12,5'):
            with self.subTest(value=value),self.assertRaises(ValueError):Targets.from_fields(dict(Targets().to_dict(),wav_lufs=value))
    def test_missing_unknown_fields(self):
        with self.assertRaises(ValueError):Targets.from_fields({'wav_lufs':-12})
        with self.assertRaises(ValueError):Targets.from_fields(dict(Targets().to_dict(),extra=1))
    def test_immutable(self):
        with self.assertRaises(AttributeError):Targets().wav_tp=-4
    def test_roundtrip_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'user'/'settings.json';t=Targets(-16.5,-2.5,-18,-3.5)
            save_settings(t,p);self.assertEqual(load_settings(p),(t,''))
            self.assertEqual(set(json.loads(p.read_text())['targets']),set(t.to_dict()))
    def test_corrupt_settings_reported(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.json';p.write_text('broken')
            t,warning=load_settings(p);self.assertEqual(t,Targets());self.assertTrue(warning)
    def test_missing_settings_defaults(self):
        with tempfile.TemporaryDirectory() as d:self.assertEqual(load_settings(Path(d)/'missing'),(Targets(),''))
    def test_invalid_settings_never_written(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'s.json';save_settings(Targets(),p);before=p.read_bytes()
            with self.assertRaises(ValueError):save_settings(Targets(mp3_tp=0),p)
            self.assertEqual(p.read_bytes(),before)

class PublisherTargets(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'original'/'曲.v1.wav';self.source.parent.mkdir();self.source.write_bytes(b'original')
        self.final=self.root/'backend';self.final.mkdir();self.calls=[]
        self.ps=[patch.object(app,'request_identity',side_effect=self.identity),
                 patch.object(engine,'run_file',side_effect=self.backend),
                 patch.object(engine,'verify_final',return_value={})]
        for p in self.ps:p.start()
    def tearDown(self):
        for p in reversed(self.ps):p.stop()
        self.tmp.cleanup()
    def identity(self,source,targets=None):
        return dict(source_name=source.name,source_sha256=app.io.file_hash(source),targets=(targets or Targets()).to_dict())
    def backend(self,source,work,**kw):
        t=kw.get('targets') or Targets();self.calls.append(t)
        for i,name in enumerate(engine.FILES):(self.final/name).write_bytes((str(t)+str(i)).encode())
        return dict(status='COMPLETE',source_unchanged=True,identity=self.identity(source,t),
                    master_metrics=dict(lufs_i=t.wav_lufs),codec_metrics=dict(lufs_i=t.mp3_lufs)),self.final
    def run_app(self,t=None,**kw):return app.run_file(self.source,self.root/'work',targets=t or Targets(),**kw)
    def test_targets_forwarded_and_recorded(self):
        t=Targets(-16,-3,-18,-4);r,_=self.run_app(t)
        self.assertEqual(self.calls,[t]);self.assertEqual(r['request']['targets'],t.to_dict())
    def test_all_four_fields_invalidate_output_identity(self):
        self.run_app()
        for name,value in [('wav_lufs',-13),('wav_tp',-3),('mp3_lufs',-15),('mp3_tp',-4)]:
            with self.subTest(name=name),self.assertRaises(RuntimeError):self.run_app(Targets(**{name:value}))
        self.assertEqual(len(self.calls),1)
    def test_same_settings_skip(self):
        self.run_app();r,_=self.run_app();self.assertEqual(r['rerun_status'],'IDEMPOTENT_SKIP');self.assertEqual(len(self.calls),1)
    def test_explicit_replace_backs_up_prior_pair(self):
        first,out=self.run_app();old={p.name:p.read_bytes() for p in out.iterdir() if p.is_file()}
        r,_=self.run_app(Targets(-16,-3,-17,-4),replace_managed=True)
        backup=Path(r['backup']);self.assertTrue(backup.is_dir())
        for name,body in old.items():self.assertEqual((backup/name).read_bytes(),body)
        self.assertEqual(self.source.read_bytes(),b'original');self.assertEqual(r['status'],'COMPLETE')
    def test_changed_source_not_replaced(self):
        self.run_app();self.source.write_bytes(b'new')
        with self.assertRaises(RuntimeError):self.run_app(Targets(-16,-3,-17,-4),replace_managed=True)
    def test_edited_output_not_replaced(self):
        _,out=self.run_app();p=out/self.source.name;p.write_bytes(b'edited')
        with self.assertRaises(RuntimeError):self.run_app(Targets(-16,-3,-17,-4),replace_managed=True)
        self.assertEqual(p.read_bytes(),b'edited')
    def test_failed_render_retains_old_pair_and_receipt(self):
        _,out=self.run_app();before={p:app.io.file_hash(p) for p in out.rglob('*.json')}
        old={p:app.io.file_hash(p) for p in out.iterdir() if p.is_file()}
        with patch.object(engine,'run_file',side_effect=RuntimeError('render failed')):
            with self.assertRaises(RuntimeError):self.run_app(Targets(-16,-3,-17,-4),replace_managed=True)
        for p,h in dict(before,**{}).items():self.assertEqual(app.io.file_hash(p),h)
        for p,h in old.items():self.assertEqual(app.io.file_hash(p),h)
    def test_resume_replacement_after_first_file(self):
        self.run_app();t=Targets(-16,-3,-17,-4)
        with self.assertRaisesRegex(RuntimeError,'PUBLISH_1'):self.run_app(t,replace_managed=True,interrupt_after=1)
        r,out=self.run_app(t);self.assertEqual(r['status'],'COMPLETE')
        self.assertEqual((out/self.source.name).read_bytes(),(str(t)+'0').encode())
        self.assertEqual((out/self.source.with_suffix('.mp3').name).read_bytes(),(str(t)+'2').encode())
    def test_foreign_files_never_replaced(self):
        out=self.source.parent/'processed';out.mkdir();p=out/self.source.name;p.write_bytes(b'foreign')
        with self.assertRaises(RuntimeError):self.run_app(replace_managed=True)
        self.assertEqual(p.read_bytes(),b'foreign')
    def test_invalid_target_causes_no_folder(self):
        with self.assertRaises(ValueError):self.run_app(Targets(mp3_tp=0))
        self.assertFalse((self.source.parent/'processed').exists())

class RealTargetProcessing(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'source.wav';self.x,self.sr=notes(frequencies=(82.406889,))
        self.x[len(self.x)//2,:]=.9
        sf.write(self.source,self.x*.6,self.sr,subtype='FLOAT')
        self.ff=engine.io.ffmpeg_path()
        if not self.ff:self.fail('FFmpeg missing from test environment')
    def tearDown(self):self.tmp.cleanup()
    def test_custom_targets_full_chain(self):
        t=Targets(-16,-3,-17,-4)
        before=engine.io.file_hash(self.source)
        r,out=engine.run_file(self.source,self.root/'work',targets=t)
        self.assertEqual(r['requested_targets'],t.to_dict())
        self.assertTrue(r['harmonic_elasticity_applied']);self.assertTrue(r['peak_protection_implemented'])
        for key,lufs,tp in [('master_metrics',t.wav_lufs,t.wav_tp),('codec_metrics',t.mp3_lufs,t.mp3_tp)]:
            self.assertLessEqual(abs(r[key]['lufs_i']-lufs),.03)
            self.assertLessEqual(r[key]['true_peak_max_dbtp_estimate'],tp)
        self.assertEqual(before,engine.io.file_hash(self.source))
    def test_stricter_louder_mp3_does_not_change_wav(self):
        master=self.root/'master.wav'
        engine.peak.fit(self.source,master,self.root/'master_fit',-18,-2,self.ff)
        before=engine.io.file_hash(master)
        t=Targets(-18,-2,-12,-4)
        m,pcm,r=engine.make_codec_branch(master,self.root/'listen.wav',self.root/'listen.mp3',self.root,t,self.ff)
        self.assertTrue(r['limiter_engaged']);self.assertLessEqual(abs(m['lufs_i']+12),.03)
        self.assertLessEqual(m['true_peak_max_dbtp_estimate'],-4)
        self.assertEqual(before,engine.io.file_hash(master))
    def test_gain_only_branch(self):
        master=self.root/'master.wav';engine.peak.fit(self.source,master,self.root/'fit',-16,-2,self.ff)
        t=Targets(-16,-2,-22,-3)
        m,pcm,r=engine.make_codec_branch(master,self.root/'listen.wav',self.root/'listen.mp3',self.root,t,self.ff)
        self.assertFalse(r['limiter_engaged']);self.assertLessEqual(abs(m['lufs_i']+22),.03)
    def test_codec_failure_not_success(self):
        master=self.source
        with patch.object(engine.peak,'execute',side_effect=RuntimeError('codec failed')):
            with self.assertRaisesRegex(RuntimeError,'codec failed'):
                engine.make_codec_branch(master,self.root/'listen.wav',self.root/'listen.mp3',self.root,Targets(-12,-2,-26,-2),self.ff)
    def test_different_targets_not_stale_cache(self):
        one=Targets(-17,-3,-20,-3);two=Targets(-16,-4,-19,-4)
        a,pa=engine.run_file(self.source,self.root/'work',targets=one)
        b,pb=engine.run_file(self.source,self.root/'work',targets=two)
        self.assertNotEqual(pa,pb);self.assertLessEqual(abs(b['master_metrics']['lufs_i']+16),.03)
    def test_invalid_before_io(self):
        with self.assertRaises(ValueError):engine.run_file(self.root/'missing.wav',self.root/'bad',targets=Targets(wav_lufs=-100))
        self.assertFalse((self.root/'bad').exists())

if __name__=='__main__':unittest.main(verbosity=2)
