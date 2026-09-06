"""Verify v3.3 AUTO policy without changing accepted/v3.2 sound modules."""
from pathlib import Path
import importlib.metadata,json,os,subprocess,sys,unittest
root=Path.cwd();sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
import offline_peak_stream as selected
import accepted_finish as af

def main():
    af.verify_dsp();selected.verify_kernel();base='804aa08c845e78206125e11af36fce8d72bf5d51'
    frozen=['offline_peak_lab.py','offline_peak_stream.py','offline_peak_rescue.py','offline_peak_stream_v31.py','offline_peak_context.py','offline_peak_stream_v32.py',
        'natural_finish.py','natural_finish_v31.py','natural_finish_v32.py','note_sub_conditioned.py','note_sub_lab.py','note_sub_lab_v02.py','hf_temporal_contrast_lab.py',
        'accepted_finish.py','distribution_finish.py','distribution_peak.py','processed_finish.py','processed_finish_v32.py','workspace_cleanup.py',
        'pdrm_engine','pdrm_runtime','pdrm_operator_lab']
    if not os.environ.get('PDRM_LOCAL_NO_GIT'):
        paths=[':(top)PDRM_Local_Render_Engine_v1/'+p for p in frozen]
        changed=subprocess.check_output(['git','diff','--name-only',base,'HEAD','--',*paths],text=True).strip()
        assert not changed,'Frozen/previous module changed: '+changed
    suite=unittest.TestSuite()
    for pattern in ('test_note_sub*.py','test_hf_temporal_contrast.py','test_accepted_finish.py','test_distribution_finish.py','test_processed_finish.py','test_target_controls.py',
        'test_offline_peak_lab.py','test_offline_peak_stream.py','test_offline_peak_rescue.py','test_offline_peak_context.py','test_auto_policy_v33.py'):
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=r.testsRun,ok=r.wasSuccessful(),failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped),python=sys.version,platform=sys.platform,
        kernel_sha256=selected.verify_kernel(),v33='AUTO: GAIN_ONLY -> OPPO -> LIMITER ONLY AFTER NotFeasible; operational errors stop',
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    Path('SOURCE_TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sys.exit(0 if r.wasSuccessful() and r.testsRun>=254 and not r.skipped else 1)
if __name__=='__main__':main()
