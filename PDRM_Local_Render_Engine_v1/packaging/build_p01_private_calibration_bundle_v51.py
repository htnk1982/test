"""Build the delivered Windows P01 v51 private-calibration bundle.

The bundle preserves the accepted 24-MP3 local compatibility boundary and the
self-contained Spleeter runtime, but selects automatic_joint_v51 so redundant
observer inference can be pruned. Public CI never receives private audio.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,importlib.metadata as metadata,json,os,platform,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'P01_V51_PRIVATE_BUNDLE'
EVIDENCE=ROOT/'P01_V51_PRIVATE_BUNDLE_EVIDENCE'
PLANNER='automatic-joint-lab-0.4.0'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def execute(command,log,cwd,env=None,timeout=1800):
    with Path(log).open('w',encoding='utf-8') as f:
        r=subprocess.run(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if r.returncode:
        text=Path(log).read_text(encoding='utf-8',errors='replace');print(text[-20000:],flush=True)
        raise RuntimeError('P01 v51 bundle step failed: '+str(log))


def main():
    if sys.platform!='win32':raise RuntimeError('Windows only')
    runtime=ROOT/'P02_CAPSULE_WORK'/'PDRM_OBSERVER_RUNTIME'
    if not runtime.is_dir():raise RuntimeError('Build Spleeter runtime first')
    if OUT.exists():shutil.rmtree(OUT)
    if EVIDENCE.exists():shutil.rmtree(EVIDENCE)
    OUT.mkdir();EVIDENCE.mkdir()
    from PyInstaller.utils.hooks import copy_metadata
    import imageio_ffmpeg
    packages=('numpy','scipy','soundfile','pyloudnorm','psutil','imageio-ffmpeg','cffi','pycparser','pyinstaller','pyinstaller-hooks-contrib')
    versions={p:metadata.version(p) for p in packages};commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip();ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    with TemporaryDirectory(prefix='pdrm_p01_v51_build_') as td:
        build=Path(td);hooks=build/'hooks';hooks.mkdir();root_py=sorted(ROOT.glob('*.py'));modes={p.stem:'py' for p in root_py}
        (hooks/'hook-p01_private_calibration_bootstrap_v51.py').write_text('module_collection_mode = '+repr(modes)+'\n',encoding='utf-8')
        datas=[(str(p),'.') for p in root_py]
        for name in packages:datas.extend(copy_metadata(name))
        hidden=[
            'p01_private_calibration_bootstrap_v51','p01_private_calibration_bootstrap','p01_private_calibration_entry_v51','p01_private_calibration_entry',
            'automatic_joint_v51','automatic_joint_v50','automatic_joint_v49','automatic_joint_v48','automatic_lowend_v41','source_events_v41','relative_low_dominance_v49',
            'physical_add_bridge_v50','physical_add_bridge_v46','same_f0_permission_v50','event_groove_v37','joint_lowend_v46','joint_lowend_v42','physical_decay_bridge_v42',
            'spleeter_observer_adapter_v48','observer_runtime_client_v47','integrated_finish_v40','distribution_finish','auto_peak_v34','hf_temporal_contrast_lab',
            'imageio_ffmpeg','_cffi_backend','tkinter','tkinter.filedialog','tkinter.messagebox'
        ]
        spec=f'''a=Analysis([{str(ROOT/'p01_private_calibration_bootstrap_v51.py')!r}],pathex={[str(ROOT)]!r},\n binaries=[({str(ffmpeg)!r},'imageio_ffmpeg/binaries')],datas={datas!r},\n hiddenimports={hidden!r},hookspath={[str(hooks)]!r},\n excludes=['torch','torchaudio','tensorflow','spleeter','pandas','matplotlib','IPython','pytest'],noarchive=False)\npyz=PYZ(a.pure)\nexe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PDRM_P01_Calibrate',console=True,debug=False,strip=False,upx=False,uac_admin=False)\ncoll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PDRM_P01_Private_Calibration')\n'''
        specfile=build/'p01_v51.spec';specfile.write_text(spec,encoding='utf-8');shutil.copyfile(specfile,EVIDENCE/'BUILD_SPEC.txt')
        execute([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(build/'dist'),'--workpath',str(build/'work'),str(specfile)],EVIDENCE/'BUILD.log',ROOT,timeout=1800)
        dist=build/'dist'/'PDRM_P01_Private_Calibration';exe=dist/'PDRM_P01_Calibrate.exe'
        if not exe.is_file():raise RuntimeError('Frozen P01 v51 EXE missing')
        shutil.copytree(runtime,dist/'PDRM_OBSERVER_RUNTIME')
        readme=f'''PDRM P01 Private Calibration Bundle v51\n=======================================\nEngineering calibration only. Product release: NO.\nAccepted P03-A musical baseline: 50a4592e45b3f810e905041c25cff1c3e35b2a88\nObserver-pruned planner: {PLANNER}\nBundle build commit: {commit}\n\nUse:\n1. Double-click RUN_P01_CALIBRATION.cmd.\n2. Select the next private WAV/FLAC (first field-speed case: source 06).\n3. Select the canonical reference.zip (24 MP3 tracks).\n4. Select an output folder outside the source folder.\n5. Listen to MASTER.wav and LISTEN_320kbps.mp3.\n6. Return CALIBRATION_MANIFEST.json plus only a short listening judgement.\n\nThe manifest records total elapsed_seconds and observer call-pruning counters.\nNo manual stopwatch or progress-log transcription is required.\n\nPrivacy/safety:\n- Private audio stays on this PC.\n- Historical MP3 references are decoded only to temporary local float-WAV.\n- Temporary decoded WAVs are removed; the global lossless contract is unchanged.\n- Spleeter stems are never exported and never mixed into the master.\n- The original source is never overwritten.\n'''
        (dist/'README_P01_V51.txt').write_text(readme,encoding='utf-8')
        (dist/'RUN_P01_CALIBRATION.cmd').write_text('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n"PDRM_P01_Calibrate.exe"\r\nif errorlevel 1 pause\r\n',encoding='utf-8-sig')

        isolated=build/'日本語 空白'/'P01 v51 校正';isolated.parent.mkdir();shutil.copytree(dist,isolated);testout=EVIDENCE/'SELFTEST';testout.mkdir();env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','IMAGEIO_FFMPEG_EXE'):env.pop(key,None)
        env['PYTHONUTF8']='1'
        execute([str(isolated/'PDRM_P01_Calibrate.exe'),'--self-test','--self-test-output',str(testout)],EVIDENCE/'SELFTEST.log',build,env,timeout=1800)
        summary=json.loads((testout/'P01_BUNDLE_SELFTEST.json').read_text(encoding='utf-8'))
        required=(summary.get('success') and summary.get('observer_provider')=='spleeter_runtime48' and summary.get('reference_count')==24 and summary.get('reference_codec')=='MP3' and summary.get('global_lossless_contract_relaxed') is False and summary.get('planner_implementation')==PLANNER)
        if not required:raise RuntimeError('Frozen private-calibration v51 self-test failed: '+json.dumps(summary))
        final=OUT/'PDRM_P01_Private_Calibration';shutil.copytree(dist,final)
        report=dict(success=True,commit=commit,accepted_p03a_commit='50a4592e45b3f810e905041c25cff1c3e35b2a88',planner_implementation=PLANNER,platform=platform.platform(),versions=versions,
            exe_sha256=sha(final/'PDRM_P01_Calibrate.exe'),exe_bytes=(final/'PDRM_P01_Calibrate.exe').stat().st_size,bundle_bytes=sum(p.stat().st_size for p in final.rglob('*') if p.is_file()),runtime_bytes=sum(p.stat().st_size for p in (final/'PDRM_OBSERVER_RUNTIME').rglob('*') if p.is_file()),
            frozen_selftest=summary,private_audio_used=False,private_audio_upload_path=False,product_release=False,user_python_required=False)
        (EVIDENCE/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print('P01_V51_PRIVATE_BUNDLE '+json.dumps(report,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
