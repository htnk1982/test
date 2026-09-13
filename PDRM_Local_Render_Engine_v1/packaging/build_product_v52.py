"""Build the P08 Windows product candidate as one GUI/worker EXE plus observer runtime.

No DSP thresholds are changed here. The frozen main excludes TensorFlow/Spleeter;
those remain in the already accepted sibling CPython 3.11 observer capsule.
The product now persists only sealed derived calibration metadata after a one-time
canonical-reference bootstrap; later runs skip reference decoding/calibration.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import hashlib,importlib.metadata as metadata,json,os,platform,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'P08_PRODUCT_BUNDLE';EVIDENCE=ROOT/'P08_PRODUCT_BUNDLE_EVIDENCE'
PLANNER='automatic-joint-lab-0.4.0';FINALIZER='auto-peak-v3.4.0'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()

def execute(command,log,cwd,env=None,timeout=2400):
    with Path(log).open('w',encoding='utf-8') as f:r=subprocess.run([str(v) for v in command],cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if r.returncode:
        text=Path(log).read_text(encoding='utf-8',errors='replace');print(text[-25000:],flush=True);raise RuntimeError('P08 product bundle step failed: '+str(log))


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
    with TemporaryDirectory(prefix='pdrm_p08_product_build_') as td:
        build=Path(td);hooks=build/'hooks';hooks.mkdir();root_py=sorted(ROOT.glob('*.py'));modes={p.stem:'py' for p in root_py}
        (hooks/'hook-product_app_v52.py').write_text('module_collection_mode = '+repr(modes)+'\n',encoding='utf-8')
        datas=[(str(p),'.') for p in root_py]
        for name in packages:datas.extend(copy_metadata(name))
        hidden=[
            'product_app_v52','product_worker_v52','product_gui_runtime_v52','product_processed_v52','product_selftest_v52','accepted_calibration_cache_v53',
            'natural_gui_v34','natural_gui_v44','gui_runtime_v44','target_settings','p01_private_calibration_bootstrap','p01_private_calibration_entry',
            'automatic_joint_v51','automatic_joint_v50','automatic_joint_v49','automatic_joint_v48','automatic_lowend_v41','source_events_v41','relative_low_dominance_v49','lowend_boundary_lab','context_occupancy_lab',
            'physical_add_bridge_v50','physical_add_bridge_v46','same_f0_permission_v50','event_groove_v37','joint_lowend_v46','joint_lowend_v42','physical_decay_bridge_v42',
            'spleeter_observer_adapter_v48','observer_runtime_client_v47','processed_integration','processed_finish','crash_recovery_v43',
            'integrated_finish_v40','distribution_finish','auto_peak_v34','offline_peak_stream_v34','offline_peak_lab','hf_temporal_contrast_lab',
            'imageio_ffmpeg','_cffi_backend','tkinter','tkinter.ttk','tkinter.filedialog','tkinter.messagebox']
        spec=f'''a=Analysis([{str(ROOT/'product_app_v52.py')!r}],pathex={[str(ROOT)]!r},\n binaries=[({str(ffmpeg)!r},'imageio_ffmpeg/binaries')],datas={datas!r},\n hiddenimports={hidden!r},hookspath={[str(hooks)]!r},\n excludes=['torch','torchaudio','tensorflow','spleeter','pandas','matplotlib','IPython','pytest'],noarchive=False)\npyz=PYZ(a.pure)\nexe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PDRM',console=False,debug=False,strip=False,upx=False,uac_admin=False)\ncoll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PDRM_Windows')\n'''
        specfile=build/'p08_product.spec';specfile.write_text(spec,encoding='utf-8');shutil.copyfile(specfile,EVIDENCE/'BUILD_SPEC.txt')
        execute([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(build/'dist'),'--workpath',str(build/'work'),str(specfile)],EVIDENCE/'BUILD.log',ROOT,timeout=1800)
        dist=build/'dist'/'PDRM_Windows';exe=dist/'PDRM.exe'
        if not exe.is_file():raise RuntimeError('Frozen PDRM product EXE missing')
        shutil.copytree(runtime,dist/'PDRM_OBSERVER_RUNTIME')
        readme=f'''PDRM Windows Product Candidate v53\n=================================\nPlanner: {PLANNER}\nFinalizer: {FINALIZER}\nDefault WAV: -12 LUFS-I / -2 dBTP\nDefault MP3: -14 LUFS-I / -2 dBTP\nBuild commit: {commit}\n\nDouble-click PDRM.exe and select one or more original WAV/FLAC files.\nOn the first run only, select the canonical reference.zip. PDRM builds the accepted calibration once, verifies its accepted SHA, and stores only sealed derived numerical metadata in LocalAppData.\nLater runs do not ask for reference.zip and do not run REFERENCE_CALIBRATION.\nThe first bootstrap also shares one feature scan between broad/context and relative calibration instead of scanning every reference twice.\nOriginal audio is never overwritten. Reference audio is not cached. Spleeter stems are analysis evidence only and are never exported or mixed into the master.\n'''
        (dist/'README_PDRM.txt').write_text(readme,encoding='utf-8')
        isolated=build/'日本語 空白'/'PDRM 製品候補';isolated.parent.mkdir();shutil.copytree(dist,isolated);testout=EVIDENCE/'SELFTEST';testout.mkdir();env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','IMAGEIO_FFMPEG_EXE'):env.pop(key,None)
        env['PYTHONUTF8']='1';env['TF_CPP_MIN_LOG_LEVEL']='2';env['OMP_NUM_THREADS']='2'
        execute([str(isolated/'PDRM.exe'),'--self-test','--self-test-output',str(testout)],EVIDENCE/'SELFTEST.log',build,env,timeout=1800)
        summary=json.loads((testout/'P08_PRODUCT_SELFTEST.json').read_text(encoding='utf-8'))
        required=(summary.get('success') and summary.get('frozen') and summary.get('planner_id')==PLANNER and summary.get('observer_provider')=='spleeter_runtime48' and summary.get('source_unchanged') and summary.get('stem_audio_in_master') is False and summary.get('calibration_single_pass_parity') and summary.get('cache_second_request_state')=='HIT' and summary.get('reference_free_second_request'))
        if not required:raise RuntimeError('Frozen P08 product/cache self-test failed: '+json.dumps(summary))
        final=OUT/'PDRM_Windows';shutil.copytree(dist,final)
        report=dict(success=True,product_release=False,stage='P08_B_CANDIDATE_V53_CACHE',commit=commit,planner=PLANNER,finalizer=FINALIZER,platform=platform.platform(),versions=versions,exe_sha256=sha(final/'PDRM.exe'),exe_bytes=(final/'PDRM.exe').stat().st_size,bundle_bytes=sum(p.stat().st_size for p in final.rglob('*') if p.is_file()),runtime_bytes=sum(p.stat().st_size for p in (final/'PDRM_OBSERVER_RUNTIME').rglob('*') if p.is_file()),runtime_manifest_sha256=summary.get('observer_runtime_manifest_sha256'),frozen_selftest=summary,private_audio_used=False,private_audio_upload_path=False,user_python_required=False,reference_audio_cached=False,accepted_calibration_cache=True)
        (EVIDENCE/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print('P08_PRODUCT_BUNDLE '+json.dumps(report,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
