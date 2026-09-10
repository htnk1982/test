"""Run the existing LAB regression and the concrete P07-A acceptance task.

Only generated fixtures are used on CI. This closes a publication adapter task,
not musical calibration, private-corpus access, GUI or release acceptance.
"""
from pathlib import Path
import sys,unittest,subprocess,json,tempfile,shutil,platform
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
BASE='c1fed72d6955bc5f749635affb92fb9ae733dee4'
OUT=ROOT/'RELEASE_EXECUTION_EVIDENCE'


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def acceptance():
    import soundfile as sf
    import processed_integration as subject
    from joint42_selftest import FixturePlanner
    from decay39_fixtures import audio_fixture
    from target_settings import Targets
    from integration_contract_v40 import capture
    from unittest.mock import patch
    import note_sub_lab_v02 as old
    records=[]
    with tempfile.TemporaryDirectory(prefix='pdrm_p07a_') as tmp:
        root=Path(tmp);inp=root/'元音源 日本語';inp.mkdir();work=root/'work'
        _,bad,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.)
        source=inp/'01 曲名.wav';sf.write(source,bad,48000,subtype='DOUBLE')
        original=capture(source);planner=FixturePlanner('tail')
        def run(**kw):
            # Only the forbidden legacy functions are mocked, never the new
            # pipeline, publisher, final processing or codec in this acceptance.
            with patch.object(old,'collect_frames',side_effect=AssertionError('old detector')),\
                 patch.object(old,'make_events',side_effect=AssertionError('old events')),\
                 patch.object(old,'render',side_effect=AssertionError('old renderer')):
                return subject.run_file(source,work,planner=planner,enable_lab=True,**kw)
        first,folder=run()
        evidence=json.loads(Path(first['processing_evidence']).read_text(encoding='utf-8'))
        assert set(first['files'])=={'01 曲名.wav','01 曲名.mp3'}
        assert evidence['output_files']==first['files']
        assert abs(first['master_metrics']['lufs_i']+12)<.03
        assert abs(first['codec_metrics']['lufs_i']+14)<.03
        assert first['master_metrics']['true_peak_max_dbtp_estimate']<=-2
        assert first['codec_metrics']['true_peak_max_dbtp_estimate']<=-2
        assert not list(work.glob('.publish-integration-*'))
        records.append(dict(case='NEW_CHAIN_TO_PROCESSED',publication_complete=True,
            wav_lufs=first['master_metrics']['lufs_i'],wav_tp=first['master_metrics']['true_peak_max_dbtp_estimate'],
            mp3_lufs=first['codec_metrics']['lufs_i'],mp3_tp=first['codec_metrics']['true_peak_max_dbtp_estimate'],
            lowend_assessment=first['lowend_assessment'],quality_status=first['quality_status'],
            copied_without_reencoding=True,final_cache_removed=True,old_note_sub_called=False))
        again,_=run();assert again['rerun_status']=='IDEMPOTENT_SKIP'
        records.append(dict(case='SAME_REQUEST_REPLAY',rerun_status=again['rerun_status'],files_unchanged=again['files']==first['files']))
        replaced,_=run(targets=Targets(wav_lufs=-13.),replace_managed=True)
        backup=Path(replaced['backup'])
        assert subject.io.file_hash(backup/'01 曲名.wav')==first['files']['01 曲名.wav']
        assert subject.io.file_hash(backup/'01 曲名.mp3')==first['files']['01 曲名.mp3']
        assert abs(replaced['master_metrics']['lufs_i']+13)<.03
        records.append(dict(case='SETTINGS_CHANGE_WITH_BACKUP',backup_hashes_match=True,
            wav_lufs=replaced['master_metrics']['lufs_i'],quality_status=replaced['quality_status']))
        assert original==capture(source)
        second=inp/'02 中断試験.wav';second.write_bytes(source.read_bytes());source=second
        try:
            run(interrupt_after=1)
        except RuntimeError as exc:
            assert 'TEST_INTERRUPTION_PUBLISH_1' in str(exc),str(exc)
        else:
            raise AssertionError('Interruption not exercised')
        assert (folder/'02 中断試験.wav').exists() and not (folder/'02 中断試験.mp3').exists()
        assert not list(work.glob('.publish-integration-*'))
        resumed,_=run()
        assert resumed['status']=='COMPLETE' and (folder/'02 中断試験.mp3').exists()
        assert not list(work.glob('.publish-integration-*'))
        records.append(dict(case='NORMAL_INTERRUPTION_AND_REPLAY',one_file_was_present=True,
            complete_pair_after_replay=True,cache_removed_on_failure_and_success=True,
            hard_process_termination_tested=False))
        assert capture(second).file_sha256==original.file_sha256
    return records


def main():
    OUT.mkdir(exist_ok=True)
    frozen=('processed_finish.py','integrated_finish_v40.py','distribution_finish.py','accepted_finish.py',
        'hf_temporal_contrast_lab.py','auto_peak_v34.py','offline_peak_lab.py','offline_peak_stream_v34.py',
        'auto_conditioned_v34.py','natural_finish_v34.py','workspace_cleanup.py','joint_lowend_v42.py',
        'automatic_lowend_v41.py','source_events_v41.py')
    matches={name:subprocess.check_output(['git','show',BASE+':PDRM_Local_Render_Engine_v1/'+name],cwd=ROOT).replace(b'\r\n',b'\n')==(ROOT/name).read_bytes().replace(b'\r\n',b'\n') for name in frozen}
    assert all(matches.values()),matches
    patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py',
        'test_event_decay39.py','test_integration40.py','test_integrated_chain40.py','test_automatic41.py','test_joint42.py')
    suite=unittest.TestSuite()
    for pattern in patterns:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
    old=suite.countTestCases();assert old==315,old
    new=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_processed_integration.py')
    added=new.countTestCases();suite.addTests(new)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    record=dict(task_id='P07-A',tests=result.testsRun,previous_tests=old,new_tests=added,
        success=result.wasSuccessful(),errors=[str(v) for v in result.errors],failures=[str(v) for v in result.failures],
        skipped=result.skipped,platform=platform.platform(),frozen_core=matches,
        code_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    dump(OUT/'TEST_RESULTS.json',record)
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    cases=acceptance()
    record.update(acceptance=cases,publication_task_passed=True,parent_P07_done=False,
        private_corpus_tested=False,neural_inference=False,product_gui_changed=False,
        production_exe_released=False,goal_gate_closure_count=0)
    dump(OUT/'SUMMARY.json',record)
    rows='\n'.join(f"| {r['case']} | 成功 |" for r in cases)
    md=f'''# PDRM 課題P07-A — 保存接続の実装・受入記録

日付: 2026-09-10。対象Issue: #4、親Issue: #2。
検証commit: `{record['code_commit']}`。
環境: {record['platform']}。

## 今回閉じられる範囲

新しい共同低域経路を、既存のprocessed同名保存・退避・通常中断後の再実行へ接続した。新コード`processed_integration.py`は既存の検査済みWAV/MP3をそのままコピーし、再符号化しない。既存publisherのjournalと旧出力backupを再利用し、新DSPやGUIを追加していない。

新経路の技術的な保存完了は、音楽的なCANDIDATE/PARTIAL/ABSTAINと分離する。要求・出力hash・音楽的判定を持つ小さな証跡を音声公開より先に記録し、再実行でも確認する。LAB有効化と明示的plannerがなければ動作しない。製品の既定入口は変更していない。

一曲専用の一時領域に完成キャッシュも含め、通常成功/例外/キャンセル時にその領域だけを削除する。利用者が作ったファイル、旧出力backupや別jobの領域を掃除しない。OS強制終了・電源断後の残留領域回収は、このタスクの対象外でP07-Bに残る。

## 実行した受入

| ケース | 結果 |
|---|---|
{rows}

受入ケースは実際のHE/AUTO/共同低域/HFTC/最終WAV/MP3/復号検査と、新しい保存接続を実行した。個人音源ではなく4秒の合成音を使用し、音楽的な関係・役割情報は既知の合成fixture。発音認識・本人嗜好校正の成功とは数えない。

保存の細かな例外試験は、一度実チェーンで生成・検査した完了fixtureをrender関数のmockから返している。publicフォルダへのコピー、hash照合、退避、通常中断、再実行、cleanupは本物の実装。別途上記の非mock完成チェーン受入で接続を確認した。

ソフトウェア試験は{record['tests']}件（既存{old}+追加{added}）。件数をプロジェクト進捗率へ変換しない。新旧の試験成功と本タスクの具体的受入で閉鎖可否を判定する。

## プロジェクト進捗への反映

P07-Aの受入が両OSで確認できれば、この子タスクだけをDONEにする。親P07はP07-B強制終了/容量とP07-C連続処理が残るためPARTIAL。親の8つの出荷課題を、この結果で一括完了にしない。

P01のローカル私有音源実行環境は、このターンでは不通。実曲校正・判断の適切さ・同一基音加算・GUI・モデル配布の残件は`docs/RELEASE_BOARD.md`に固定IDで保持する。台帳とコードを置いただけのものは完了とせず、実行証拠を添える。

正本台帳の開始版を本パッケージにも収録した。最終状態は同branchの最新RELEASE_BOARD.mdとIssue#2/#4で確認する。

## 一次資料

既存repoのprocessed_finish.py/integrated_finish_v40.py、今回の実行ログとSUMMARY.json。
通常の一時領域cleanup仕様: https://docs.python.org/3.12/library/tempfile.html
renameのOS差異: https://docs.python.org/3.12/library/os.html#os.rename

標準ライブラリ資料は実装上の扱いの根拠であり、電源断や音質の保証ではない。
'''
    (OUT/'PDRM_P07A_課題消込と保存接続の実行結果_20260910.md').write_text(md,encoding='utf-8')
    for name in ('processed_integration.py','processed_finish.py','integrated_finish_v40.py'):
        dest=OUT/'code'/name;dest.parent.mkdir(exist_ok=True);shutil.copyfile(ROOT/name,dest)
    shutil.copyfile(ROOT/'tests'/'test_processed_integration.py',OUT/'code'/'test_processed_integration.py')
    shutil.copyfile(__file__,OUT/'code'/'verify_release_publication.py')
    shutil.copyfile(ROOT/'docs'/'RELEASE_BOARD.md',OUT/'RELEASE_BOARD_AT_RUN_START.md')
    print('P07A_ACCEPTANCE '+json.dumps(record,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
