"""Developer VM: assemble vendor binaries locally; export technical evidence only."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EVIDENCE = REPO / 'package-evidence'
WORK = Path(os.environ['RUNNER_TEMP']) / 'LocalScribe package build'


def execute(command, **kwargs):
    print('BUILD_STAGE:', str(command[0]), flush=True)
    subprocess.run([str(x) for x in command], check=True, timeout=1200, **kwargs)


def main():
    if sys.platform != 'win32':
        raise RuntimeError('Windows build is required')
    EVIDENCE.mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    wheels = WORK / 'wheels'
    wheels.mkdir(exist_ok=True)
    req = ROOT / 'ci' / 'package-requirements.txt'
    execute([sys.executable, '-m', 'pip', 'download', '--only-binary=:all:',
             '--disable-pip-version-check', '--index-url', 'https://pypi.org/simple',
             '--dest', wheels, '-r', req])
    rows, inventory = [], []
    for path in sorted(wheels.glob('*.whl')):
        with zipfile.ZipFile(path) as archive:
            metadata_names = [n for n in archive.namelist()
                              if n.count('/') == 1 and n.endswith('.dist-info/METADATA')]
            if len(metadata_names) != 1:
                raise RuntimeError('Ambiguous root wheel metadata: ' + path.name + ': ' + repr(metadata_names))
            from email.parser import BytesParser
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
        if not metadata['Name'] or not metadata['Version']:
            raise RuntimeError('Incomplete wheel metadata: ' + path.name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rows.append(f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{digest}")
        inventory.append(dict(name=metadata['Name'], version=metadata['Version'], filename=path.name, sha256=digest))
    lock = EVIDENCE / 'windows-build.lock.txt'
    lock.write_text('\n'.join(rows) + '\n', encoding='utf-8')
    (EVIDENCE / 'wheels.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    print('RESOLVED_LOCK_BEGIN\n' + '\n'.join(rows) + '\nRESOLVED_LOCK_END', flush=True)
    venv = WORK / 'venv'
    execute([sys.executable, '-m', 'venv', venv])
    python = venv / 'Scripts' / 'python.exe'
    execute([python, '-m', 'pip', 'install', '--no-index', '--find-links', wheels,
             '--require-hashes', '--disable-pip-version-check', '-r', lock])
    execute([python, '-m', 'pip', 'check'])
    execute([python, ROOT / 'ci' / 'package_build.py', '--assemble'], cwd=REPO)


def assemble():
    sys.path.insert(0, str(ROOT))
    from desktop.model_guard import MODEL_ID, REVISION, HASHES, verify_model, digest
    from huggingface_hub import hf_hub_download
    EVIDENCE.mkdir(exist_ok=True)
    source_model = WORK / 'model'
    for name in list(HASHES) + ['README.md']:
        hf_hub_download(MODEL_ID, name, revision=REVISION, local_dir=source_model, token=False)
    verify_model(source_model)
    fixture = Path(hf_hub_download('japanese-asr/ja_asr.jsut_basic5000', 'sample.flac',
        repo_type='dataset', revision='278db379fc96167ff2293d7abf9ab86976afcd78',
        local_dir=WORK / 'fixture', token=False))
    if digest(fixture) != '405c0e8fc9dab69497f2068e06f6bc23324af022aed1644472fcc5a2231d32f7':
        raise RuntimeError('Fixture digest mismatch')
    execute([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
             '--distpath', WORK / 'dist', '--workpath', WORK / 'freeze',
             ROOT / 'desktop_candidate.spec'], cwd=ROOT)
    bundle = WORK / 'dist' / 'LocalScribeNPU'
    (bundle / 'models').mkdir()
    for name in list(HASHES) + ['README.md']:
        shutil.copy2(source_model / name, bundle / 'models' / name)
    shutil.copy2(ROOT / 'LICENSE.txt', bundle / 'LICENSE.txt')
    shutil.copy2(ROOT / 'desktop' / 'README.md', bundle / 'README.md')
    licenses = bundle / 'licenses'
    licenses.mkdir()
    import importlib.metadata
    for dist in importlib.metadata.distributions():
        for entry in dist.files or []:
            if any(token in str(entry).lower() for token in ('license', 'copying', 'notice')):
                original = Path(dist.locate_file(entry))
                if original.is_file() and original.stat().st_size < 2000000:
                    safe = (dist.metadata['Name'] + '__' + str(entry)).replace('/', '_').replace('\\', '_')
                    shutil.copy2(original, licenses / safe)
    manifest = {str(p.relative_to(bundle)).replace('\\', '/'): digest(p)
                for p in sorted(bundle.rglob('*')) if p.is_file()}
    (bundle / 'BUNDLE_SHA256.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    archive = Path(shutil.make_archive(str(WORK / 'LocalScribeNPU_candidate'), 'zip', bundle.parent, bundle.name))
    unpack = WORK / '日本語 展開先'
    unpack.mkdir()
    with zipfile.ZipFile(archive) as z:
        z.extractall(unpack)
    assembled = unpack / 'LocalScribeNPU'
    for relative, expected in manifest.items():
        if digest(assembled / relative) != expected:
            raise RuntimeError('Packaged bytes changed on extraction')
    build = dict(commit=os.environ.get('LS_SOURCE_SHA'), archive_sha256=digest(archive),
                 archive_bytes=archive.stat().st_size, bundle_bytes=sum(p.stat().st_size for p in assembled.rglob('*') if p.is_file()),
                 exe_sha256=digest(assembled / 'LocalScribeNPU.exe'), file_count=len(manifest),
                 model_verified=True, binary_exported=False, product_release_approved=False)
    (EVIDENCE / 'build.json').write_text(json.dumps(build, indent=2), encoding='utf-8')
    print('PACKAGE_BUILD_RESULT:', json.dumps(build), flush=True)
    execute([sys.executable, ROOT / 'ci' / 'frozen_gui_gate.py', assembled, fixture, EVIDENCE], cwd=REPO)


if __name__ == '__main__':
    try:
        if '--assemble' in sys.argv:
            assemble()
        else:
            main()
    except Exception as exc:
        import traceback
        EVIDENCE.mkdir(exist_ok=True)
        details = dict(outcome='failed', error_type=type(exc).__name__,
                       error=str(exc), traceback=traceback.format_exc(), product_release_approved=False)
        name = 'assemble-error.json' if '--assemble' in sys.argv else 'build-error.json'
        (EVIDENCE / name).write_text(json.dumps(details, indent=2), encoding='utf-8')
        if not (EVIDENCE / 'SUMMARY.md').exists():
            (EVIDENCE / 'SUMMARY.md').write_text('# LocalScribe package build failed\n\n' +
                type(exc).__name__ + '\nNo release is approved.\n', encoding='utf-8')
        raise
