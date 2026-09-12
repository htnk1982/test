"""Single-entry P08 Windows product candidate.

GUI mode selects source files, the one canonical reference.zip and the existing
four output targets. Worker mode is the same executable with --worker-manifest,
so Tk remains responsive while DSP runs in another process. Final product
release remains gated by P08 Frozen/roundtrip/private acceptance.
"""
from __future__ import annotations
from pathlib import Path
import argparse,os,subprocess,sys,uuid

import gui_runtime_v44 as gui44
import natural_gui_v34 as targets_gui
import natural_gui_v44 as progress_gui
import product_gui_runtime_v52 as request
import product_worker_v52 as worker

VERSION='product-app-candidate-0.1.0'


def app_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'product_v52'


def _select_audio_and_reference():
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw()
    try:
        sources=[Path(p) for p in filedialog.askopenfilenames(
            title='PDRM: 処理する元WAV/FLACを選択（複数可）',
            filetypes=[('Lossless audio','*.wav *.flac')])]
        if not sources:return [],None
        reference=filedialog.askopenfilename(
            title='PDRM: canonical reference.zipを選択',
            filetypes=[('reference.zip','*.zip')])
        return sources,(Path(reference) if reference else None)
    finally:
        root.destroy()


def _worker_command(manifest):
    if getattr(sys,'frozen',False):
        return [sys.executable,'--worker-manifest',str(manifest)]
    return [sys.executable,str(Path(__file__).resolve()),'--worker-manifest',str(manifest)]


def gui():
    import tkinter as tk
    from tkinter import messagebox
    sources,reference=_select_audio_and_reference()
    if not sources or reference is None:return 0
    selected=targets_gui.choose_targets()
    if selected is None:return 0
    targets,replace_managed,_mode=selected

    root=app_root();work=root/'work';sessions=root/'sessions'
    token=uuid.uuid4().hex;session=sessions/token;session.mkdir(parents=True,exist_ok=False)
    manifest_path=session/'request.json'
    try:
        manifest=request.make_manifest(
            sources,reference,targets,replace_managed,work,session)
        request.write_manifest(manifest_path,manifest)
    except Exception as exc:
        messagebox.showerror('PDRM','開始できません。\n\n'+str(exc))
        return 1

    log=(session/'worker.log').open('w',encoding='utf-8')
    try:
        proc=subprocess.Popen(_worker_command(manifest_path),cwd=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent,
                              stdout=log,stderr=subprocess.STDOUT)
    except Exception:
        log.close();raise

    ui=tk.Tk()
    def done(state):
        log.flush()
        overall=state.get('overall')
        if overall=='COMPLETE':
            messagebox.showinfo('PDRM','すべての音源を完了しました。\n各元音源フォルダの processed を確認してください。',parent=ui)
        elif overall=='COMPLETE_WITH_ERRORS':
            messagebox.showwarning('PDRM','完了しましたが、処理できなかった音源があります。\n進捗画面とworker.logを確認してください。',parent=ui)
        elif overall=='CANCELLED':
            messagebox.showinfo('PDRM','キャンセルしました。元音源は変更していません。',parent=ui)
        else:
            messagebox.showerror('PDRM','workerが異常終了しました。\n'+str(session/'PRODUCT_FAILURE.json'),parent=ui)
    progress_gui.ProgressDialog(ui,proc,session,manifest['sha256'],on_done=done)
    try:ui.mainloop()
    finally:log.close()
    return 0


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--worker-manifest',type=Path)
    p.add_argument('--self-test',action='store_true');p.add_argument('--self-test-output',type=Path)
    a=p.parse_args(argv)
    if a.self_test:
        if a.worker_manifest or not a.self_test_output:
            raise SystemExit('--self-test requires --self-test-output and no worker manifest')
        from product_selftest_v52 import self_test
        import json
        print(json.dumps(self_test(a.self_test_output),ensure_ascii=True),flush=True)
        return 0
    if a.worker_manifest:
        result=worker.run_manifest(a.worker_manifest)
        return 0 if result['overall'] in ('COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED') else 1
    return gui()


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
