"""Developer-only runner for the extracted single-process GUI exercise.

No firewall changes or OS input injection. This tests packaged startup, real
inference, GUI rendering and local storage, not native hard cancellation.
"""
from pathlib import Path
import json
import os
import subprocess
import sys

bundle,fixture,evidence = (Path(x).resolve() for x in sys.argv[1:4])
report = dict(scope='packaged_single_process_gui_cpu_only', outcome='running', runs=[],
              npu_tested=False, live_tested=False, hard_timeout_tested=False,
              network_isolation_tested=False, product_release_approved=False, binary_exported=False)
try:
    for name in ('first_process','fresh_process'):
        target=evidence/name
        target.mkdir()
        output=bundle.parent/name
        result=subprocess.run([str(bundle/'LocalScribeNPU.exe'),'--exercise',str(fixture),
                               '--evidence',str(target),'--output',str(output)],
                              cwd=str(bundle.parent),timeout=420,check=False)
        data=json.loads((target/'ui-result.json').read_text(encoding='utf-8'))
        report['runs'].append(data)
        if result.returncode != 0 or data.get('outcome')!='passed':
            raise RuntimeError('Packaged GUI exercise failed: '+json.dumps(data,ensure_ascii=False))
    report['outcome']='packaged_gui_cpu_passed_partial_gate'
except Exception as exc:
    report.update(outcome='failed',error_type=type(exc).__name__,error=str(exc)[:10000])
(evidence/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
(evidence/'SUMMARY.md').write_text('# LocalScribe packaged GUI gate\n\n'+report['outcome']+
    '\n\nNot target-NPU/live acceptance. Cancellation is cooperative; native compilation has no hard cancellation.\n',encoding='utf-8')
print('FROZEN_GUI_RESULT:',json.dumps(report,ensure_ascii=False),flush=True)
raise SystemExit(0 if report['outcome']=='packaged_gui_cpu_passed_partial_gate' else 1)
