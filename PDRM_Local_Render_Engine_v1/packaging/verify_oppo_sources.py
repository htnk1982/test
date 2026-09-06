"""All existing tests plus whole-track OPPO tests; no private audio in CI."""
from pathlib import Path
import importlib.metadata,json,os,subprocess,sys,unittest
root=Path.cwd();sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
import offline_peak_stream as op
import accepted_finish as af

def main():
    af.verify_dsp();op.verify_kernel()
    base='32d8cbe136739ae0a6bbb194047e5c3f6e072273'
    frozen=['offline_peak_lab.py','note_sub_lab.py','note_sub_lab_v02.py','hf_temporal_contrast_lab.py',
            'accepted_finish.py','distribution_finish.py','distribution_peak.py',
            'pdrm_engine','pdrm_runtime','pdrm_operator_lab']
    if not os.environ.get('PDRM_LOCAL_NO_GIT'):
        paths=[':(top)PDRM_Local_Render_Engine_v1/'+p for p in frozen]
        assert not subprocess.check_output(['git','diff','--name-only',base,'HEAD','--',*paths],text=True).strip()
    suite=unittest.TestSuite()
    for pattern in ('test_note_sub*.py','test_hf_temporal_contrast.py','test_accepted_finish.py',
            'test_distribution_finish.py','test_processed_finish.py','test_target_controls.py',
            'test_offline_peak_lab.py','test_offline_peak_stream.py'):
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=result.testsRun,ok=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),
        skipped=len(result.skipped),python=sys.version,platform=sys.platform,kernel_sha256=op.verify_kernel(),
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    Path('SOURCE_TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sys.exit(0 if result.wasSuccessful() and result.testsRun>=217 and not result.skipped else 1)
if __name__=='__main__':main()
