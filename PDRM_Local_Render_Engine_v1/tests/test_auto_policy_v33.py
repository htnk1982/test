from pathlib import Path
import shutil,sys,tempfile,unittest
from unittest.mock import patch
import numpy as np
import soundfile as sf
sys.path.insert(0,str(Path(__file__).resolve().parents[1]));sys.path.insert(0,str(Path(__file__).parent))
import auto_peak_v33 as auto
import auto_conditioned_v33 as conditioned
import natural_finish_v33 as natural
import offline_peak_lab as kernel
from target_settings import Targets
from test_offline_peak_lab import mixture

SR=48000

def quiet(seconds=1.0):
    t=np.arange(round(SR*seconds))/SR
    x=np.column_stack((.05*np.sin(2*np.pi*220*t),.045*np.sin(2*np.pi*223*t)))
    x[:128]=0;x[-128:]=0
    return x

class AutoPeakPolicy(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'src.wav';sf.write(self.src,quiet(),SR,subtype='FLOAT')
    def tearDown(self):self.tmp.cleanup()
    def test_gain_only_first(self):
        out=self.root/'gain.wav';r=auto.fit(self.src,out,self.root/'g',-24,-2)
        self.assertEqual(r['auto_route'],'GAIN_ONLY');self.assertFalse(r['conventional_limiter_used'])
    def test_selected_oppo_before_limiter(self):
        p=self.root/'mix.wav';sf.write(p,mixture(),SR,subtype='FLOAT');out=self.root/'oppo.wav'
        r=auto.fit(p,out,self.root/'o',-12,-2)
        self.assertEqual(r['auto_route'],'OPPO');self.assertFalse(r['conventional_limiter_used'])
    def test_only_notfeasible_can_fallback(self):
        out=self.root/'fallback.wav';metrics=dict(lufs_i=-12.,true_peak_max_dbtp_estimate=-2.1,frames=sf.info(self.src).frames,samplerate=SR,channels=2)
        def lim(src,dest,*a,**k):shutil.copyfile(src,dest);return dict(limiter_engaged=True)
        with patch.object(auto.oppo,'fit',side_effect=kernel.NotFeasible('naturalness veto')),patch.object(auto.limiter,'fit',side_effect=lim),patch.object(auto,'_verify',return_value=metrics):
            r=auto.fit(self.src,out,self.root/'f',-12,-2)
        self.assertEqual(r['auto_route'],'LIMITER_FALLBACK');self.assertTrue(r['conventional_limiter_used']);self.assertIn('naturalness veto',r['limiter_fallback_reason'])
    def test_runtime_error_never_falls_back(self):
        with patch.object(auto.oppo,'fit',side_effect=RuntimeError('corrupt cache')),patch.object(auto.limiter,'fit') as lim:
            with self.assertRaisesRegex(RuntimeError,'corrupt cache'):auto.fit(self.src,self.root/'x.wav',self.root/'x',-12,-2)
            lim.assert_not_called()
    def test_cancel_never_falls_back(self):
        with patch.object(auto.oppo,'fit',side_effect=InterruptedError('cancel')),patch.object(auto.limiter,'fit') as lim:
            with self.assertRaises(InterruptedError):auto.fit(self.src,self.root/'x.wav',self.root/'x',-12,-2)
            lim.assert_not_called()
    def test_fallback_receipt_resumes_without_reclassifying(self):
        out=self.root/'resume.wav';metrics=dict(lufs_i=-12.,true_peak_max_dbtp_estimate=-2.1,frames=sf.info(self.src).frames,samplerate=SR,channels=2)
        def lim(src,dest,*a,**k):shutil.copyfile(src,dest);return dict(limiter_engaged=True)
        with patch.object(auto.oppo,'fit',side_effect=kernel.NotFeasible('veto')),patch.object(auto.limiter,'fit',side_effect=lim),patch.object(auto,'_verify',return_value=metrics):auto.fit(self.src,out,self.root/'r',-12,-2)
        with patch.object(auto.oppo,'fit') as oppo,patch.object(auto.limiter,'fit') as lim,patch.object(auto,'_verify',return_value=metrics):
            r=auto.fit(self.src,out,self.root/'r',-12,-2)
        self.assertEqual(r['rerun_status'],'IDEMPOTENT_SKIP');oppo.assert_not_called();lim.assert_not_called()

class AutoConditionAndIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.src=self.root/'mix.wav';sf.write(self.src,mixture(),SR,subtype='FLOAT')
    def tearDown(self):self.tmp.cleanup()
    def test_conditioner_keeps_shadow_decision_and_auto_physical_route(self):
        out,r=conditioned.run(self.src,self.root/'cond')
        self.assertTrue(out.is_file());self.assertEqual(r['analysis_anchor_lufs'],-14.0)
        self.assertIn(r['prep_route'],('GAIN_ONLY','OPPO','LIMITER_FALLBACK'))
        self.assertEqual(r['prep_limiter_used'],r['prep_route']=='LIMITER_FALLBACK')
    def test_full_v33_reports_actual_routes(self):
        r,out=natural.run_file(self.src,self.root/'finish',targets=Targets(-18,-2,-20,-3),write_mp3=False)
        self.assertEqual(r['preparation'],'auto_safe');self.assertEqual(r['preparation_policy'],'GAIN_ONLY -> OPPO -> LIMITER_ONLY_AFTER_NOT_FEASIBLE')
        self.assertIn(r['preparation_route'],('GAIN_ONLY','OPPO','LIMITER_FALLBACK'));self.assertIn(r['master_route'],('GAIN_ONLY','OPPO','LIMITER_FALLBACK'))
        natural.verify_final(out,r['identity'])
    def test_gui_has_no_peak_mode_selector(self):
        text=Path(__file__).resolve().parents[1].joinpath('natural_gui_v33.py').read_text(encoding='utf-8')
        self.assertNotIn('legacy_peak',text);self.assertNotIn('Combobox',text)
    def test_cleanup_reclaims_v32_for_same_source(self):
        old=self.root/'oppo_finish_v32'/'.oppo_work_v3'/'old';old.mkdir(parents=True)
        natural.io.atomic_json(old/'identity.json',dict(source_sha256=natural.io.file_hash(self.src),version='natural-finish-3.2.0'));(old/'big.wav').write_bytes(b'0'*4096)
        current=self.root/'oppo_finish_v33';current.mkdir();natural.cleanup_source_workspace(self.src,current,prestart=True)
        self.assertFalse(old.exists())

if __name__=='__main__':unittest.main(verbosity=2)
