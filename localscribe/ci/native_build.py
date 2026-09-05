"""Build and test an offline bundled developer candidate. Never includes test audio or transcripts in artifacts."""
from pathlib import Path
import hashlib
import importlib.metadata
import json
import math
import os
import shutil
import subprocess
import sys
import traceback
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
WORK = Path(os.environ['RUNNER_TEMP']) / 'LocalScribe native build'
EVIDENCE = REPO / 'native-evidence'


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(command, timeout=1200, **kw):
    subprocess.run([str(x) for x in command], check=True, timeout=timeout, **kw)


def main():
    WORK.mkdir(exist_ok=True)
    EVIDENCE.mkdir(exist_ok=True)
    wheels = WORK/'wheels'
    wheels.mkdir(exist_ok=True)
    lock = ROOT/'ci'/'native-build.lock.txt'
    run([sys.executable,'-m','pip','download','--require-hashes','--only-binary=:all:',
         '--disable-pip-version-check','--index-url','https://pypi.org/simple',
         '-r',lock,'--dest',wheels])
    venv = WORK/'venv'
    run([sys.executable,'-m','venv',venv])
    python = venv/'Scripts'/'python.exe'
    run([python,'-m','pip','install','--no-index','--find-links',wheels,'--require-hashes',
         '--disable-pip-version-check','-r',lock])
    run([python,'-m','pip','check'])
    shutil.copy2(lock,EVIDENCE/lock.name)
    run([python,Path(__file__),'--assemble'])


def assemble():
    sys.path.insert(0,str(ROOT))
    from desktop.model_guard import MODEL_ID, REVISION, HASHES, verify_model
    from huggingface_hub import hf_hub_download
    import soundfile as sf
    import numpy as np
    from scipy.signal import resample_poly
    model = WORK/'model'
    for name in list(HASHES)+['README.md']:
        hf_hub_download(MODEL_ID,name,revision=REVISION,local_dir=model,token=False)
    verify_model(model)
    card=(model/'README.md').read_text(encoding='utf-8')
    if 'license: mit' not in card:raise RuntimeError('Expected model license was not declared')
    original=Path(hf_hub_download('japanese-asr/ja_asr.jsut_basic5000','sample.flac',repo_type='dataset',
        revision='278db379fc96167ff2293d7abf9ab86976afcd78',local_dir=WORK/'fixture',token=False))
    if digest(original)!='405c0e8fc9dab69497f2068e06f6bc23324af022aed1644472fcc5a2231d32f7':
        raise RuntimeError('Fixture bytes changed')
    fixture_dir=WORK/'日本語 入力';fixture_dir.mkdir()
    fixture=fixture_dir/'日本語 音声.flac';shutil.copy2(original,fixture)
    sf.write(fixture_dir/'silence.wav',np.zeros(16000),16000)
    samples,rate=sf.read(fixture,dtype='float32')
    d=math.gcd(rate,48000)
    stereo=resample_poly(samples,48000//d,rate//d)*0.8
    sf.write(fixture_dir/'stereo.wav',np.column_stack((stereo,stereo)),48000,subtype='PCM_16')
    run([sys.executable,'-m','PyInstaller','--noconfirm','--clean',
         '--distpath',WORK/'dist','--workpath',WORK/'freeze',ROOT/'native_host'/'worker.spec'],cwd=ROOT)
    bundle=WORK/'bundle'/'LocalScribeNPU'
    bundle.mkdir(parents=True)
    shutil.copytree(WORK/'dist'/'WhisperWorker',bundle/'worker')
    (bundle/'worker'/'models').mkdir()
    for name in list(HASHES)+['README.md']:
        shutil.copy2(model/name,bundle/'worker'/'models'/name)
    compiler=Path(os.environ['WINDIR'])/'Microsoft.NET'/'Framework64'/'v4.0.30319'/'csc.exe'
    run([compiler,'/nologo','/target:winexe','/platform:x64','/optimize+',
         '/r:System.Windows.Forms.dll','/r:System.Drawing.dll','/r:System.Web.Extensions.dll','/r:System.Core.dll',
         '/win32manifest:'+str(ROOT/'src'/'app.manifest'),'/out:'+str(bundle/'LocalScribeNPU.exe'),ROOT/'native_host'/'Host.cs'])
    (bundle/'worker.sha256').write_text(digest(bundle/'worker'/'WhisperWorker.exe')+'\n',encoding='ascii')
    (bundle/'LocalScribeNPU.exe.config').write_text('<?xml version="1.0"?><configuration><startup><supportedRuntime version="v4.0" sku=".NETFramework,Version=v4.8"/></startup></configuration>',encoding='utf-8')
    shutil.copy2(ROOT/'LICENSE.txt',bundle/'LICENSE.txt')
    shutil.copy2(ROOT/'native_host'/'README.md',bundle/'README.md')
    licenses=bundle/'licenses';licenses.mkdir()
    shutil.copy2(ROOT/'native_host'/'WHISPER_LICENSE.txt',licenses/'WHISPER_LICENSE.txt')
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
            p=Path(dist.locate_file(entry))
            if any(t in str(entry).lower() for t in ('license','copying','notice')) and p.is_file() and p.stat().st_size<2000000:
                name=(dist.metadata['Name']+'__'+str(entry)).replace('/','_').replace('\\','_')
                shutil.copy2(p,licenses/name)
    for name in ('LICENSE.txt','LICENSE'):
        p=Path(sys.base_prefix)/name
        if p.is_file():shutil.copy2(p,licenses/('Python_'+name))
    if any(p.suffix.lower() in ('.ttf','.otf','.woff','.woff2','.wav','.flac') for p in bundle.rglob('*')):
        raise RuntimeError('Font or test-audio files are prohibited in this artifact')
    files={str(p.relative_to(bundle)).replace('\\','/'):digest(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    (bundle/'BUNDLE_SHA256.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
    archive=Path(shutil.make_archive(str(WORK/'LocalScribeNPU_0.5.0_win-x64_candidate'),'zip',bundle.parent,bundle.name))
    unpack=WORK/'日本語 展開先';unpack.mkdir()
    with zipfile.ZipFile(archive) as z:z.extractall(unpack)
    extracted=unpack/'LocalScribeNPU'
    for name,h in files.items():
        if digest(extracted/name)!=h:raise RuntimeError('ZIP roundtrip mismatch')
    env=os.environ.copy()
    env['PATH']=os.environ['WINDIR']+'\\System32;'+os.environ['WINDIR']
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    powershell=Path(os.environ['WINDIR'])/'System32'/'WindowsPowerShell'/'v1.0'/'powershell.exe'
    run([powershell,'-NoProfile','-NonInteractive','-File',ROOT/'ci'/'native_offline_gate.ps1',
         '-Bundle',extracted,'-Fixture',fixture,'-Evidence',EVIDENCE],timeout=1000,env=env)
    evidence=[json.loads((EVIDENCE/('gui_'+str(i)+'.json')).read_text(encoding='utf-8-sig')) for i in range(2)]
    if any(r.get('outcome')!='passed' for r in evidence):raise RuntimeError('Native GUI acceptance failed')
    network=json.loads((EVIDENCE/'network.json').read_text(encoding='utf-8-sig'))
    if network.get('outcome')!='passed':raise RuntimeError('Offline rules were not confirmed')
    result=dict(outcome='bounded_native_gui_cpu_passed',commit=os.environ.get('LS_SOURCE_SHA'),
        archive_sha256=digest(archive),archive_bytes=archive.stat().st_size,
        bundle_bytes=sum(p.stat().st_size for p in bundle.rglob('*') if p.is_file()),
        file_count=len(files),tests=evidence,npu_tested=False,live_tested=False,
        network_isolation=network,binary_exported=False,product_release_approved=False)
    (EVIDENCE/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (EVIDENCE/'SUMMARY.md').write_text('# Native GUI gate\n\nBounded worker, extracted EXE and outbound-denied CPU file tests passed.\nNPU/live/product not accepted.\n',encoding='utf-8')
    print('NATIVE_PACKAGE_RESULT:',json.dumps(result,ensure_ascii=True),flush=True)
    # Retain only the exact tested developer candidate. No final release or test audio.
    target=REPO/'candidate-artifact';target.mkdir()
    shutil.copy2(archive,target/archive.name)
    (target/'SHA256.txt').write_text(result['archive_sha256']+'  '+archive.name+'\n',encoding='ascii')


if __name__=='__main__':
    try:
        if '--assemble' in sys.argv:assemble()
        else:main()
    except Exception:
        EVIDENCE.mkdir(exist_ok=True)
        name='assembly_failure.txt' if '--assemble' in sys.argv else 'build_failure.txt'
        (EVIDENCE/name).write_text(traceback.format_exc(),encoding='utf-8')
        raise
