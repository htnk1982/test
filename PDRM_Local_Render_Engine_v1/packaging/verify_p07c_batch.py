"""P07-C multi-track/resource acceptance. Synthetic audio only."""
from pathlib import Path
import sys,os,json,time,tempfile,subprocess,platform
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
OUT=ROOT/'P07C_EVIDENCE'

def size(root):
    total=0;root=Path(root)
    if not root.exists():return 0
    try:paths=list(root.rglob('*'))
    except OSError:return total
    for p in paths:
        try:
            if p.is_file() and not p.is_symlink():total+=p.stat().st_size
        except (FileNotFoundError,PermissionError,OSError):continue
    return total

def monitor(proc,work,timeout=600):
    import psutil
    peak_rss=0;peak_work=0;samples=0;deadline=time.monotonic()+timeout
    try:parent=psutil.Process(proc.pid)
    except psutil.NoSuchProcess:parent=None
    try:
        while proc.poll() is None:
            if time.monotonic()>deadline:raise TimeoutError('batch timeout')
            rss=0
            if parent is not None:
                try:
                    for child in [parent]+parent.children(recursive=True):
                        try:rss+=child.memory_info().rss
                        except (psutil.NoSuchProcess,psutil.AccessDenied):pass
                except (psutil.NoSuchProcess,psutil.AccessDenied):pass
            peak_rss=max(peak_rss,rss);peak_work=max(peak_work,size(work));samples+=1;time.sleep(.05)
        proc.wait(timeout=20)
        return dict(peak_rss_bytes=peak_rss,peak_work_bytes=peak_work,monitor_samples=samples,returncode=proc.returncode,final_work_bytes=size(work))
    except BaseException:
        if proc.poll() is None:
            proc.kill()
            try:proc.wait(timeout=20)
            except subprocess.TimeoutExpired:pass
        raise

def run_worker(manifest_path,work,log):
    env=dict(os.environ,PDRM_ENABLE_GUI_FIXTURE='1')
    with Path(log).open('w',encoding='utf-8') as f:
        proc=subprocess.Popen([sys.executable,str(ROOT/'gui_worker_entry_v44.py'),'--worker-manifest',str(manifest_path)],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT)
        return monitor(proc,work)

def main():
    import numpy as np,soundfile as sf
    import gui_runtime_v44 as gui
    from target_settings import Targets
    from decay39_fixtures import audio_fixture
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pdrm_p07c_') as td:
        root=Path(td);a=root/'アルバム A';b=root/'Album B';a.mkdir();b.mkdir();work=root/'work';sessions=root/'sessions';sessions.mkdir()
        _,bad48,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.);_,bad32,_=audio_fixture(32000,phase=.41,decay=.74,fault_db=6.)
        paths=[a/'01 同名.wav',a/'02 FLAC.flac',b/'01 同名.wav',b/'03 FLAC.flac',b/'99 失敗.wav']
        sf.write(paths[0],bad48,48000,subtype='DOUBLE');sf.write(paths[1],bad48,48000,format='FLAC',subtype='PCM_24');sf.write(paths[2],bad48,48000,subtype='DOUBLE');sf.write(paths[3],bad48,48000,format='FLAC',subtype='PCM_24');sf.write(paths[4],bad32,32000,subtype='DOUBLE')
        original={str(p):p.read_bytes() for p in paths}
        cw=a/'衝突.wav';cf=a/'衝突.flac';sf.write(cw,bad48,48000,subtype='DOUBLE');sf.write(cf,bad48,48000,format='FLAC',subtype='PCM_24')
        collision=False
        try:gui.make_manifest([cw,cf],Targets(),False,work,sessions/'collision',runtime_id='engineering_fixture_tail')
        except ValueError as exc:collision='output collision' in str(exc)
        assert collision and not (a/'processed'/'衝突.wav').exists();cw.unlink();cf.unlink()
        targets=Targets();session=sessions/'first';manifest=gui.make_manifest(paths,targets,False,work,session,runtime_id='engineering_fixture_tail');mf=root/'batch.json';gui.atomic_json(mf,manifest)
        first=run_worker(mf,work,OUT/('BATCH1_'+platform.system()+'.log'));status=gui.read_status(session,manifest['sha256'])
        assert first['returncode']==0 and status['overall']=='COMPLETE_WITH_ERRORS'
        assert len(status['completed'])==4 and len(status['failures'])==1 and status['failures'][0]['file']=='99 失敗.wav'
        for p in paths:assert p.read_bytes()==original[str(p)]
        for p in paths[:4]:
            folder=p.parent/'processed';assert (folder/(p.stem+'.wav')).is_file() and (folder/(p.stem+'.mp3')).is_file()
        assert not (b/'processed'/'99 失敗.wav').exists() and not (b/'processed'/'99 失敗.mp3').exists()
        assert not list(work.glob('.pdrm-owned-*')) and first['final_work_bytes']==0
        published=[p for folder in (a/'processed',b/'processed') for p in folder.iterdir() if p.is_file() and p.suffix.lower() in ('.wav','.mp3')]
        stamps={str(p):(p.stat().st_mtime_ns,p.read_bytes()) for p in published}
        session2=sessions/'second';m2=gui.make_manifest(paths,targets,False,work,session2,runtime_id='engineering_fixture_tail');mf2=root/'batch2.json';gui.atomic_json(mf2,m2)
        second=run_worker(mf2,work,OUT/('BATCH2_'+platform.system()+'.log'));s2=gui.read_status(session2,m2['sha256'])
        assert second['returncode']==0 and s2['overall']=='COMPLETE_WITH_ERRORS' and not list(work.glob('.pdrm-owned-*')) and second['final_work_bytes']==0
        for p,(stamp,data) in stamps.items():q=Path(p);assert q.stat().st_mtime_ns==stamp and q.read_bytes()==data
        report=dict(success=True,platform=platform.platform(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),collision_preflight=True,sources=5,successful=4,expected_failures=1,multiple_source_folders=2,wav_flac_mixed=True,same_stem_different_folders_allowed=True,first_run=first,second_run=second,completed_outputs_not_rewritten=True,original_sources_unchanged=True,owned_workspace_final_count=0,product_release=False,private_music=False,throughput_claim='NOT_A_SPEED_BENCHMARK',failure_policy='RECORD_ONE_FILE_AND_CONTINUE')
        (OUT/'SUMMARY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        md=f'''# PDRM P07-C — 多曲・多フォルダ・資源累積の実行記録\n\n日付: 2026-09-10。Issue #7。commit `{report['commit']}`。環境: {report['platform']}。\n\nWAV/FLAC混在5入力、2フォルダ、日本語/空白名を別workerで順次処理した。48kHz4曲はprocessedへWAV/MP3を作成し、意図的な32kHz非対応ケース1曲は失敗として記録した後もbatchを完走した。元入力は全バイト不変。\n\n同じstemのWAV/FLACが同じフォルダにある衝突はmanifest作成時に拒否し、DSP前に止めた。別フォルダの同一stemは許可。\n\n1回目のworker+子process最大RSSは{first['peak_rss_bytes']}bytes、work root観測最大は{first['peak_work_bytes']}bytes、終了時{first['final_work_bytes']}bytes。2回目終了時も{second['final_work_bytes']}bytes。50ms監視なので瞬間ピークの厳密上限ではない。監視中にworkerが削除したファイルは競合として無視し、監視器自身が失敗した場合もchildを必ず回収する。\n\n同設定で再実行し、4曲の既存WAV/MP3はmtimeと全バイトが不変。失敗曲は再試行されるが完成済み曲は再生成しない。10倍高速化は再開していない。\n'''
        (OUT/'PDRM_P07C_多曲資源回帰_20260910.md').write_text(md,encoding='utf-8');print('P07C '+json.dumps(report,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
