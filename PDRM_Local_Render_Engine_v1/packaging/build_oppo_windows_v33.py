"""Build PDRM AUTO v3.3 in a clean Windows environment."""
from pathlib import Path
import argparse,hashlib,importlib.metadata as md,json,os,shutil,subprocess,sys,urllib.request,zipfile
MODULES=('processed_finish','processed_finish_v32','distribution_finish','distribution_peak','accepted_finish','note_sub_lab','note_sub_lab_v02','hf_temporal_contrast_lab',
 'target_settings','target_gui','natural_finish','natural_finish_v32','offline_peak_lab','offline_peak_stream','offline_peak_rescue','offline_peak_stream_v31','offline_peak_context','offline_peak_stream_v32',
 'note_sub_conditioned','natural_gui','workspace_cleanup','auto_peak_v33','auto_conditioned_v33','natural_finish_v33','natural_gui_v33')
PACKAGES=('numpy','scipy','soundfile','pyloudnorm','psutil','imageio-ffmpeg','cffi','pycparser')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def get(url,dest):
    with urllib.request.urlopen(url,timeout=120) as src,dest.open('wb') as out:shutil.copyfileobj(src,out)
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--codec',required=True,type=Path);args=ap.parse_args();codec=args.codec.resolve();root=Path.cwd().resolve()
    if sys.platform!='win32':raise RuntimeError('Windows PyInstaller must run on Windows')
    ff=codec/'ffmpeg.exe';version=subprocess.check_output([str(ff),'-hide_banner','-version'],text=True,encoding='utf-8')
    if '--enable-gpl' in version or '--enable-nonfree' in version:raise RuntimeError('Only minimal LGPL codec build is permitted')
    work=root/'build_exe_assets_v33';work.mkdir(exist_ok=True);hooks=work/'hooks';hooks.mkdir(exist_ok=True)
    (hooks/'hook-processed_finish_v32.py').write_text('module_collection_mode = '+repr({n:'py' for n in MODULES})+'\n',encoding='utf-8')
    (hooks/'hook-imageio_ffmpeg.py').write_text('datas = []\nbinaries = []\n',encoding='utf-8')
    resources={n+'.py':sha(root/(n+'.py')) for n in MODULES};resources['native/ffmpeg.exe']=sha(ff)
    manifest=dict(app_version='3.3.0-auto-exe',resources=resources,source_commit=os.environ.get('GITHUB_SHA','local'),versions={n:md.version(n) for n in PACKAGES},
        ffmpeg_version=version,native_recipe='packaging/build_codec.sh',signing='UNSIGNED',automatic_policy='GAIN_ONLY -> OPPO -> LIMITER_ONLY_AFTER_NOT_FEASIBLE')
    (work/'BUNDLE_MANIFEST.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    from PyInstaller.utils.hooks import copy_metadata
    datas=[(str(work/'BUNDLE_MANIFEST.json'),'.')]
    for name in PACKAGES:datas.extend(copy_metadata(name))
    spec=f'''# generated AUTO v3.3\na = Analysis([{str(root/'natural_exe_entry_v33.py')!r}], pathex=[{str(root)!r}],\n binaries=[({str(ff)!r}, 'native')], datas={datas!r},\n hiddenimports={list(MODULES)+['natural_exe_entry','natural_exe_entry_v33','_cffi_backend','imageio_ffmpeg','tkinter','tkinter.filedialog']!r},\n hookspath=[{str(hooks)!r}], excludes=['pytest','IPython','matplotlib','pandas','torch','scipy.tests','numpy.tests'], noarchive=False)\npyz=PYZ(a.pure)\nexe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PDRM_AUTO',console=True,debug=False,strip=False,upx=False,uac_admin=False)\ncoll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PDRM_AUTO')\n'''
    specpath=work/'PDRM_AUTO_v33.spec';specpath.write_text(spec,encoding='utf-8')
    subprocess.run([sys.executable,'-m','PyInstaller','--clean','--noconfirm','--distpath',str(root/'dist'),'--workpath',str(root/'build_pyinstaller_v33'),str(specpath)],check=True)
    dest=root/'dist'/'PDRM_AUTO';licenses=dest/'LICENSES';sources=dest/'SOURCES';licenses.mkdir(exist_ok=True);sources.mkdir(exist_ok=True)
    shutil.copytree(codec/'LICENSES',licenses/'native-codec',dirs_exist_ok=True);shutil.copytree(codec/'SOURCES',sources/'native-codec',dirs_exist_ok=True)
    (licenses/'FFMPEG_VERSION_AND_CONFIG.txt').write_text(version,encoding='utf-8')
    for name in (*PACKAGES,'pyinstaller','pyinstaller-hooks-contrib'):
        dist=md.distribution(name)
        for f in dist.files or []:
            low=str(f).lower()
            if any(w in low for w in ('license','copying','copyright','notice')):
                p=Path(dist.locate_file(f))
                if p.is_file() and p.suffix.lower() not in ('.pyc','.py','.pyd'):
                    target=licenses/name/Path(str(f).replace('..','__'));target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
    p=Path(sys.base_prefix)/'LICENSE.txt'
    if p.is_file():shutil.copy2(p,licenses/'python-LICENSE.txt')
    for p in (Path(sys.base_prefix)/'tcl').glob('*/license.terms'):shutil.copy2(p,licenses/('tcl-'+p.parent.name+'-license.txt'))
    import soundfile as sf
    libver=sf.__libsndfile_version__;get(f'https://github.com/libsndfile/libsndfile/releases/download/{libver}/libsndfile-{libver}.tar.xz',sources/f'libsndfile-{libver}.tar.xz')
    data=json.load(urllib.request.urlopen(f'https://pypi.org/pypi/soundfile/{md.version("soundfile")}/json',timeout=60))
    for item in data['urls']:
        if item['packagetype']=='sdist':
            target=sources/item['filename'];get(item['url'],target)
            if sha(target)!=item['digests']['sha256']:raise RuntimeError('SoundFile source checksum differs')
    with zipfile.ZipFile(sources/'PDRM_APPLICATION_SOURCE.zip','w',zipfile.ZIP_DEFLATED) as z:
        for name in MODULES+('natural_exe_entry','natural_exe_entry_v33','processed_exe_entry'):
            z.write(root/(name+'.py'),name+'.py')
        for p in (root/'packaging').rglob('*'):
            if p.is_file() and '__pycache__' not in str(p):z.write(p,p.relative_to(root))
        for p in (root/'tests').glob('test_*.py'):z.write(p,p.relative_to(root))
        z.write(root/'docs/AUTO_V33_GUIDE.md','AUTO_V33_GUIDE.md')
    (dest/'THIRD_PARTY_NOTICES.md').write_text('Third-party licenses and corresponding sources are retained in LICENSES and SOURCES.\n',encoding='utf-8')
    shutil.copy2(root/'docs/AUTO_V33_GUIDE.md',dest/'使い方.md')
    if (root/'SOURCE_TEST_RESULTS.json').exists():shutil.copy2(root/'SOURCE_TEST_RESULTS.json',dest/'SOURCE_TEST_RESULTS.json')
    manifest.update(python=sys.version,libsndfile=libver,pyinstaller=md.version('pyinstaller'))
    (dest/'BUILD_REPORT.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    exes=sorted(p.name for p in dest.rglob('*.exe'))
    if exes!=['PDRM_AUTO.exe','ffmpeg.exe']:raise RuntimeError('Unexpected executable: '+repr(exes))
    print(dest)
if __name__=='__main__':main()
