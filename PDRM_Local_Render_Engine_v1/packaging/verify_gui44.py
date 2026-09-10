"""P06-A acceptance. Synthetic audio only; product planner remains closed."""
from pathlib import Path
import sys,json,os,time,tempfile,subprocess,unittest,platform
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
OUT=ROOT/'P06A_EVIDENCE'

def dump(name,value):OUT.mkdir(exist_ok=True);(OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def wait(proc,session,manifest_hash,timeout=240):
    import gui_runtime_v44 as g
    deadline=time.monotonic()+timeout;seen=[]
    while time.monotonic()<deadline:
        s=g.read_status(session,manifest_hash)
        if s:
            state=(s.get('stage'),s.get('file_index'),s.get('current_file'))
            if not seen or seen[-1]!=state:seen.append(state)
            if s.get('overall') in ('COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED','FAILED'):
                proc.wait(timeout=20);return s,seen
        if proc.poll() is not None:
            raise RuntimeError('Worker exited without final status '+str(proc.returncode))
        time.sleep(.05)
    proc.kill();proc.wait();raise TimeoutError('GUI worker did not finish')

def process_acceptance():
    import numpy as np,soundfile as sf
    import gui_runtime_v44 as g
    from target_settings import Targets
    from decay39_fixtures import audio_fixture
    records=[]
    with tempfile.TemporaryDirectory(prefix='pdrm_gui44_') as tmp:
        root=Path(tmp);source_dir=root/'日本語 入力';source_dir.mkdir();work=root/'work';session=root/'session';manifest_path=root/'manifest.json'
        _,bad,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.);source=source_dir/'01 曲.wav';sf.write(source,bad,48000,subtype='DOUBLE')
        targets=Targets(wav_lufs=-12.5,wav_tp=-2.3,mp3_lufs=-14.5,mp3_tp=-2.2)
        manifest=g.make_manifest([source],targets,False,work,session,runtime_id='engineering_fixture_tail');g.atomic_json(manifest_path,manifest)
        env=dict(os.environ,PDRM_ENABLE_GUI_FIXTURE='1');proc=subprocess.Popen([sys.executable,str(ROOT/'gui_worker_entry_v44.py'),'--worker-manifest',str(manifest_path)],cwd=ROOT,env=env)
        final,seen=wait(proc,session,manifest['sha256'])
        assert proc.returncode==0 and final['overall']=='COMPLETE' and len(final['completed'])==1
        out=source_dir/'processed';assert (out/'01 曲.wav').is_file() and (out/'01 曲.mp3').is_file()
        assert not list(work.glob('.pdrm-owned-*'))
        records.append(dict(case='SEPARATE_WORKER_COMPLETE',final=final['overall'],status_updates=len(seen),targets=targets.to_dict(),outputs=['01 曲.wav','01 曲.mp3'],owned_work_left=False))

        # Cancellation path: use a longer input so cancellation is observed by
        # the real audio Progress.set before publication can race to completion.
        source2=source_dir/'02 キャンセル.wav';sf.write(source2,np.tile(bad,(8,1)),48000,subtype='DOUBLE')
        session2=root/'session2';m2=g.make_manifest([source2],Targets(),False,work,session2,runtime_id='engineering_fixture_tail');p2=root/'m2.json';g.atomic_json(p2,m2)
        proc=subprocess.Popen([sys.executable,str(ROOT/'gui_worker_entry_v44.py'),'--worker-manifest',str(p2)],cwd=ROOT,env=env)
        deadline=time.monotonic()+30;started=False
        while time.monotonic()<deadline:
            s=g.read_status(session2,m2['sha256'])
            if s and s.get('file_index')==1 and s.get('stage') not in ('START',):started=True;break
            if proc.poll() is not None:break
            time.sleep(.02)
        if not started:
            if proc.poll() is None:proc.kill();proc.wait()
            raise RuntimeError('Worker never entered first file for cancellation')
        g.request_cancel(session2);cancel,seen2=wait(proc,session2,m2['sha256'])
        assert cancel['overall']=='CANCELLED' and proc.returncode==0
        assert not list(work.glob('.pdrm-owned-*'))
        records.append(dict(case='REAL_WORKER_CANCEL',final=cancel['overall'],status_updates=len(seen2),owned_work_left=False))
    return records

def main():
    OUT.mkdir(exist_ok=True)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_gui_runtime_v44.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    records=process_acceptance();gui=None
    if sys.platform=='win32':
        import natural_gui_v44 as gui44
        gui_file=OUT/'GUI_SELF_CHECK.json';gui44.progress_self_check(gui_file);gui=json.loads(gui_file.read_text())
        assert gui['status']=='PASS' and gui['responsive_callbacks'] and gui['progress_poll']
    summary=dict(task='P06-A',platform=platform.platform(),tests=result.testsRun,success=True,process_acceptance=records,
        gui_self_check=gui,product_planner_closed=True,private_music=False,product_exe=False,
        commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    dump('SUMMARY.json',summary)
    md=f'''# PDRM P06-A — GUI/worker接続基盤の実行記録\n\n日付: 2026-09-10。Issue #6。commit `{summary['commit']}`。\n\n既存v3.4の4つのWAV/MP3 LUFS/TP設定と退避指定UIは再利用し、DSPをTkのmain threadから外すworker境界を実装した。worker manifestはseal付きで、複数source、4目標、replace-managed、work/session、runtime IDを固定する。\n\nGUIは100ms pollの`after()`でstatus.jsonを読み、現在曲、stage、done/total、完了/失敗数を描画する。CancelはCANCELファイルをfsyncし、同じProgress.setが検知する。通常の一曲失敗は記録して次曲へ進み、cancelだけは全queueを止める。\n\n別processで実際のnew-chain合成音処理をWAV/MP3まで完走し、progress更新とprocessed出力を確認。別の長い合成入力では処理開始後にcancelを送ってCANCELLEDとなり、P07のowned workspaceが残らないことを確認した。\n\nWindowsではTkのmainloop相当の`update()`中にscheduled callbackが実行され、status表示も更新されるself-checkを行った。これは人間によるGUI操作試験やfrozen EXEの検査ではないため、IssueのEXE条件は別のfrozen QAで閉じる。\n\n現在のworkerは`product_release` runtimeを意図的に拒否する。P02/P03/P04が未承認のplanner/modelをGUI基盤の完成と同時に製品へ流さない。engineering fixtureは環境変数で明示許可した試験だけ。\n'''
    (OUT/'PDRM_P06A_GUI_worker_実装結果_20260910.md').write_text(md,encoding='utf-8')
    print('P06A '+json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
