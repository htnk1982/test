"""Add Microsoft VC++ app-local runtime DLLs to the isolated PDRM observer capsule.

The CPython Windows embeddable distribution does not provide the Microsoft C/C++
runtime required by native wheels such as NumPy/SciPy/TensorFlow. CI hosts often
have those DLLs globally, which can hide a broken distributable. This script
copies the redistributable VC143 CRT/OpenMP DLLs from the Visual Studio redist
folder into the capsule root and seals their hashes for artifact verification.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys

ROOT=Path(__file__).resolve().parents[1]
RUNTIME=ROOT/'P02_CAPSULE_WORK'/'PDRM_OBSERVER_RUNTIME'
MANIFEST='PDRM_NATIVE_RUNTIME_MANIFEST.json'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def version_key(path):
    parts=[]
    for token in path.name.split('.'):
        try:parts.append(int(token))
        except ValueError:parts.append(-1)
    return tuple(parts)


def find_redist():
    pf=Path(os.environ.get('ProgramFiles',r'C:\Program Files'))
    base=pf/'Microsoft Visual Studio'/'2022'
    candidates=[]
    for edition in ('Enterprise','Professional','Community','BuildTools'):
        redist=base/edition/'VC'/'Redist'/'MSVC'
        if redist.is_dir():
            candidates.extend(p for p in redist.iterdir() if p.is_dir())
    if not candidates:raise RuntimeError('Visual Studio VC redistributable directory not found on builder')
    version=max(candidates,key=version_key)
    crt=version/'x64'/'Microsoft.VC143.CRT'
    if not crt.is_dir():raise RuntimeError('Microsoft.VC143.CRT x64 directory missing: '+str(crt))
    openmp=version/'x64'/'Microsoft.VC143.OpenMP'
    return version,crt,openmp


def main():
    if sys.platform!='win32':raise RuntimeError('Windows only')
    if not RUNTIME.is_dir():raise RuntimeError('Observer runtime must be built first')
    version,crt,openmp=find_redist();sources=list(crt.glob('*.dll'))
    if openmp.is_dir():sources.extend(openmp.glob('*.dll'))
    if not sources:raise RuntimeError('No VC redistributable DLLs found')
    copied={}
    for src in sorted(sources,key=lambda p:p.name.lower()):
        dest=RUNTIME/src.name
        shutil.copy2(src,dest)
        copied[src.name]=dict(sha256=sha(dest),bytes=dest.stat().st_size,source=str(src))
    required=('vcruntime140.dll','vcruntime140_1.dll','msvcp140.dll','concrt140.dll')
    missing=[name for name in required if name not in copied]
    if missing:raise RuntimeError('Required VC runtime DLL missing: '+','.join(missing))
    python=RUNTIME/'python.exe'
    code="import json,numpy,scipy,soundfile,tensorflow as tf;print(json.dumps({'success':True,'numpy':numpy.__version__,'scipy':scipy.__version__,'soundfile':soundfile.__version__,'tensorflow':tf.__version__}))"
    smoke=subprocess.check_output([str(python),'-I','-c',code],cwd=RUNTIME,text=True,encoding='utf-8',stderr=subprocess.STDOUT)
    payload=dict(schema=1,vc_redist_version=version.name,files=copied,required=list(required),native_import_smoke=json.loads(smoke.strip().splitlines()[-1]))
    payload['sha256']=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
    (RUNTIME/MANIFEST).write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print('PDRM_NATIVE_RUNTIME '+json.dumps(payload,ensure_ascii=True),flush=True)


if __name__=='__main__':main()
