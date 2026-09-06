"""Frozen sound-stage boundaries plus all source regressions for target GUI v2.2."""
from pathlib import Path
import ast
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
import unittest

ROOT=Path.cwd().resolve()
sys.path.insert(0,str(ROOT))
BASE='1651c55a80f8c759661ccd727e20a7c9f0132eb1'

def main():
    import accepted_finish
    accepted_finish.verify_dsp()
    frozen=['accepted_finish.py','note_sub_lab.py','note_sub_lab_v02.py','hf_temporal_contrast_lab.py',
            'pdrm_engine','pdrm_runtime','pdrm_operator_lab']
    args=['git','diff','--name-only',BASE,'HEAD','--']+[':(top)PDRM_Local_Render_Engine_v1/'+p for p in frozen]
    assert not subprocess.check_output(args,text=True).strip(),'Frozen sound or production module changed'
    # Only output orchestration and the finite gain solver may change. Verify
    # the exact signal transforms and timing against the last shipped source.
    for module,names in [('distribution_finish.py',('harmonic_elasticity','render_harmonic','write_pcm24')),
                          ('distribution_peak.py',('render_limited','measure','execute'))]:
        old=subprocess.check_output(['git','show',BASE+':PDRM_Local_Render_Engine_v1/'+module],text=True,encoding='utf-8')
        def functions(text):
            return {node.name:ast.dump(node,include_attributes=False) for node in ast.parse(text).body if isinstance(node,ast.FunctionDef)}
        before,after=functions(old),functions((ROOT/module).read_text(encoding='utf-8'))
        for name in names:assert before[name]==after[name],f'Signal transform changed: {module}:{name}'
    suite=unittest.TestSuite()
    for pattern in ('test_note_sub*.py','test_hf_temporal_contrast.py','test_accepted_finish.py',
                    'test_distribution_finish.py','test_processed_finish.py','test_target_controls.py'):
        suite.addTests(unittest.defaultTestLoader.discover('tests',pattern=pattern))
    r=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=r.testsRun,ok=r.wasSuccessful(),failures=len(r.failures),errors=len(r.errors),
                skipped=len(r.skipped),python=sys.version,platform=sys.platform,
                frozen_signal_functions='MATCH_BASELINE_AST',
                versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    Path('SOURCE_TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not (r.wasSuccessful() and r.testsRun==167 and not r.skipped):raise SystemExit(1)

if __name__=='__main__':main()
