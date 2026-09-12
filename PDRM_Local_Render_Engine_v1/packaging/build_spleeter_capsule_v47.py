"""Build a self-contained Windows-x64 Spleeter observer runtime capsule.

Build-time network is allowed for official CPython/PyPI/Spleeter release assets.
The resulting runtime needs no host Python/TensorFlow and performs no model
download at song-processing time. It is a worker component, not the PDRM GUI.
"""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,os,platform,shutil,subprocess,sys,tarfile,tempfile,urllib.request,zipfile

ROOT=Path(__file__).resolve().parents[1]
PYTHON_VERSION='3.11.9'
PYTHON_URL=f'https://www.python.org/ftp/python/{PYTHON_VERSION}/python-{PYTHON_VERSION}-embed-amd64.zip'
SPLEETER_RELEASE='v1.4.0'
SPLEETER_BASE=f'https://github.com/deezer/spleeter/releases/download/{SPLEETER_RELEASE}'
MODEL_ASSET='4stems.tar.gz'
PACKAGES=(
    'tensorflow==2.12.1','numpy==1.23.5','scipy==1.10.1','soundfile==0.12.1','pandas==1.5.3',
    'norbert==0.2.1','ffmpeg-python==0.2.0','httpx[http2]==0.19.0','typer==0.3.2',
)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,allow_nan=False,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()


def download(url,path):
    with urllib.request.urlopen(url,timeout=90) as r,Path(path).open('wb') as f:
        while True:
            b=r.read(2**20)
            if not b:break
            f.write(b)


def safe_tar(archive,dest):
    dest=Path(dest).resolve()
    with tarfile.open(archive,'r:gz') as t:
        members=t.getmembers()
        for m in members:
            target=(dest/m.name).resolve()
            if dest not in target.parents and target!=dest:raise RuntimeError('Model archive path escape')
            if m.issym() or m.islnk():raise RuntimeError('Model archive links refused')
        t.extractall(dest,members=members)


def run(cmd,**kw):
    print('RUN',json.dumps([str(v) for v in cmd]),flush=True)
    return subprocess.run([str(v) for v in cmd],check=True,**kw)


def configure_embed(runtime):
    p=runtime/'python311._pth';text=p.read_text(encoding='utf-8')
    lines=[]
    for line in text.splitlines():
        if line.strip()=='#import site':lines.append('import site')
        else:lines.append(line)
    if 'Lib\\site-packages' not in lines:lines.insert(-1 if lines and lines[-1]=='import site' else len(lines),'Lib\\site-packages')
    p.write_text('\n'.join(lines)+'\n',encoding='utf-8')


def package_versions(python,runtime):
    code="import importlib.metadata as i,json;print(json.dumps({n:i.version(n) for n in ['spleeter','tensorflow','numpy','scipy','soundfile','pandas','norbert','ffmpeg-python','httpx','typer','tensorflow-io-gcs-filesystem']},sort_keys=True))"
    out=subprocess.check_output([str(python),'-I','-c',code],cwd=runtime,text=True,encoding='utf-8')
    return json.loads(out.strip().splitlines()[-1])


def main():
    if sys.platform!='win32' or platform.machine().lower() not in ('amd64','x86_64'):raise RuntimeError('Windows x64 builder required')
    if sys.version_info[:2]!=(3,11):raise RuntimeError('Build host must use Python 3.11')
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,default=ROOT/'P02_CAPSULE_WORK');a=ap.parse_args()
    out=a.output.absolute()
    if out.exists():shutil.rmtree(out)
    out.mkdir(parents=True);runtime=out/'PDRM_OBSERVER_RUNTIME';runtime.mkdir()
    with tempfile.TemporaryDirectory(prefix='pdrm_spleeter_build_') as td:
        td=Path(td);embed=td/'python.zip';index=td/'checksum.json';asset=td/MODEL_ASSET
        download(PYTHON_URL,embed)
        with zipfile.ZipFile(embed) as z:z.extractall(runtime)
        configure_embed(runtime);site=runtime/'Lib'/'site-packages';site.mkdir(parents=True)
        run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-warn-script-location','--target',site,*PACKAGES])
        run([sys.executable,'-m','pip','install','--disable-pip-version-check','--no-deps','--target',site,'spleeter==2.4.2'])
        download(SPLEETER_BASE+'/checksum.json',index);download(SPLEETER_BASE+'/'+MODEL_ASSET,asset)
        checks=json.loads(index.read_text(encoding='utf-8'));expected=checks.get('4stems');actual=sha(asset)
        if not isinstance(expected,str) or expected!=actual:raise RuntimeError('Official Spleeter model archive checksum mismatch')
        model=runtime/'models'/'4stems';model.mkdir(parents=True);safe_tar(asset,model)
        # The official v1.4.0 archive contains macOS AppleDouble sidecars such as
        # ._checkpoint. They are not TensorFlow model components and may be
        # rewritten by NAS/filesystem tooling, so never package or attest them.
        ignored_metadata=[]
        for p in sorted(model.rglob('._*')):
            if p.is_file():
                ignored_metadata.append(str(p.relative_to(model)).replace('\\','/'));p.unlink()
        (model/'.probe').write_text('PDRM_OFFLINE_OK\n',encoding='utf-8')
    worker_source=ROOT/'observer_worker_spleeter_v47.py';worker=runtime/worker_source.name;shutil.copyfile(worker_source,worker)
    python=runtime/'python.exe';versions=package_versions(python,runtime)
    if versions['spleeter']!='2.4.2' or versions['tensorflow']!='2.12.1' or versions['tensorflow-io-gcs-filesystem']!='0.31.0':raise RuntimeError('Unexpected isolated dependency versions '+repr(versions))
    required_model_files=('checkpoint','model.data-00000-of-00001','model.index','model.meta')
    if any(not (model/name).is_file() for name in required_model_files):raise RuntimeError('Required Spleeter model file missing')
    model_files={}
    for p in sorted(model.rglob('*')):
        if p.is_file() and p.name!='.probe' and not p.name.startswith('._'):
            model_files[str(p.relative_to(model)).replace('\\','/')]=dict(sha256=sha(p),bytes=p.stat().st_size)
    if not model_files:raise RuntimeError('No packaged model files')
    manifest=dict(schema=1,runtime='CPython-embed-win_amd64',python_version=PYTHON_VERSION,python_embed_url=PYTHON_URL,python_embed_sha256=sha(out/'PDRM_OBSERVER_RUNTIME'/'python311.zip'),
        worker_version='spleeter-observer-worker-0.1.0',worker_sha256=sha(worker),spleeter_release=SPLEETER_RELEASE,
        model_asset=MODEL_ASSET,model_asset_url=SPLEETER_BASE+'/'+MODEL_ASSET,model_asset_sha256=actual,
        model_files=model_files,ignored_archive_metadata=ignored_metadata,packages=versions,source_order=['mix','drums','bass','other','vocals'],
        preprocessing=dict(separator_rate_hz=44100,feature_rate_hz=12000,feature_hop_samples=120,feature_window_samples=720,
            bands_hz=dict(low=[25,120],body=[120,300],focus=[300,450],upper_focus=[450,700]),contexts_required=2,max_core_seconds=16,max_pad_seconds=4),
        offline_policy=dict(model_download_at_runtime=False,stem_audio_persisted=False,stem_audio_in_master=False),
        known_windows_metadata_exception='spleeter 2.4.2 declares tensorflow-io-gcs-filesystem==0.32.0; Windows TensorFlow 2.12.1 resolves 0.31.0; actual offline inference is separately required',
        product_quality='NOT_EVALUATED')
    manifest['sha256']=digest(manifest);(runtime/'PDRM_OBSERVER_RUNTIME_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    selftest=subprocess.check_output([str(python),'-I',str(worker),'--self-test'],cwd=runtime,text=True,encoding='utf-8',stderr=subprocess.STDOUT)
    result=dict(success=True,runtime_dir=str(runtime),runtime_bytes=sum(p.stat().st_size for p in runtime.rglob('*') if p.is_file()),file_count=sum(1 for p in runtime.rglob('*') if p.is_file()),
        manifest_sha256=manifest['sha256'],model_asset_sha256=actual,worker_sha256=manifest['worker_sha256'],ignored_archive_metadata=ignored_metadata,versions=versions,selftest=selftest.strip(),host_python=sys.version)
    (out/'BUILD_RESULT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('P02_CAPSULE_BUILD '+json.dumps(result,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
