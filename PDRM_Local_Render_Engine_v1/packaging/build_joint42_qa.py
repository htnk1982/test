"""Build/run a synthetic QA-only Windows executable; do not publish the binary.

This verifies packaging of the new joint DSP path, not production GUI, automatic
musical analysis or neural inference. Audio fixtures are generated internally.
The standalone program accepts no user music and is not a replacement release.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import os,sys,json,subprocess,shutil,hashlib,importlib.metadata as metadata,platform
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'JOINT42_FROZEN_EVIDENCE'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def execute(command,log,cwd,env=None,timeout=600):
    with Path(log).open('w',encoding='utf-8') as f:
        result=subprocess.run(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if result.returncode:
        text=Path(log).read_text(encoding='utf-8',errors='replace')
        print(text[-16000:],flush=True)
        raise RuntimeError('QA process failed; see '+str(log))


def main():
    if sys.platform!='win32':raise RuntimeError('Windows build must run on Windows')
    OUT.mkdir(exist_ok=True)
    from PyInstaller.utils.hooks import copy_metadata
    import imageio_ffmpeg
    packages=('numpy','scipy','soundfile','pyloudnorm','psutil','imageio-ffmpeg','cffi','pycparser','pyinstaller','pyinstaller-hooks-contrib')
    versions={p:metadata.version(p) for p in packages}
    (OUT/'ENVIRONMENT_LOCK.txt').write_text('\n'.join(k+'=='+v for k,v in versions.items())+'\n',encoding='utf-8')
    source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    ffmpeg=Path(imageio_ffmpeg.get_ffmpeg_exe()).resolve()
    with TemporaryDirectory(prefix='pdrm42_build_') as builddir:
        build=Path(builddir);hooks=build/'hooks';hooks.mkdir()
        # This project verifies and fingerprints its actual .py source files.
        # Collect them unchanged, rather than disabling those runtime checks.
        root_py=sorted(ROOT.glob('*.py'))
        modes={p.stem:'py' for p in root_py};modes['decay39_fixtures']='py'
        (hooks/'hook-integrated_finish_v40.py').write_text('module_collection_mode = '+repr(modes)+'\n',encoding='utf-8')
        datas=[(str(p),'.') for p in root_py]
        datas.append((str(ROOT/'tests'/'decay39_fixtures.py'),'.'))
        for name in packages:datas.extend(copy_metadata(name))
        spec=f'''a = Analysis([{str(ROOT/'joint42_selftest.py')!r}],
 pathex={[str(ROOT),str(ROOT/'tests')]!r},
 binaries=[({str(ffmpeg)!r},'imageio_ffmpeg/binaries')],datas={datas!r},
 hiddenimports=['imageio_ffmpeg','decay39_fixtures','joint_lowend_v42','_cffi_backend'],
 hookspath={[str(hooks)]!r},
 excludes=['torch','torchaudio','tensorflow','pandas','matplotlib','IPython','pytest','tkinter'],noarchive=False)
pyz=PYZ(a.pure)
exe=EXE(pyz,a.scripts,[],exclude_binaries=True,name='PDRM_JOINT_QA',console=True,debug=False,strip=False,upx=False,uac_admin=False)
coll=COLLECT(exe,a.binaries,a.datas,strip=False,upx=False,name='PDRM_JOINT_QA')
'''
        specfile=build/'joint42.spec';specfile.write_text(spec,encoding='utf-8')
        shutil.copyfile(specfile,OUT/'BUILD_SPEC.txt')
        execute([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(build/'dist'),
            '--workpath',str(build/'work'),str(specfile)],OUT/'BUILD.log',ROOT,timeout=900)
        bundle=build/'dist'/'PDRM_JOINT_QA'
        if not (bundle/'PDRM_JOINT_QA.exe').is_file():raise RuntimeError('Build produced no EXE')
        # Copy away from the checkout/build root, including a Japanese/spaced path.
        isolated=build/'日本語 空白'/'bundle';isolated.parent.mkdir();shutil.copytree(bundle,isolated)
        cwd=build/'empty_working_directory';cwd.mkdir()
        env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME','IMAGEIO_FFMPEG_EXE'):env.pop(key,None)
        windows=Path(env.get('SystemRoot',r'C:\Windows'))
        env['PATH']=str(windows/'System32')+os.pathsep+str(windows)
        env['PYTHONUTF8']='1';env['OMP_NUM_THREADS']='1';env['OPENBLAS_NUM_THREADS']='1';env['MKL_NUM_THREADS']='1'
        # Absolute source Python for the baseline. Neither process can find a
        # system ffmpeg via PATH; both must use the identical packaged codec.
        source_output=OUT/'source';frozen_output=OUT/'frozen'
        execute([sys.executable,str(ROOT/'joint42_selftest.py'),'--self-test-output',str(source_output)],OUT/'SOURCE.log',cwd,env)
        exe=isolated/'PDRM_JOINT_QA.exe'
        execute([str(exe),'--self-test-output',str(frozen_output)],OUT/'FROZEN.log',cwd,env)
        a=json.loads((source_output/'SUMMARY.json').read_text(encoding='utf-8'))
        b=json.loads((frozen_output/'SUMMARY.json').read_text(encoding='utf-8'))
        assert a['success'] and b['success'] and not a['frozen'] and b['frozen']
        assert len(a['cases'])==len(b['cases'])==5
        matches=[]
        for aa,bb in zip(a['cases'],b['cases']):
            keys=('case','master_pcm_sha256','mp3_sha256','ffmpeg_sha256','prep_route','master_route','codec_routes')
            same={k:aa[k]==bb[k] for k in keys}
            matches.append(dict(case=aa['case'],matches=same))
            assert all(same.values()),matches[-1]
        report=dict(success=True,source_commit=source_commit,platform=platform.platform(),python=sys.version,
            versions=versions,exe_sha256=sha(exe),binary_size_bytes=exe.stat().st_size,
            bundle_size_bytes=sum(p.stat().st_size for p in isolated.rglob('*') if p.is_file()),
            source_vs_frozen=matches,actual_frozen_execution=True,isolated_from_checkout=True,
            japanese_and_space_path=True,path_contains_python_or_system_ffmpeg=False,
            host_python_uninstalled=False,os_network_blocked=False,neural_inference=False,
            production_gui=False,distribution_release=False,model_weights_bundled=False,
            scope='QA_EXE_SYNTHETIC_JOINT_PATH;_NOT_AUTOMATIC_MUSIC_OR_MODEL_PACKAGING')
        (OUT/'FROZEN_RESULTS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        rows='\n'.join(f"| {v['case']} | {all(v['matches'].values())} |" for v in matches)
        md=f'''# PDRM Joint42 — Windows実EXEの結合検査

日付: 2026-09-10。状態: QA専用EXEのビルド・実行確認。ユーザー向け完成版ではない。
検証commit: `{source_commit}`。

PyInstaller {versions['pyinstaller']}で、共同低域描画を既存HE/AUTO/HFTC/codecへ接続したQA用EXEを作成した。
ビルドしたEXEをcheckout外の日本語と空白を含むフォルダへコピーし、別の空ディレクトリから起動した。
PATHからPythonと外部FFmpegを外し、同梱したPythonランタイム・依存ライブラリ・FFmpegで実行した。
ホストPCからPythonをアンインストールした試験や、OSで通信を遮断した試験ではない。

同じWindows環境・同じcodecでPython版も実行し、下記の完成WAVの復号PCM hash、MP3全バイトhash、前段/最終/codecの処理経路を照合した。

| ケース | すべて一致 |
|---|---|
{rows}

狭帯域の尾部は合成音の既知イベント・明示された合成支持を使用する。実曲の自動成分認識、本人の好み適合、ステム分離モデルのWindows EXE推論の合格ではない。
HE/HFTC/OPPOの既存ソース照合は無効化せず、必要な元のPythonファイルをそのまま同梱して通した。

QAバイナリはこの試験のためだけに作成・実行し、ジョブ内で削除する。ユーザーへ新しいマスタリングアプリとして配布しない。
成果物には本Markdown、ビルド仕様、ライブラリ版、実行ログ、比較結果を保持する。モデル重み・個人音源は含まない。

一次資料: https://pyinstaller.org/en/stable/runtime-information.html 、https://pyinstaller.org/en/stable/hooks.html 。
外部資料はパッケージ方式と実行時のファイル位置の根拠であり、PDRMの音質成功を保証しない。
'''
        (OUT/'PDRM_Joint42_Windows実EXE検証_20260910.md').write_text(md,encoding='utf-8')
    shutil.copyfile(__file__,OUT/'build_joint42_qa.py')
    print('JOINT42_FROZEN_RESULT '+json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
