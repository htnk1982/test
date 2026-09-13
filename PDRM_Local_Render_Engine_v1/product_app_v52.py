"""Single-entry P08 Windows product candidate.

The accepted reference calibration is persistent derived metadata. After the
one-time canonical bootstrap, normal GUI runs no longer ask for reference.zip
and no longer perform REFERENCE_CALIBRATION. Worker mode remains the same EXE.
"""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,os,subprocess,sys,traceback,uuid

import accepted_calibration_cache_v53 as calcache
import gui_runtime_v44 as gui44
import natural_gui_v34 as targets_gui
import natural_gui_v44 as progress_gui
import product_gui_runtime_v52 as request
import product_worker_v52 as worker

VERSION='product-app-candidate-0.2.0'


def app_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'product_v53'


def _select_audio():
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw()
    try:return [Path(p) for p in filedialog.askopenfilenames(title='PDRM: 処理する元WAV/FLACを選択（複数可）',filetypes=[('Lossless audio','*.wav *.flac')])]
    finally:root.destroy()


def _select_reference_once():
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk();root.withdraw()
    try:
        value=filedialog.askopenfilename(title='PDRM 初回のみ: canonical reference.zipを選択',filetypes=[('reference.zip','*.zip')])
        return Path(value) if value else None
    finally:root.destroy()


def _worker_command(manifest):
    if getattr(sys,'frozen',False):return [sys.executable,'--worker-manifest',str(manifest)]
    return [sys.executable,str(Path(__file__).resolve()),'--worker-manifest',str(manifest)]


def gui():
    import tkinter as tk
    from tkinter import messagebox
    sources=_select_audio()
    if not sources:return 0
    cache_ready=calcache.has_accepted()
    reference=None if cache_ready else _select_reference_once()
    if not cache_ready and reference is None:return 0
    selected=targets_gui.choose_targets()
    if selected is None:return 0
    targets,replace_managed,_mode=selected

    root=app_root();work=root/'work';sessions=root/'sessions';token=uuid.uuid4().hex;session=sessions/token;session.mkdir(parents=True,exist_ok=False);manifest_path=session/'request.json'
    try:
        manifest=request.make_manifest(sources,reference,targets,replace_managed,work,session,cache_ready=cache_ready)
        request.write_manifest(manifest_path,manifest)
    except Exception as exc:
        messagebox.showerror('PDRM','開始できません。\n\n'+str(exc));return 1

    log=(session/'worker.log').open('w',encoding='utf-8')
    try:
        proc=subprocess.Popen(_worker_command(manifest_path),cwd=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent,stdout=log,stderr=subprocess.STDOUT)
    except Exception:log.close();raise

    ui=tk.Tk()
    def done(state):
        log.flush();overall=state.get('overall')
        if overall=='COMPLETE':messagebox.showinfo('PDRM','すべての音源を完了しました。\n各元音源フォルダの processed を確認してください。',parent=ui)
        elif overall=='COMPLETE_WITH_ERRORS':messagebox.showwarning('PDRM','完了しましたが、処理できなかった音源があります。\n進捗画面とworker.logを確認してください。',parent=ui)
        elif overall=='CANCELLED':messagebox.showinfo('PDRM','キャンセルしました。元音源は変更していません。',parent=ui)
        else:messagebox.showerror('PDRM','workerが異常終了しました。\n'+str(session/'PRODUCT_FAILURE.json'),parent=ui)
    progress_gui.ProgressDialog(ui,proc,session,manifest['sha256'],on_done=done)
    try:ui.mainloop()
    finally:log.close()
    return 0


def _file_diag(path):
    p=Path(path);row=dict(path=str(p),exists=p.is_file())
    if p.is_file():
        row['bytes']=p.stat().st_size;h=hashlib.sha256()
        with p.open('rb') as f:
            for block in iter(lambda:f.read(2**20),b''):h.update(block)
        row['sha256']=h.hexdigest()
    return row


def _selftest_failure(output,exc):
    out=Path(output);out.mkdir(parents=True,exist_ok=True);frozen=bool(getattr(sys,'frozen',False));bundle=Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
    failure=dict(success=False,version=VERSION,error_type=type(exc).__name__,error=str(exc),repr=repr(exc),traceback=traceback.format_exc(),frozen=frozen,executable=str(Path(sys.executable).resolve()),cwd=str(Path.cwd()),bundle_root=str(bundle),observer_runtime=str(worker.runtime_root()),observer_runtime_exists=worker.runtime_root().is_dir())
    try:
        import imageio_ffmpeg;failure['ffmpeg']=_file_diag(Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve())
    except Exception as diag_exc:failure['ffmpeg_diagnostic_error']=repr(diag_exc)
    for name in ('product_app_v52.py','product_worker_v52.py','product_selftest_v52.py','accepted_calibration_cache_v53.py','p01_private_calibration_entry.py'):
        failure.setdefault('bundled_python_sources',{})[name]=_file_diag(bundle/name)
    (out/'P08_PRODUCT_SELFTEST_FAILURE.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');return failure


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--worker-manifest',type=Path);p.add_argument('--self-test',action='store_true');p.add_argument('--self-test-output',type=Path);a=p.parse_args(argv)
    if a.self_test:
        if a.worker_manifest or not a.self_test_output:raise SystemExit('--self-test requires --self-test-output and no worker manifest')
        try:
            from product_selftest_v52 import self_test;print(json.dumps(self_test(a.self_test_output),ensure_ascii=True),flush=True);return 0
        except Exception as exc:_selftest_failure(a.self_test_output,exc);return 90
    if a.worker_manifest:
        result=worker.run_manifest(a.worker_manifest);return 0 if result['overall'] in ('COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED') else 1
    return gui()

if __name__=='__main__':
    import multiprocessing;multiprocessing.freeze_support();raise SystemExit(main())
