"""Developer Windows bundle construction and actual desktop acceptance.
Vendor clients are used only in the build environment. Public fixture/transcript
bytes are not exported. This stage retains technical evidence only.
"""
from pathlib import Path
import hashlib
import importlib.metadata
import json
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
    model = WORK/'model'
    for name in list(HASHES)+['README.md']:
        hf_hub_download(MODEL_ID,name,revision=REVISION,local_dir=model,token=False)
    verify_model(model)
    card=(model/'README.md').read_text(encoding='utf-8')
    print('MODEL_LICENSE_LINES:',json.dumps([l for l in card.splitlines() if 'license' in l.lower()],ensure_ascii=True))
    fixture=Path(hf_hub_download('japanese-asr/ja_asr.jsut_basic5000','sample.flac',repo_type='dataset',
        revision='278db379fc96167ff2293d7abf9ab86976afcd78',local_dir=WORK/'fixture',token=False))
    if digest(fixture)!='405c0e8fc9dab69497f2068e06f6bc23324af022aed1644472fcc5a2231d32f7':
        raise RuntimeError('Fixture bytes changed')
    sf.write(fixture.parent/'silence.wav',np.zeros(16000),16000)
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
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
            p=Path(dist.locate_file(entry))
            if any(t in str(entry).lower() for t in ('license','copying','notice')) and p.is_file() and p.stat().st_size<2000000:
                name=(dist.metadata['Name']+'__'+str(entry)).replace('/','_').replace('\\','_')
                shutil.copy2(p,licenses/name)
    for name in ('LICENSE.txt','LICENSE'):
        p=Path(sys.base_prefix)/name
        if p.is_file():shutil.copy2(p,licenses/('Python_'+name))
    if any(p.suffix.lower() in ('.ttf','.otf','.woff','.woff2') for p in bundle.rglob('*')):
        raise RuntimeError('Do not redistribute system font files')
    files={str(p.relative_to(bundle)).replace('\\','/'):digest(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    (bundle/'BUNDLE_SHA256.json').write_text(json.dumps(files,indent=2),encoding='utf-8')
    archive=Path(shutil.make_archive(str(WORK/'LocalScribeNPU_0.5.0_candidate'),'zip',bundle.parent,bundle.name))
    unpack=WORK/'日本語 展開先';unpack.mkdir()
    with zipfile.ZipFile(archive) as z:z.extractall(unpack)
    extracted=unpack/'LocalScribeNPU'
    for name,h in files.items():
        if digest(extracted/name)!=h:raise RuntimeError('ZIP roundtrip mismatch')
    env=os.environ.copy()
    env['PATH']=os.environ['WINDIR']+'\\System32;'+os.environ['WINDIR']
    env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
    evidence=[]
    for index in range(2):
        private=WORK/('exercise_'+str(index));private.mkdir()
        try:
            run([extracted/'LocalScribeNPU.exe','--exercise',fixture,private],timeout=420,env=env)
        finally:
            if (private/'native-gui.json').is_file():
                shutil.copy2(private/'native-gui.json',EVIDENCE/('gui_'+str(index)+'.json'))
                print('GUI_REPORT:',(private/'native-gui.json').read_text(encoding='utf-8'),flush=True)
        report=json.loads((private/'native-gui.json').read_text(encoding='utf-8'))
        evidence.append(report)
        if report.get('outcome')!='passed':raise RuntimeError('Packaged native GUI did not pass')
    result=dict(outcome='bounded_native_gui_cpu_passed',commit=os.environ.get('LS_SOURCE_SHA'),
        archive_sha256=digest(archive),archive_bytes=archive.stat().st_size,
        file_count=len(files),tests=evidence,npu_tested=False,live_tested=False,
        network_isolation_tested=False,binary_exported=False,product_release_approved=False)
    (EVIDENCE/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (EVIDENCE/'SUMMARY.md').write_text('# Native GUI gate\n\nBounded local worker: CPU file gate passed.\nNPU/live/product not accepted.\n',encoding='utf-8')
    print('NATIVE_PACKAGE_RESULT:',json.dumps(result,ensure_ascii=True),flush=True)


if __name__=='__main__':
    try:
        if '--assemble' in sys.argv:assemble()
        else:main()
    except Exception:
        EVIDENCE.mkdir(exist_ok=True)
        (EVIDENCE/'build_failure.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
