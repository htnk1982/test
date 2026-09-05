"""Build in a clean Windows environment. No edits to the adopted DSP modules."""
from pathlib import Path
import argparse
import hashlib
import importlib.metadata as md
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

MODULES = ('processed_finish', 'distribution_finish', 'distribution_peak',
           'accepted_finish', 'note_sub_lab', 'note_sub_lab_v02', 'hf_temporal_contrast_lab')
PACKAGES = ('numpy', 'scipy', 'soundfile', 'pyloudnorm', 'psutil', 'imageio-ffmpeg', 'cffi', 'pycparser')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def get(url, dest):
    with urllib.request.urlopen(url, timeout=120) as src, dest.open('wb') as out:
        shutil.copyfileobj(src, out)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--codec', required=True, type=Path)
    args = ap.parse_args(); codec = args.codec.resolve(); root = Path.cwd().resolve()
    if sys.platform != 'win32':
        raise RuntimeError('Windows PyInstaller must run on Windows')
    ff = codec / 'ffmpeg.exe'
    version = subprocess.check_output([str(ff), '-hide_banner', '-version'], text=True, encoding='utf-8')
    if '--enable-gpl' in version or '--enable-nonfree' in version:
        raise RuntimeError('This package only permits the minimal LGPL codec build')
    work = root / 'build_exe_assets'; work.mkdir(exist_ok=True)
    hooks = work / 'hooks'; hooks.mkdir(exist_ok=True)
    (hooks / 'hook-processed_finish.py').write_text('module_collection_mode = ' + repr({n: 'py' for n in MODULES}) + '\n', encoding='utf-8')
    (hooks / 'hook-imageio_ffmpeg.py').write_text('datas = []\nbinaries = []\n', encoding='utf-8')
    resources = {n+'.py': sha(root/(n+'.py')) for n in MODULES}
    resources['native/ffmpeg.exe'] = sha(ff)
    manifest = dict(app_version='2.1.1-exe', resources=resources,
                    source_commit=os.environ.get('GITHUB_SHA', 'local'),
                    versions={n:md.version(n) for n in PACKAGES}, ffmpeg_version=version,
                    native_recipe='packaging/build_codec.sh', signing='UNSIGNED')
    (work / 'BUNDLE_MANIFEST.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    from PyInstaller.utils.hooks import copy_metadata
    datas = [(str(work/'BUNDLE_MANIFEST.json'), '.')]
    for name in PACKAGES:
        datas.extend(copy_metadata(name))
    spec = f'''# Generated from packaging/build_windows.py
from pathlib import Path
a = Analysis([{str(root/'processed_exe_entry.py')!r}], pathex=[{str(root)!r}],
    binaries=[({str(ff)!r}, 'native')], datas={datas!r},
    hiddenimports={list(MODULES) + ['_cffi_backend', 'imageio_ffmpeg', 'tkinter', 'tkinter.filedialog']!r},
    hookspath=[{str(hooks)!r}], excludes=['pytest','IPython','matplotlib','pandas','torch','scipy.tests','numpy.tests'],
    noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='PDRM_Processed',
    console=True, debug=False, strip=False, upx=False, uac_admin=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='PDRM_Processed')
'''
    specpath = work/'PDRM_Processed.spec'; specpath.write_text(spec, encoding='utf-8')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--clean', '--noconfirm',
                    '--distpath', str(root/'dist'), '--workpath', str(root/'build_pyinstaller'), str(specpath)], check=True)
    dest = root/'dist'/'PDRM_Processed'
    licenses = dest/'LICENSES'; sources = dest/'SOURCES'
    licenses.mkdir(exist_ok=True); sources.mkdir(exist_ok=True)
    shutil.copytree(codec/'LICENSES', licenses/'native-codec', dirs_exist_ok=True)
    shutil.copytree(codec/'SOURCES', sources/'native-codec', dirs_exist_ok=True)
    (licenses/'FFMPEG_VERSION_AND_CONFIG.txt').write_text(version, encoding='utf-8')
    for name in (*PACKAGES, 'pyinstaller', 'pyinstaller-hooks-contrib'):
        dist = md.distribution(name)
        for f in dist.files or []:
            low = str(f).lower()
            if any(w in low for w in ('license', 'copying', 'copyright', 'notice')):
                p = Path(dist.locate_file(f))
                if p.is_file() and p.suffix.lower() not in ('.pyc', '.py', '.pyd'):
                    target = licenses/name/Path(str(f).replace('..', '__'))
                    target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p,target)
    for base, prefix in ((Path(sys.base_prefix), 'python'),):
        p = base/'LICENSE.txt'
        if p.is_file(): shutil.copy2(p, licenses/(prefix+'-LICENSE.txt'))
        for p in (base/'tcl').glob('*/license.terms'):
            shutil.copy2(p, licenses/('tcl-'+p.parent.name+'-license.txt'))
    import soundfile as sf
    libver = sf.__libsndfile_version__
    get(f'https://github.com/libsndfile/libsndfile/releases/download/{libver}/libsndfile-{libver}.tar.xz',
        sources/f'libsndfile-{libver}.tar.xz')
    data = json.load(urllib.request.urlopen(f'https://pypi.org/pypi/soundfile/{md.version("soundfile")}/json', timeout=60))
    for item in data['urls']:
        if item['packagetype'] == 'sdist':
            target = sources/item['filename']; get(item['url'], target)
            if sha(target) != item['digests']['sha256']: raise RuntimeError('SoundFile source checksum differs')
    with zipfile.ZipFile(sources/'PDRM_APPLICATION_SOURCE.zip', 'w', zipfile.ZIP_DEFLATED) as z:
        for name in MODULES + ('processed_exe_entry',): z.write(root/(name+'.py'), name+'.py')
        for p in (root/'packaging').rglob('*'):
            if p.is_file() and '__pycache__' not in str(p): z.write(p, p.relative_to(root))
        for p in (root/'tests').glob('test_*.py'): z.write(p, p.relative_to(root))
        z.write(root/'docs/WINDOWS_EXE_GUIDE.md', 'WINDOWS_EXE_GUIDE.md')
    notices = '''# Third-party notices / ソースとライセンス

This distribution includes Python, Tcl/Tk, NumPy, SciPy, SoundFile/libsndfile,
cffi, pycparser, pyloudnorm, psutil and the PyInstaller bootloader.
Their notices are retained in LICENSES and _internal/*dist-info.
FFmpeg is a separate executable built with GPL/nonfree components disabled,
linked only to the LAME MP3 library. Its exact source archives and build recipe
are in SOURCES/native-codec. No imageio-supplied GPL FFmpeg binary is shipped.
The libsndfile shared library may be replaced with a compatible build;
its matching release sources and SoundFile wheel build instructions are provided.
No restriction on debugging modifications to LGPL components is imposed.
PDRM processing source is included for integrity checks and reproducibility.
Keep this complete folder, notices and source archives together when redistributing.
No code-signing certificate or trademark/patent clearance is supplied.

Upstream: https://ffmpeg.org/legal.html ; https://lame.sourceforge.io/ ;
https://libsndfile.github.io/libsndfile/ ; https://github.com/bastibe/python-soundfile ;
https://pyinstaller.org/en/stable/license.html
'''
    (dest/'THIRD_PARTY_NOTICES.md').write_text(notices, encoding='utf-8')
    shutil.copy2(root/'docs/WINDOWS_EXE_GUIDE.md', dest/'使い方.md')
    for name in ('SOURCE_TEST_RESULTS.json',):
        if (root/name).exists(): shutil.copy2(root/name,dest/name)
    manifest.update(python=sys.version, libsndfile=libver, pyinstaller=md.version('pyinstaller'))
    (dest/'BUILD_REPORT.json').write_text(json.dumps(manifest,indent=2), encoding='utf-8')
    exes = [p for p in dest.rglob('*.exe')]
    if sorted(p.name for p in exes) != ['PDRM_Processed.exe','ffmpeg.exe']:
        raise RuntimeError('Unexpected executable in bundle: ' + repr(exes))
    print(dest)


if __name__ == '__main__': main()
