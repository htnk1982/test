"""Verify v3.4 sparse-exact OPPO execution while freezing v3.3 and earlier."""
from pathlib import Path
import importlib.metadata,json,os,subprocess,sys,unittest
root=Path.cwd();sys.path.insert(0,str(root));sys.path.insert(0,str(root/'tests'))
import offline_peak_stream as selected
import accepted_finish as af

def main():
    af.verify_dsp();selected.verify_kernel();base='cb81ba442e8957977db41be51dc2446d0a20ca11'
    frozen=['offline_peak_lab.py','offline_peak_stream.py','offline_peak_rescue.py','offline_peak_stream_v31.py','offline_peak_context.py','offline_peak_stream_v32.py',
        'auto_peak_v33.py','auto_conditioned_v33.py','natural_finish_v33.py','natural_gui_v33.py','natural_exe_entry_v33.py',
        'natural_finish.py','natural_finish_v31.py','natural_finish_v32.py','note_sub_conditioned.py','note_sub_lab.py','note_sub_lab_v02.py','hf_temporal_contrast_lab.py',
        'accepted_finish.py','distribution_finish.py','distribution_peak.py','processed_finish.py','processed_finish_v32.py','workspace_cleanup.py','pdrm_engine','pdrm_runtime','pdrm_operator_lab']
    if not os.environ.get('PDRM_LOCAL_NO_GIT'):
        paths=[':(top)PDRM_Local_Render_Engine_v1/'+p for p in frozen];changed=subprocess.check_output(['git','diff','--name-only',base,'HEAD','--',*paths],text=True).strip();assert not changed,'Frozen/previous module changed: '+changed
    suite=unittest.TestSuite()
    for pattern in ('test_note_sub*.py','test_hf_temporal_contrast.py','test_accepted_finish.py','test_distribution_finish.py','test_processed_finish.py','test_target_controls.py',
        'test_offline_peak_lab.py','test_offline_peak_stream.py','test_offline_peak_rescue.py','test_offline_peak_context.py','test_auto_policy_v33.py','test_oppo_performance_v34.py'):
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=r.testsRun,ok=r.wasSuccessful(),failures=len(r.failures),errors=len(r.errors),skipped=len(r.skipped),python=sys.version,platform=sys.platform,
        kernel_sha256=selected.verify_kernel(),v34='SPARSE EXACT principal-block long-context solver + visible progress; AUTO safety policy unchanged',
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    Path('SOURCE_TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    sys.exit(0 if r.wasSuccessful() and r.testsRun>=260 and not r.skipped else 1)
if __name__=='__main__':main()
