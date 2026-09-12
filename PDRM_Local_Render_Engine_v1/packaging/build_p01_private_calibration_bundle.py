"""Build a self-contained Windows P01 private calibration bundle.

Public CI contains code/runtime only. It never receives private music/reference
audio. The output is an engineering bundle, not a product-release executable.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib, importlib.metadata as metadata, json, os, platform, shutil, subprocess, sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'P01_PRIVATE_BUNDLE'
EVIDENCE=ROOT/'P01_PRIVATE_BUNDLE_EVIDENCE'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def execute(command,log,cwd,env=None,timeout=1800):
    with Path(log).open('w',encoding='utf-8') as f:r=subprocess.run(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if r.returncode:
        text=Path(log).read_text(encoding='utf-8',errors='replace');print(text[-20000:],flush=True)
        raise RuntimeError('P01 bundle step failed: '+str(log))


def main():
    if sys.platform!='win32':raise RuntimeError('Windows only')
    runtime=ROOT/'P02_CAPSULE_WORK'/'PDRM_OBSERVER_RUNTIME'
    if not runtime.is_dir():raise RuntimeError('Build Spleeter runtime first')
    OUT.mkdir(exist_ok=True);EVIDENCE.mkdir(exist_ok=True)
    from PyInstaller.utils.hooks import copy_metadata
    import imageio_ffmpeg
    packages=('numpy','scipy','soundfile','pyloudnorm','psutil','imageio-ffmpeg','cffi','pycparser','pyinstaller','pyinstaller-hooks-contrib')
    versions={p:metadata.version(p) for p in packages};commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    with TemporaryDirectory(prefix='pdrm_p01_build_') as td:
        build=Path(td);hooks=build/'hooks';hooks.mkdir();root_py=sorted(ROOT.glob('*.py'));modes={p.stem:'py' for p in root_py}
        (hooks/'hook-p01_private_calibration_entry.py').write_text('module_collection_mode = '+repr(modes)+'\n',encoding='utf-8')
        datas=[(str(p),'.') for p in root_py]
        for name in packages:datas.extend(copy_metadata(name))
        hidden=['imageio_ffmpeg','_cffi_backend','tkinter','tkinter.filedialog','tkinter.messagebox','automatic_joint_v50','automatic_joint_v49','automatic_joint_v48','automatic_lowend_v41','source_events_v41','relative_low_dominance_v49','physical_add_bridge_v50','physical_add_bridge_v46','same_f0_permission_v50','event_groove_v37','joint_lowend_v46','joint_lowend_v42','physical_decay_bridge_v42','spleeter_observer_adapter_v48','observer_runtime_client_v47','integrated_finish_v40','distribution_finish','auto_peak_v34','hf_temporal_contrast_lab']
        spec=f'''a=Analysis([{str(ROOT/'p01_private_calibration_entry.py')!r}],pathex={[str(ROOT)]!r},\n binaries=[({str(ffmpeg)!r},'imageio_ffmpeg/binaries')],datas={datas!r},\n hiddenimports={hidden!r},hookspath={[str(hooks)]!r},\n excludes=['torch','torchaudio','tensorflow','spleeter','pandas','matplotlib','IPython','pytest'],noarchive=False)\npyz=PYZ(a.pure)\nexe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PDRM_P01_Calibrate',console=True,debug=False,strip=False,upx=False,uac_admin=False)\ncoll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PDRM_P01_Private_Calibration')\n'''
        specfile=build/'p01.spec';specfile.write_text(spec,encoding='utf-8');shutil.copyfile(specfile,EVIDENCE/'BUILD_SPEC.txt')
        execute([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(build/'dist'),'--workpath',str(build/'work'),str(specfile)],EVIDENCE/'BUILD.log',ROOT,timeout=1800)
        dist=build/'dist'/'PDRM_P01_Private_Calibration';exe=dist/'PDRM_P01_Calibrate.exe'
        if not exe.is_file():raise RuntimeError('Frozen P01 EXE missing')
        shutil.copytree(runtime,dist/'PDRM_OBSERVER_RUNTIME')
        readme=f'''PDRM P01 Private Calibration Bundle\n===================================\nEngineering calibration only. Product release: NO.\nAccepted P03-A code baseline: 50a4592e45b3f810e905041c25cff1c3e35b2a88\nBundle build commit: {commit}\n\n使い方:\n1. PDRM_P01_Calibrate.exe をダブルクリック。\n2. 実曲の WAV または FLAC を選択。\n3. 既存の reference.zip（または参照音源フォルダ）を選択。\n4. 元音源フォルダとは別の結果保存フォルダを選択。\n5. 完了後、PDRM_P01_<曲名>_<hash>/ の MASTER.wav と LISTEN_320kbps.mp3 を聴く。\n6. REVIEW.md の4項目だけを確認する。\n\nプライバシー:\n- 音源はこのPC上だけで処理される。\n- GitHub/CI/ネットワークへ私有音源を送信する機能はない。\n- Spleeter stem音声は保存せず、完成音にも混ぜない。\n- 元音源は上書きしない。\n\n注意:\n- 初回はreference群の校正を行うため時間がかかる。\n- これはP01/P03実曲校正用であり製品版ではない。\n'''
        (dist/'README_P01.txt').write_text(readme,encoding='utf-8')
        (dist/'RUN_P01_CALIBRATION.cmd').write_text('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n"PDRM_P01_Calibrate.exe"\r\nif errorlevel 1 pause\r\n',encoding='utf-8')
        isolated=build/'日本語 空白'/'P01校正';isolated.parent.mkdir();shutil.copytree(dist,isolated);testout=EVIDENCE/'SELFTEST';testout.mkdir(exist_ok=True);env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','IMAGEIO_FFMPEG_EXE'):env.pop(key,None)
        env['PYTHONUTF8']='1';execute([str(isolated/'PDRM_P01_Calibrate.exe'),'--self-test','--self-test-output',str(testout)],EVIDENCE/'SELFTEST.log',build,env,timeout=1200)
        summary=json.loads((testout/'P01_BUNDLE_SELFTEST.json').read_text(encoding='utf-8'))
        if not summary.get('success') or summary.get('observer_provider')!='spleeter_runtime48':raise RuntimeError('Frozen private-calibration self-test failed')
        final=OUT/'PDRM_P01_Private_Calibration'
        if final.exists():shutil.rmtree(final)
        shutil.copytree(dist,final)
        report=dict(success=True,commit=commit,accepted_p03a_commit='50a4592e45b3f810e905041c25cff1c3e35b2a88',platform=platform.platform(),versions=versions,exe_sha256=sha(final/'PDRM_P01_Calibrate.exe'),exe_bytes=(final/'PDRM_P01_Calibrate.exe').stat().st_size,bundle_bytes=sum(p.stat().st_size for p in final.rglob('*') if p.is_file()),runtime_bytes=sum(p.stat().st_size for p in (final/'PDRM_OBSERVER_RUNTIME').rglob('*') if p.is_file()),frozen_selftest=summary,private_audio_used=False,private_audio_upload_path=False,product_release=False,user_python_required=False)
        (EVIDENCE/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print('P01_PRIVATE_BUNDLE '+json.dumps(report,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
