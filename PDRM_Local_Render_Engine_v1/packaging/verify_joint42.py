"""Validate joint backend, physical bridge and unchanged production DSP."""
from pathlib import Path
import sys,json,unittest,subprocess,platform,shutil,hashlib
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
BASE='1b651fbb5f752a99dfff3c49791df0ad2154c4bc'
OUT=ROOT/'JOINT42_EVIDENCE'

def main():
    OUT.mkdir(exist_ok=True)
    frozen=('natural_finish.py','natural_finish_v34.py','auto_conditioned_v34.py','distribution_finish.py','accepted_finish.py','hf_temporal_contrast_lab.py','offline_peak_lab.py','offline_peak_stream_v34.py','offline_peak_stream_v32.py','offline_peak_context_v34.py','auto_peak_v34.py','processed_finish.py','workspace_cleanup.py','source_events_v41.py','automatic_lowend_v41.py','lowend_coordinator_v40.py','event_decay_v39.py')
    matches={n:subprocess.check_output(['git','show',BASE+':PDRM_Local_Render_Engine_v1/'+n],cwd=ROOT).replace(b'\r\n',b'\n')==(ROOT/n).read_bytes().replace(b'\r\n',b'\n') for n in frozen}
    assert all(matches.values()),matches
    previous=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py','test_event_decay39.py','test_integration40.py','test_integrated_chain40.py','test_automatic41.py')
    suite=unittest.TestSuite()
    for p in previous:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=p))
    old=suite.countTestCases();assert old==277,old
    new=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_joint42.py');new_count=new.countTestCases();suite.addTests(new)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(tests=result.testsRun,previous_tests=old,new_tests=new_count,success=result.wasSuccessful(),failures=[str(v) for v in result.failures],errors=[str(v) for v in result.errors],skipped=result.skipped,platform=platform.platform(),production_files_unchanged=matches,
        changed_existing_lab='integrated_finish_v40.py: explicit backend registry and report provenance',
        source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),private_music_tested=False,neural_inference=False)
    (OUT/'TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    from joint42_selftest import run_selftest
    r=run_selftest(OUT/'source_pipeline');report['pipeline']=r
    (OUT/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    rows='\n'.join(f"| {v['case']} | {v['narrow_operations']} | {v['master_route']} | {v['wav_lufs']:.5f} | {v['mp3_lufs']:.5f} | {v['target_to_peer_db']:.4f} |" for v in r['cases'])
    md=f'''# PDRM Integration42 — 共通予算・物理音声再確認・EXE前の結合試験

日付: 2026-09-10。状態: LAB実装。新しいユーザー向けEXEではない。
検証commit: `{report['source_commit']}`。基準: `{BASE}`。

## 今回の実装

広い低域・中低域のFIR処理を維持し、狭帯域の要求について既に満たされた減衰分を差し引く共通描画器を追加した。同じ周波数への1.5dB要求を二つ足して3dBにしない。すべての差分は同じ物理音声から求め、処理済み音を別の処理器へ繰り返し渡さない。

狭帯域要求がない場合は従来の広域描画へそのまま委譲する。狭帯域を使う場合はフレームごとの周波数応答から不足分を計算し、各操作固有の時間窓で差分を局所化する。別の操作が有効な時刻でも、対象外の発音や未支持区間へ差分を広げない。

共通上限はフレーム応答上2dB、狭帯域個別上限は1.5dB。これを完成波形の全局所帯域・True Peak・聴感に対する数学的保証とはしない。実際の音声を再検査する。

## 原音と前処理後の役割

原音側の相対減衰に対する発音許可を受け取り、HE/AUTO後の実音声でも関連成分との減衰差を測り直す。前処理で問題が解消した場合は追加減算しない。原音の観測hashを物理音声のhashへ書き換えず、両者の親関係・整数フレーム対応を保持する。

このbridgeは、event_decay_v39の発音・成分仮説と校正済みatlasを受け取る。任意の実曲から比較すべき部分音群を正しく自動発見できたという結果ではない。今回の局所ラベルと役割支持は合成試験用と明示した。

## 実行結果

ソフトウェア試験: {report['tests']}件（既存{old}+新規{new_count}）、成功。環境: {report['platform']}。

| 合成ケース | 狭帯域操作数 | 最終経路 | WAV LUFS | 復号MP3 LUFS | 完成WAVの対象/関連成分 dB |
|---|---:|---|---:|---:|---:|
{rows}

原音の欠点が前処理後にも残るケース、解消済みのケース、無加工、同じ操作の重複、異なる操作の時間境界、内部の未支持区間、サンプルレート対応、キャンセル後始末を含む。最終HFTC/AUTO/PCM24/MP3と実際に接続したが、個人の実曲改善・主観合格とは別。

## 不変更と出荷上の限界

既存の本番HE/HFTC/OPPO、GUI/processed、基音合成器、既存広域plannerは変更していない。変更した既存ファイルはLAB統合入口で、明示的に選んだjoint-v42を呼べるようにした。一般公開の処理入口をこのLABへ切り替えていない。

全曲のステムをWAVへ保存しない。狭帯域の差分描画は最大2秒の出力ブロックと有限の文脈を読み、同時に扱う操作数へ容量上限を設ける。容量超過は無言で間引かない。長時間実曲バッチの実測は未完了。

ローカル実行環境が応答しないためGitHub Actionsで検証した。個人音源・Excel・参照データを公開repoやCIへ送っていない。実曲校正、全曲の成分関連付け、同一基音追加の共通予算、配布モデル選定、GUIと中断再開の本番統合は残る。

## 数値手法の一次資料

SciPyのNOLA/ISTFT条件: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.istft.html
PyInstallerのフォルダ配布と実行時ファイル位置: https://pyinstaller.org/en/stable/operating-mode.html

これらは数値再構成と配布方式の根拠であり、音楽的な好み適合を証明するものではない。別ジョブでQA専用のWindows EXEを作る場合も、利用者向けマスタリングEXEの完成とは分けて記録する。
'''
    (OUT/'PDRM_Integration42_共通予算と実行検証_20260910.md').write_text(md,encoding='utf-8')
    for path in ROOT.glob('*.py'):
        dest=OUT/'code'/path.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    for path in (ROOT/'tests').glob('*.py'):
        dest=OUT/'code'/'tests'/path.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    dest=OUT/'code'/'packaging'/'verify_joint42.py';dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(__file__,dest)
    print('JOINT42_SUMMARY '+json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
