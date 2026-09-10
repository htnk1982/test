"""QA-only GUI executable entry. It accepts no arbitrary product planner.

In frozen self-test it creates synthetic audio, launches a second copy of the
same executable as the DSP worker, drives the Tk progress window, verifies UI
callbacks during work, then exercises cancellation. Not a release app.
"""
from pathlib import Path
import argparse,json,os,sys,tempfile,time
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def worker(path):
    import gui_worker_entry_v44
    return gui_worker_entry_v44.run_manifest(path)


def full_self_test(output):
    import tkinter as tk
    import numpy as np,soundfile as sf
    import gui_runtime_v44 as runtime
    from natural_gui_v44 import ProgressDialog
    from target_settings import Targets
    from decay39_fixtures import audio_fixture
    records=[]
    with tempfile.TemporaryDirectory(prefix='pdrm_gui44_frozen_') as tmp:
        rootdir=Path(tmp);source_dir=rootdir/'日本語 空白 入力';source_dir.mkdir();work=rootdir/'work'
        _,bad,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.)
        def execute(name,audio,targets,cancel_ms=None):
            source=source_dir/(name+'.wav');sf.write(source,audio,48000,subtype='DOUBLE')
            session=rootdir/('session_'+name);manifest=runtime.make_manifest([source],targets,False,work,session,runtime_id='engineering_fixture_tail')
            mf=rootdir/(name+'.manifest.json');runtime.atomic_json(mf,manifest)
            env=dict(os.environ,PDRM_ENABLE_GUI_FIXTURE='1')
            command=[sys.executable] if getattr(sys,'frozen',False) else [sys.executable,str(Path(__file__).resolve())]
            process=__import__('subprocess').Popen(command+['--worker-manifest',str(mf)],cwd=rootdir,env=env)
            root=tk.Tk();root.withdraw();done=[];dialog=ProgressDialog(root,process,session,manifest['sha256'],on_done=lambda s:done.append(s),poll_ms=50)
            ticks=[]
            def tick():
                ticks.append(time.monotonic())
                if not dialog.closed:root.after(20,tick)
            root.after(5,tick)
            if cancel_ms is not None:root.after(cancel_ms,dialog.cancel)
            deadline=time.monotonic()+240
            while not dialog.closed and time.monotonic()<deadline:
                root.update();time.sleep(.01)
            if not dialog.closed:
                process.kill();process.wait();root.destroy();raise TimeoutError('Frozen GUI did not finish')
            process.wait(timeout=20);root.update();root.destroy()
            final=done[-1] if done else dialog.last
            result=dict(name=name,overall=final['overall'],worker_returncode=process.returncode,ui_ticks=len(ticks),
                current_file_seen=bool(final.get('current_file')),owned_work_left=len(list(work.glob('.pdrm-owned-*'))),
                wav_exists=(source_dir/'processed'/(name+'.wav')).exists(),mp3_exists=(source_dir/'processed'/(name+'.mp3')).exists())
            return result
        good=execute('01 完走',bad,Targets(wav_lufs=-12.5,wav_tp=-2.3,mp3_lufs=-14.5,mp3_tp=-2.2))
        assert good['overall']=='COMPLETE' and good['worker_returncode']==0 and good['ui_ticks']>=5 and good['wav_exists'] and good['mp3_exists'] and not good['owned_work_left']
        records.append(good)
        cancelled=execute('02 キャンセル',np.tile(bad,(8,1)),Targets(),cancel_ms=300)
        assert cancelled['overall']=='CANCELLED' and cancelled['worker_returncode']==0 and cancelled['ui_ticks']>=2 and not cancelled['owned_work_left']
        records.append(cancelled)
    report=dict(success=True,frozen=bool(getattr(sys,'frozen',False)),records=records,
        actual_tk_mainloop_callbacks=True,separate_worker_process=True,product_runtime_open=False,
        private_music=False,neural_inference=False,scope='FROZEN_GUI_WORKER_QA;_NOT_RELEASE_APP')
    Path(output).write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return 0


def main(argv=None):
    ap=argparse.ArgumentParser();group=ap.add_mutually_exclusive_group(required=True)
    group.add_argument('--worker-manifest',type=Path);group.add_argument('--full-self-test',type=Path)
    a=ap.parse_args(argv)
    if a.worker_manifest:return worker(a.worker_manifest)
    return full_self_test(a.full_self_test)

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support();raise SystemExit(main())
