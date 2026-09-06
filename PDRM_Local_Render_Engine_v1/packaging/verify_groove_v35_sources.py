"""Source gate for isolated Groove-First Low-End v3.5 LAB."""
from pathlib import Path
import subprocess,sys,unittest
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
BASE='7d2632a01426e93af515f5bd4e91427745a2f7d2'
FROZEN=(
 'distribution_finish.py','hf_temporal_contrast_lab.py','note_sub_lab.py','note_sub_lab_v02.py',
 'auto_peak_v34.py','auto_conditioned_v34.py','natural_finish_v34.py','offline_peak_lab.py',
 'offline_peak_stream_v34.py','offline_peak_stream_v32.py','offline_peak_context_v34.py')

def main():
    paths=[':(top)PDRM_Local_Render_Engine_v1/'+p for p in FROZEN]
    changed=subprocess.check_output(['git','diff','--name-only',BASE,'HEAD','--',*paths],text=True).strip()
    assert not changed,'Accepted/current production path changed: '+changed
    suite=unittest.TestSuite()
    for mod in ('test_groove_lowend_v35','test_note_sub_v02','test_note_sub_v021_context','test_hf_temporal_contrast','test_auto_policy_v33','test_context_units'):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromName('tests.'+mod))
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    assert r.wasSuccessful() and r.testsRun>=66 and not r.skipped
if __name__=='__main__':main()
