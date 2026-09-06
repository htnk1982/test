"""Verify OPPO v3.1 extension without rewriting the selected v0.1 path."""
from pathlib import Path
import importlib.metadata,json,os,subprocess,sys,unittest
root=Path.cwd();sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
import offline_peak_stream as oldstream
import accepted_finish as af

def main():
    af.verify_dsp();oldstream.verify_kernel()
    base='b1702ca788f02c1cc8131ee7b9a519a446599617'
    frozen=['offline_peak_lab.py','offline_peak_stream.py','natural_finish.py','note_sub_lab.py','note_sub_lab_v02.py',
            'hf_temporal_contrast_lab.py','accepted_finish.py','distribution_finish.py','distribution_peak.py',
            'pdrm_engine','pdrm_runtime','pdrm_operator_lab']
    if not os.environ.get('PDRM_LOCAL_NO_GIT'):
        paths=[':(top)PDRM_Local_Render_Engine_v1/'+p for p in frozen]
        changed=subprocess.check_output(['git','diff','--name-only',base,'HEAD','--',*paths],text=True).strip()
        assert not changed,'Selected/frozen module changed: '+changed
    suite=unittest.TestSuite()
    for pattern in ('test_note_sub*.py','test_hf_temporal_contrast.py','test_accepted_finish.py',
            'test_distribution_finish.py','test_processed_finish.py','test_target_controls.py',
            'test_offline_peak_lab.py','test_offline_peak_stream.py','test_offline_peak_rescue.py'):
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=result.testsRun,ok=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),
        skipped=len(result.skipped),python=sys.version,platform=sys.platform,kernel_sha256=oldstream.verify_kernel(),
        rescue_extension='ONLY_AFTER_OLD_POINTWISE_BUDGET_FAILURE',
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    Path('SOURCE_TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() and result.testsRun>=230 and not result.skipped else 1)
if __name__=='__main__':main()
