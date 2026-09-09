"""Run actual replacement-entry tests and export reproducible small evidence."""
from pathlib import Path
import sys
import subprocess
import unittest
import importlib.metadata
import platform
import json
import shutil
import hashlib

BASE = 'b94bafca24ab5d6d511eff4f9e847a38a3613b97'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT)); sys.path.insert(0,str(ROOT/'tests'))
OUT = ROOT/'INTEGRATION40_EVIDENCE'
OUT.mkdir(exist_ok=True)
FROZEN = ('natural_finish.py','natural_finish_v34.py','auto_conditioned_v34.py',
    'distribution_finish.py','accepted_finish.py','hf_temporal_contrast_lab.py',
    'offline_peak_lab.py','offline_peak_stream_v34.py','offline_peak_stream_v32.py',
    'offline_peak_context_v34.py','auto_peak_v34.py','processed_finish.py',
    'workspace_cleanup.py','lowend_boundary_lab.py','event_decay_v39.py')


def main():
    checks = {}
    for name in FROZEN:
        before=subprocess.check_output(['git','show',BASE+':PDRM_Local_Render_Engine_v1/'+name],cwd=ROOT)
        after=(ROOT/name).read_bytes()
        checks[name]=before.replace(b'\r\n',b'\n')==after.replace(b'\r\n',b'\n')
    if not all(checks.values()):raise RuntimeError('Frozen files changed: '+str(checks))
    suite=unittest.TestSuite()
    old_patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py','test_event_decay39.py')
    old_count=0
    for pattern in old_patterns:
        part=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern)
        old_count+=part.countTestCases();suite.addTests(part)
    for pattern in ('test_integration40.py','test_integrated_chain40.py'):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    from test_integrated_chain40 import EVIDENCE
    import note_sub_lab as io
    ff=io.ffmpeg_path()
    report=dict(tests=result.testsRun,previous_tests=old_count,new_tests=result.testsRun-old_count,
        success=result.wasSuccessful() and not result.skipped and old_count==173,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        platform=platform.platform(),python=sys.version,base_commit=BASE,
        code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        versions={p:importlib.metadata.version(p) for p in ('numpy','scipy','soundfile','pyloudnorm','imageio-ffmpeg','psutil')},
        ffmpeg_version=subprocess.check_output([ff,'-version'],text=True).splitlines()[0],
        frozen_files=checks,integrated_cases=EVIDENCE,
        scope='Synthetic musical plan; real HE/AUTO/HFTC/codec execution. No neural inference or personal audio.',
        production_exe_changed=False,automatic_music_planner_complete=False,
        same_fundamental_synthesis_connected=False)
    (OUT/'RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    rows=[]
    for case in EVIDENCE:
        if 'wav_lufs' not in case:continue
        rows.append(f"| {case['case']} | {case['prep_route']} | {case['master_route']} | {case['wav_lufs']:.5f} | {case['wav_tp']:.5f} | {case['mp3_lufs']:.5f} | {case['mp3_tp']:.5f} |")
    text=f'''# PDRM 統合Step1 — 原音・物理音声・共通低域計画の接続

作成日: 2026-09-09。状態: 実行済み統合LAB。新しい本番EXEではありません。

## 今回の到達点

既存HE → 既存AUTO前段 → 新しい低域統合入口 → 既存HFTC → 既存AUTO最終 → MP3符号化・復号検査、を実際に実行する入口を追加しました。
旧Note-Subの発音抽出・生成呼出しは使いません。試験ではその3関数を呼ぶと例外になるようにして、経路の取り違えを検査しています。

ただし、処理計画は明示的なengineering_fixtureです。自動的に本人の好みを判断した結果ではありません。モデルがない場合に勝手な無加工成功へ縮退する入口も作っていません。

## 実装

1. `integration_contract_v40.py`：元ファイルと復号PCMの二つのhash、物理音声の親由来、SRC/補償遅延の有理数時計、整数フレーム区間、観測窓スケジューラ。
2. `lowend_coordinator_v40.py`：同じ物理snapshotからの候補だけを受理。共通の低域・中低域枝では減算を加算せず最大深さに統合。Boundary36の既存レンダラーを分割I/Oで一回使用。
3. `integrated_finish_v40.py`：明示的なplannerを必要とするLAB入口。共有モジュールの一時差替えを増やさず、既存DSPを直接呼出し。実保存後LUFS/TP/長さ検査、証跡、所有する一曲分の作業物を成功・失敗・キャンセル時に削除。

同一基音追加と狭帯域処理の共通予算アダプターは未接続です。非対応の操作を広いEQに置換せずエラーにします。この段階を、加算を含む音楽的制御器の完成と扱いません。

## 実行結果

プラットフォーム: {report['platform']}  
コードcommit: `{report['code_commit']}`  
比較基準: `{BASE}`

既存LAB {old_count}件 + 新規 {report['new_tests']}件 = {result.testsRun}件。成功: {report['success']}。失敗 {len(result.failures)}、エラー {len(result.errors)}、skip {len(result.skipped)}。

| 合成ケース | 前段AUTO | 最終AUTO | WAV LUFS | WAV TP推定 | MP3 LUFS | MP3 TP推定 |
|---|---|---|---:|---:|---:|---:|
{chr(10).join(rows)}

実WAV/MP3の値は全長約2.6秒の合成試験の測定です。実曲全長・主観音質・EXE内部モデル推論・処理速度の保証ではありません。
KEEP_EQUIVALENCEケースは、新入口の全KEEPと、同じHE/AUTO/HFTC/最終AUTOで低域を明示的に省いた比較経路の復号PCM一致を確認します。従来Note-Sub込みの旧マスターとの一致ではありません。

## 今回の重要な安全条件

- 原音と前処理後のファイルが異なることを、由来を持つsnapshotとして表します。ハッシュ照合を解除しません。
- `KEEP_SUPPORTED`と`ABSTAIN`を分けます。無加工であるという事実だけで、音楽的に良いと認定しません。
- 同じ帯域に1.5dBの要求が二つあっても、3dBへ積み上げません。これは制御上限であり、局所音質・TPの証明ではありません。
- 数秒単位のチャンクへ変えても、全曲先頭に固定した計画を使います。チャンク毎のラウドネス合わせをしません。
- 旧Note-Subを新経路の後ろへ残しません。
- 未対応の同一基音追加を搭載済みと表示しません。
- 欠落planner、I/O、非有限値、snapshot改変、キャンセルでは、別の音楽処理で隠さず停止します。
- 全KEEP時は低域段の入力ファイル自体と出力が完全一致。非ゼロ計画は、同じ既存レンダラーの一括計算と数値許容内で一致を検査します。
- 原音・既存processed・backupは掃除対象にしません。今回作った所有jobだけを削除します。

## 変えていないもの

基準から{len(FROZEN)}ファイルの一致を検査しました。既存HE/HFTC/OPPO、ミリ秒修正、通常版GUI/EXE、processed公開・掃除の既存経路を更新していません。
今回の出力先は別のINTEGRATION_LAB結果フォルダです。従来processedへの同名公開、再開機能、実worker/GUIは次の接続対象であり、今回完成済みではありません。

## 観測スケジューラの範囲

提案された候補区間から、8秒以下のcoreと前後contextを作ります。重複区間を整理し、曲端を処理し、coreとcontextを区別します。これは実行順の設計であり、発音を自動発見した結果、全曲分離が終わった記録ではありません。

## 残る工程

全曲のイベント抽出・関連成分の選択、研究モデルと用途条件の確定、実レビューを用いた校正、同一基音/狭帯域と共通予算の接続、完成音に対する候補評価、実曲回帰、Windows評価EXE、processed/中断再開/バッチ統合。
現版はenable_labが明示されない限り開始しません。一般配布版への入口を未完成のまま差し替えていません。

## 再現

このrepoのコードcommitをcheckoutし、`python packaging/verify_integration40.py`を実行します。依存ライブラリとFFmpegが必要です。モデル重みや個人音源は不要です。
成果物の`code/`は当該commitのPythonソース、`RESULTS.json`は実行結果、`SHA256SUMS.json`は同梱内容のhashです。
GitHubへ送ったものは一般化したコード・合成試験のみ。ユーザー音源・レビュー・参照atlas・モデル重みは送っていません。
'''
    (OUT/'PDRM_統合Step1_実装と実行結果_20260909.md').write_text(text,encoding='utf-8')
    for path in ROOT.glob('*.py'):
        dest=OUT/'code'/path.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,dest)
    for name in ('test_integration40.py','test_integrated_chain40.py'):
        dest=OUT/'code'/'tests'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/'tests'/name,dest)
    source_manifest={str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file()}
    (OUT/'SHA256SUMS.json').write_text(json.dumps(source_manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print('INTEGRATION40_SUMMARY '+json.dumps(report,ensure_ascii=False,allow_nan=False),flush=True)
    if not report['success']:raise SystemExit(1)


if __name__=='__main__':main()
