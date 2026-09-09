"""Run scanner/planner contracts and full finishing from source-only inputs."""
from pathlib import Path
import sys,os,json,shutil,unittest,subprocess,platform,hashlib,tempfile,argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
BASE='d37441b40ffd959316b712ed6015fb703e4bd84e'
OUT=ROOT/'AUTOMATIC41_EVIDENCE'


def save_json(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def run_chain(checkpoint=None):
    import automatic_lowend_v41 as ap
    import integrated_finish_v40 as finish
    import numpy as np
    import soundfile as sf
    from integration_contract_v40 import capture
    from test_automatic41 import song,save,calibration,FixtureRoles
    records=[]
    with tempfile.TemporaryDirectory(prefix='pdrm_auto41_') as tmp:
        root=Path(tmp);refs=root/'refs';refs.mkdir();bundle=calibration(refs)
        cases=(('NEURAL_OBSERVER',.5),) if checkpoint else (('AUTOMATIC_CUT',.5),('AUTOMATIC_KEEP',.03),('UNCERTAIN_VOICE',.5))
        for name,amp in cases:
            inputs=root/name;inputs.mkdir();p=save(inputs/'input.wav',song(low=amp));original=capture(p)
            observer=ap.ResearchDemucsObserver(checkpoint,research_use=True) if checkpoint else FixtureRoles('voice' if name=='UNCERTAIN_VOICE' else 'support')
            planner=ap.AutomaticRepairPlanner(bundle,observer,allow_fixture=not bool(checkpoint))
            # Enforce that no legacy note detector/generator/renderer is invoked.
            from unittest.mock import patch
            import note_sub_lab_v02 as old
            with patch.object(old,'collect_frames',side_effect=AssertionError('Legacy analysis called')),patch.object(old,'make_events',side_effect=AssertionError('Legacy event called')),patch.object(old,'render',side_effect=AssertionError('Legacy render called')):
                report,folder=finish.run_lab(p,root/'results',planner,enable_lab=True)
            assert original==capture(p)
            detail=planner.last_report
            assert detail and not detail['manual_event_times_used'] and detail['automatically_discovered_events']>0
            assert not list((root/'results').glob('.integration40_*'))
            assert abs(report['master_metrics']['lufs_i']+12)<.03
            assert abs(report['codec_metrics']['lufs_i']+14)<.03
            if name=='AUTOMATIC_CUT':assert report['lowend_report']['waveform_changed']
            if name in ('AUTOMATIC_KEEP','UNCERTAIN_VOICE'):assert not report['lowend_report']['waveform_changed']
            if name=='UNCERTAIN_VOICE':assert detail['assessment']=='ABSTAIN'
            if checkpoint:assert len(detail['observations'])>0 and all(v['neural_inference'] for v in detail['observations'])
            record=dict(case=name,assessment=detail['assessment'],events=detail['automatically_discovered_events'],
                observer_windows=len(detail['observations']),manual_event_times_used=False,
                waveform_changed=report['lowend_report']['waveform_changed'],
                raw_candidate_seconds=detail['raw_candidate_seconds'],supported_candidate_seconds=detail['supported_candidate_seconds'],
                selected_strength=detail['selected_strength'],prep_route=report['preparation']['auto_route'],
                master_route=report['master']['auto_route'],wav_lufs=report['master_metrics']['lufs_i'],
                wav_tp=report['master_metrics']['true_peak_max_dbtp_estimate'],mp3_lufs=report['codec_metrics']['lufs_i'],
                mp3_tp=report['codec_metrics']['true_peak_max_dbtp_estimate'],work_bytes_removed=report['work_bytes_removed'],
                source_unchanged=True,neural_inference=bool(checkpoint),observer_is_synthetic=not bool(checkpoint),
                calibration_is_synthetic=True,subjective_quality='NOT_EVALUATED',production_release=False)
            save_json(OUT/(name+'_DETAIL.json'),detail);save_json(OUT/(name+'_CHAIN.json'),report)
            records.append(record);print('SOURCE_DRIVEN_CASE '+json.dumps(record),flush=True)
    return records


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--neural-checkpoint');args=parser.parse_args()
    OUT.mkdir(exist_ok=True)
    old_patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py','test_event_decay39.py','test_integration40.py','test_integrated_chain40.py')
    frozen=('natural_finish.py','natural_finish_v34.py','auto_conditioned_v34.py','distribution_finish.py','accepted_finish.py','hf_temporal_contrast_lab.py','offline_peak_lab.py','offline_peak_stream_v34.py','offline_peak_stream_v32.py','offline_peak_context_v34.py','auto_peak_v34.py','processed_finish.py','workspace_cleanup.py','integration_contract_v40.py','integrated_finish_v40.py','lowend_coordinator_v40.py')
    matches={n:subprocess.check_output(['git','show',BASE+':PDRM_Local_Render_Engine_v1/'+n],cwd=ROOT).replace(b'\r\n',b'\n')==(ROOT/n).read_bytes().replace(b'\r\n',b'\n') for n in frozen}
    assert all(matches.values()),matches
    result=None
    if not args.neural_checkpoint:
        suite=unittest.TestSuite()
        for pattern in old_patterns+('test_automatic41.py',):suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
        result=unittest.TextTestRunner(verbosity=2).run(suite)
        save_json(OUT/'TEST_RESULTS.json',dict(tests=result.testsRun,success=result.wasSuccessful(),failures=[str(x) for x in result.failures],errors=[str(x) for x in result.errors],skipped=result.skipped))
        if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    cases=run_chain(args.neural_checkpoint)
    report=dict(scope='Source-driven scanner and candidate selection; synthetic music/reference corpus.',
        platform=platform.platform(),tests=None if result is None else result.testsRun,previous_tests=242,
        new_tests=None if result is None else result.testsRun-242,cases=cases,frozen_core=matches,
        code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        private_music_tested=False,manual_event_times_used=False,real_neural_inference=bool(args.neural_checkpoint),
        taste_calibrated=False,sub_synthesis_connected=False,narrow_budget_connected=False,
        production_exe_changed=False,success=True)
    save_json(OUT/'SUMMARY.json',report)
    rows='\n'.join(f"| {c['case']} | {c['events']} | {c['observer_windows']} | {c['assessment']} | {c['wav_lufs']:.5f} | {c['mp3_lufs']:.5f} |" for c in cases)
    text=f'''# PDRM 統合Step2 — 原音からの候補抽出・自動計画

日付: 2026-09-10。状態: 研究用統合経路。新EXEではありません。
検証commit: `{report['code_commit']}`。基準: `{BASE}`。
実行環境: {report['platform']}。

## 今回の差分

前回の手渡し処理計画に代わり、元音源から発音候補を抽出し、HE/AUTO後の実音声からヒット/持続低域の暫定超過を測定し、必要区間の役割観測を依頼して、候補を実描画してから量を選ぶplannerを接続しました。旧Note-Subを後ろに残していません。

`source_events_v41.py`は20ms包絡・10ms更新で立上がり候補を求め、別の最大256ms窓で周期性を観測します。更新幅は推定精度の保証ではありません。同じ音程の再発音を分け、拍へ移動せず、純音/周期音から発音許可を推論しません。音程変化だけで立上がりのない全レガートを認識したわけでもありません。

原音・実描画音のhash/PCM/時計を保持します。全曲の高レート波形や4本のstemを常駐・保存しません。有限音声読込で特徴列を作ります。8秒coreと重なりを用い、内部の窓端に観測の空白を作らず、実ファイル端の不足を観測済みにしません。

## 校正と量

今回の境界はbassについて明示的な好例を要求しますが、全曲役割コメントは弱いラベルのままです。絶対的な好みを学習したモデルではありません。候補は同じ物理音声から0.5/1.0強度を有限回描画して再測定し、暫定目標に到達した最小強度を選びます。上限でも未達ならPARTIAL、支持なし/有効な改善なしはABSTAINです。

今回は広い低域枝だけを統合しています。狭帯域の問題を広いEQへ偽装しません。同一基音加算・相対減衰の共通予算接続は未完了です。

## 実行結果

ソフトウェア試験: {report['tests']}。このレポートで実神経推論を実施: {report['real_neural_inference']}。

| ケース | 自動発見イベント数 | 観測窓 | 判定 | WAV LUFS | 復号MP3 LUFS |
|---|---:|---:|---|---:|---:|
{rows}

入力と校正音は合成音です。手入力の発音時刻・制御曲線はplannerへ渡していません。機械試験の役割観測はsynthetic_roles41と明示し、通常APIがその利用を拒否します。別の神経推論試験は実研究checkpointを使い、その結果がABSTAINであっても健康判定にはしません。合成音を正しく分離できたことや実曲の聴感改善を、この接続試験だけから主張しません。

既存HE/HFTC/AUTO/OPPO、保存、通常EXEの{len(frozen)}ファイルが未変更です。新経路の成功/失敗/キャンセルの一曲所有作業領域の掃除を保持します。新plannerの候補一時音声も選択終了後に削除します。

## 残課題

実曲・実参照の校正と回帰、実発音と関連成分の意味的対応、同一基音の適量、狭帯域との共通予算、配布条件が確認できたモデル、GUI/processed/強制終了再開、最終EXE実推論。研究checkpointは同梱せず、私有音源やレビューをCIへ送信していません。

## 再現

検証commitをcheckoutし、`python packaging/verify_automatic41.py`。追加の実神経接続試験はローカルの研究checkpointを明示して `--neural-checkpoint PATH`。実行条件はworkflowに固定。曲名ホワイトリストや隠れた既定KEEPはありません。
'''
    (OUT/'PDRM_統合Step2_自動候補と実行結果_20260910.md').write_text(text,encoding='utf-8')
    for p in ROOT.glob('*.py'):
        dst=OUT/'code'/p.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
    for p in (ROOT/'tests').glob('test_*.py'):
        dst=OUT/'code'/'tests'/p.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
    dst=OUT/'code'/'packaging'/'verify_automatic41.py';dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(__file__,dst)
    save_json(OUT/'SHA256SUMS.json',{str(p.relative_to(OUT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.rglob('*') if p.is_file() and p.name!='SHA256SUMS.json'})
    print('AUTOMATIC41_SUMMARY '+json.dumps(report),flush=True)

if __name__=='__main__':main()
