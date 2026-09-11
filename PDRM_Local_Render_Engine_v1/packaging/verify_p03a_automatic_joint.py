"""P03-A acceptance: automatic source events -> one joint-v46 plan."""
from pathlib import Path
import sys,json,unittest,subprocess,platform
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
OUT=ROOT/'P03A_EVIDENCE'

def main():
    OUT.mkdir(exist_ok=True)
    patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py','test_event_decay39.py','test_integration40.py','test_integrated_chain40.py','test_automatic41.py','test_joint42.py','test_processed_integration.py','test_crash_recovery_v43.py','test_gui_runtime_v44.py','test_same_fundamental46.py','test_automatic_joint48.py')
    suite=unittest.TestSuite();counts={}
    for p in patterns:
        q=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=p);counts[p]=q.countTestCases();suite.addTests(q)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    summary=dict(task='P03-A',tests=result.testsRun,counts=counts,success=result.wasSuccessful(),failures=[str(v) for v in result.failures],errors=[str(v) for v in result.errors],skipped=result.skipped,
        platform=platform.platform(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),private_music=False,real_spleeter_runtime=False,manual_event_times=False,production_release=False)
    (OUT/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    md=f'''# PDRM P03-A — 元2mixからjoint低域判断までの自動接続\n\n日付: 2026-09-12。Issue #10。commit `{summary['commit']}`。環境: {summary['platform']}。\n\n`source_events_v41`が元2mixから発音候補と周期候補を抽出し、planner自身がobserver窓を配置する。試験のrole observerは合成fixtureだが、発音時刻・pitch・修正区間を手入力していない。\n\nprepared 2mix上の過剰low/lowmid候補は既存reference boundaryと実observer permissionで絞り、候補量を同じphysical snapshotから有限比較する。その後、30–70Hzのsource periodic eventだけを同一基音候補として`physical_add_bridge_v46`で再確認する。octave-downは作らない。\n\n同一区間で広域low-cutとsame-fundamental addが競合した場合は、初期policyとして広域減算を優先してaddを明示抑止する。加算・減算を別processorで同時に走らせて自己相殺させない。重なる複数addは未解決としてPARTIAL/ABSTAINへ落とし、黙って足し合わせない。\n\nweak-present-fundamental、kick-only、vocal-like-low、rest-gap、110Hz非octave-down、過剰low＋弱基音競合、observer identity異常、原音不変、旧Note-Sub不使用、HE/AUTO/HFTC/WAV/MP3完成経路を検査した。\n\nソフトウェア試験は{summary['tests']}件。これは合成contractの技術受入であり、私有実曲での本人嗜好・量校正ではない。実Spleeter隔離runtimeを使うWindows統合試験は別workflowで受入し、P03親はP01復旧後の実曲評価までPARTIALとする。\n'''
    (OUT/'PDRM_P03A_自動joint判断_20260912.md').write_text(md,encoding='utf-8')
    print('P03A '+json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
