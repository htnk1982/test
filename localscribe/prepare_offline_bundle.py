"""Distributor-only optional packer. Not a task for the end user's company PC.
Downloads public pinned packages/models, checks publisher hashes, makes offline/.
Does NOT certify imports or NPU compatibility. Run Windows tests separately.
"""
from pathlib import Path
import argparse
import json
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'assets'))
from common import PYTHON_VERSION, PYTHON_SHA256, sha256, write_json
from install import download, prepare_runtime, prepare_model

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    a=ap.parse_args();dest=a.output.resolve()
    dest.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='localscribe-distributor-') as td:
        stage=Path(td);no_offline=stage/'empty';no_offline.mkdir()
        name=f'python-{PYTHON_VERSION}-embed-amd64.zip'
        download(f'https://www.python.org/ftp/python/{PYTHON_VERSION}/{name}',dest/name,PYTHON_SHA256,None,print,limit=30_000_000)
        prepare_runtime(stage,no_offline,print)
        prepare_model(stage,no_offline,print)
        for src in (stage/'downloads').glob('*.whl'):shutil.copy2(src,dest/src.name)
        shutil.copy2(stage/'locks/runtime.json',dest/'runtime-lock.json')
        shutil.copy2(stage/'locks/model.json',dest/'model-lock.json')
        shutil.copytree(stage/'model',dest/'model')
        hashes={p.relative_to(dest).as_posix():sha256(p) for p in sorted(dest.rglob('*')) if p.is_file()}
        write_json(dest/'bundle_manifest.json',{'status':'bytes_and_hashes_only_windows_npu_not_tested','sha256':hashes})
    print(dest)
if __name__=='__main__':main()
