"""P04-A acceptance: same-fundamental only, physical remeasure, final chain."""
from pathlib import Path
import sys,json,unittest,subprocess,platform
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
OUT=ROOT/'P04A_EVIDENCE'

def main():
    OUT.mkdir(exist_ok=True)
    patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py','test_event_decay39.py','test_integration40.py','test_integrated_chain40.py','test_automatic41.py','test_joint42.py','test_processed_integration.py','test_crash_recovery_v43.py','test_gui_runtime_v44.py','test_same_fundamental46.py')
    suite=unittest.TestSuite()
    counts={}
    for p in patterns:
        q=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=p);counts[p]=q.countTestCases();suite.addTests(q)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    summary=dict(task='P04-A',tests=result.testsRun,counts=counts,success=result.wasSuccessful(),
        failures=[str(v) for v in result.failures],errors=[str(v) for v in result.errors],skipped=result.skipped,
        platform=platform.platform(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        private_music=False,neural_inference=False,personal_taste_calibrated=False,production_release=False)
    (OUT/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    md=f'''# PDRM P04-A — 同一基音補強の共同経路接続\n\n日付: 2026-09-10。Issue #9。commit `{summary['commit']}`。環境: {summary['platform']}。\n\n原音observerが同じ55Hz発音・bass role・周期性を支持し、HE/AUTO後の実物理音声で55Hzが同じ発音の倍音群に対して不足する場合だけ、位相・必要量・headroomを物理音声から再測定して補強proposalを作る。110→55Hzは新octaveとして拒否する。missing-fundamental生成は未実装のまま。\n\n共同rendererは既存joint-v42を変更せず新`joint-v46`として追加した。広域low-cutと同じsupported区間へsubを足す自己相殺plan、重なる複数sub発音を拒否する。減算がない場合の共同処理、誤音程、非bass role、既に十分な基音、observer内部の不確実区間、原音非破壊を検査。分離stem samplesは出力へ使わない。\n\n実HE/AUTO/HFTC/最終WAV/MP3まで`joint-v46`で通し、旧Note-Subが呼ばれないこと、same-fundamental additionが1件実行されること、指定TP条件と中間作業物削除を確認した。入力・役割観測は合成fixtureであり、本人の実曲に対する量の好みやステムmodelの正確性は未評価。\n\nソフトウェア試験は{summary['tests']}件。件数を製品完成率へ換算しない。P04-Aが閉じてもP04親には、実曲の成分関連付けと本人嗜好に基づく量校正、product plannerへの自動接続が残る。\n'''
    (OUT/'PDRM_P04A_同一基音接続_20260910.md').write_text(md,encoding='utf-8')
    print('P04A '+json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
