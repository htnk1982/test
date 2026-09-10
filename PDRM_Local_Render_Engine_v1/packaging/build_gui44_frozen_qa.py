"""Build/run P06-A QA EXE. Evidence only; binary is not uploaded as product."""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,sys,json,subprocess,shutil,hashlib,importlib.metadata as metadata,platform
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'P06A_FROZEN_EVIDENCE'

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def execute(command,log,cwd,env=None,timeout=900):
    with Path(log).open('w',encoding='utf-8') as f:r=subprocess.run(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if r.returncode:
        text=Path(log).read_text(encoding='utf-8',errors='replace');print(text[-16000:],flush=True);raise RuntimeError('Frozen QA failed: '+str(log))

def main():
    if sys.platform!='win32':raise RuntimeError('Windows only')
    OUT.mkdir(exist_ok=True)
    from PyInstaller.utils.hooks import copy_metadata
    import imageio_ffmpeg
    packages=('numpy','scipy','soundfile','pyloudnorm','psutil','imageio-ffmpeg','cffi','pycparser','pyinstaller','pyinstaller-hooks-contrib')
    versions={p:metadata.version(p) for p in packages};commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    with TemporaryDirectory(prefix='pdrm_gui44_build_') as td:
        build=Path(td);hooks=build/'hooks';hooks.mkdir();root_py=sorted(ROOT.glob('*.py'))
        modes={p.stem:'py' for p in root_py};modes['decay39_fixtures']='py'
        (hooks/'hook-gui44_qa_entry.py').write_text('module_collection_mode = '+repr(modes)+'\n',encoding='utf-8')
        datas=[(str(p),'.') for p in root_py]+[(str(ROOT/'tests'/'decay39_fixtures.py'),'.')]
        for name in packages:datas.extend(copy_metadata(name))
        spec=f'''a=Analysis([{str(ROOT/'gui44_qa_entry.py')!r}],pathex={[str(ROOT),str(ROOT/'tests')]!r},\n binaries=[({str(ffmpeg)!r},'imageio_ffmpeg/binaries')],datas={datas!r},\n hiddenimports=['imageio_ffmpeg','decay39_fixtures','joint_lowend_v42','physical_decay_bridge_v42','processed_integration','gui_worker_entry_v44','_cffi_backend','tkinter','tkinter.ttk'],\n hookspath={[str(hooks)]!r},excludes=['torch','torchaudio','tensorflow','pandas','matplotlib','IPython','pytest'],noarchive=False)\npyz=PYZ(a.pure)\nexe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PDRM_GUI_QA',console=True,debug=False,strip=False,upx=False,uac_admin=False)\ncoll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PDRM_GUI_QA')\n'''
        specfile=build/'gui44.spec';specfile.write_text(spec,encoding='utf-8');shutil.copyfile(specfile,OUT/'BUILD_SPEC.txt')
        execute([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(build/'dist'),'--workpath',str(build/'work'),str(specfile)],OUT/'BUILD.log',ROOT,timeout=1200)
        bundle=build/'dist'/'PDRM_GUI_QA';exe=bundle/'PDRM_GUI_QA.exe'
        if not exe.is_file():raise RuntimeError('No frozen EXE')
        isolated=build/'日本語 空白'/'アプリ';isolated.parent.mkdir();shutil.copytree(bundle,isolated);exe=isolated/'PDRM_GUI_QA.exe'
        cwd=build/'empty';cwd.mkdir();env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','IMAGEIO_FFMPEG_EXE','PDRM_ENABLE_GUI_FIXTURE'):env.pop(key,None)
        win=Path(env.get('SystemRoot',r'C:\Windows'));env['PATH']=str(win/'System32')+os.pathsep+str(win);env['PYTHONUTF8']='1'
        result=OUT/'FROZEN_GUI_RESULT.json';execute([str(exe),'--full-self-test',str(result)],OUT/'RUN.log',cwd,env,timeout=600)
        payload=json.loads(result.read_text(encoding='utf-8'))
        assert payload['success'] and payload['frozen'] and payload['actual_tk_mainloop_callbacks'] and payload['separate_worker_process']
        assert payload['records'][0]['overall']=='COMPLETE' and payload['records'][1]['overall']=='CANCELLED'
        assert all(r['owned_work_left']==0 for r in payload['records'])
        report=dict(success=True,commit=commit,platform=platform.platform(),versions=versions,exe_sha256=sha(exe),
            exe_bytes=exe.stat().st_size,bundle_bytes=sum(p.stat().st_size for p in isolated.rglob('*') if p.is_file()),
            isolated_japanese_path=True,external_python_on_path=False,product_runtime_open=False,private_music=False,
            neural_inference=False,qa=payload,product_exe_published=False)
        (OUT/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        md=f'''# PDRM P06-A — Windows frozen GUI/worker QA\n\n日付: 2026-09-10。commit `{commit}`。\n\nPyInstallerでQA専用EXEを作成し、checkout外の日本語・空白を含む場所へ移して起動した。Tk側で進捗windowをpollしながら、同じEXEの別processを実際のnew-chain workerとして起動。通常完走と、処理中Cancelの2ケースを実行した。\n\n通常完走ではWAV/MP3がprocessedへ作成され、CancelではworkerがCANCELLEDで終了した。いずれもP07のowned workspace残留なし。Tkのscheduled callbackは処理中にも複数回実行し、DSPをUI threadへ戻していない。\n\nPATHから外部Python/FFmpegを外したが、ホストPythonをアンインストールした試験やOSネットワーク遮断ではない。QAバイナリは製品用GUIではなく、engineering fixture plannerだけを環境変数で子processに明示許可する。`product_release` runtimeは未承認planner/modelのため閉じたまま。\n\nこの成功はGUI/worker配線を閉じる証拠であり、実曲判断やモデル推論の完成ではない。QA EXEは成果物へ同梱せず、証拠だけ保存する。\n'''
        (OUT/'PDRM_P06A_Windows_frozen_GUI_worker_20260910.md').write_text(md,encoding='utf-8')
    print('P06A_FROZEN '+json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
