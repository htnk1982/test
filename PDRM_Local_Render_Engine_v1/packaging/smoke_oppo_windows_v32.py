"""Smoke-test built OPPO v3.2 outside the build environment."""
from pathlib import Path
import json,os,shutil,subprocess,sys,tempfile
import numpy as np
import soundfile as sf
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import natural_finish_v32 as n
import processed_finish as pub
from target_settings import Targets
from test_offline_peak_lab import mixture

def sha(p):return pub.io.file_hash(p)
def tree_bytes(p):return sum(f.stat().st_size for f in Path(p).rglob('*') if f.is_file()) if Path(p).exists() else 0

def main():
    original=ROOT/'dist'/'PDRM_OPPO';area=Path(tempfile.mkdtemp(prefix='OPPO32_EXE_',dir=os.environ.get('RUNNER_TEMP')))
    bundle=area/'配布 単体'/'PDRM_OPPO';shutil.copytree(original,bundle);exe=bundle/'PDRM_OPPO.exe';ff=bundle/'_internal/native/ffmpeg.exe'
    env=os.environ.copy()
    for name in list(env):
        if name.upper().startswith(('PYTHON','VIRTUAL_ENV','CONDA')):env.pop(name,None)
    win=Path(os.environ.get('SystemRoot','C:/Windows'));local=area/'ユーザー'
    env.update(PATH=str(win/'System32')+os.pathsep+str(win),LOCALAPPDATA=str(local))
    checks=[];measurements=[]
    def run(args,expected=0):
        mode=[] if args and str(args[0]) in ('--bundle-check','--gui-check') else ['--headless']
        p=subprocess.run([str(exe),'--no-pause','--no-open',*mode,*map(str,args)],cwd=area,env=env,capture_output=True,timeout=900)
        (original/'last-smoke.log').write_bytes(p.stdout+p.stderr)
        if p.returncode!=expected:raise RuntimeError((p.stdout+p.stderr).decode('utf-8','replace')[-8000:])
        return p
    run(['--bundle-check',area/'bundle.json']);run(['--gui-check',area/'gui.json'])
    bundle_result=json.loads((area/'bundle.json').read_text(encoding='utf-8'));assert bundle_result['frozen'] and Path(bundle_result['ffmpeg']).samefile(ff)
    for name in ('offline_peak_context.py','offline_peak_stream_v32.py','workspace_cleanup.py','processed_finish_v32.py'):
        assert name in bundle_result['manifest']['resources']
    gui=json.loads((area/'gui.json').read_text(encoding='utf-8'));assert gui['status']=='PASS';checks.append('Bundle, v3.2 context modules, FFmpeg and Tk GUI')
    pub.io.ffmpeg_path=lambda:str(ff);fixtures=[]
    for i,sr in enumerate((44100,48000,96000)):
        d=area/'曲'/str(i);d.mkdir(parents=True);src=d/('試験.v1.flac' if i==1 else '試験.v1.wav');x=mixture(sr=sr)
        if i==1:
            t=np.arange(len(x))/sr;x+=.55*np.exp(-.5*((t-.63)/.00004)**2)[:,None]
        sf.write(src,x,sr,subtype='PCM_24' if i==1 else 'FLOAT');rd=area/'reference'/str(i);rd.mkdir(parents=True);ref=rd/src.name;shutil.copy2(src,ref);fixtures.append((src,sha(src),ref))
    target=Targets(-18,-2,-20,-3);args=[str(s) for s,_,_ in fixtures]
    for k,v in target.to_dict().items():args.extend(['--'+k.replace('_','-'),str(v)])
    run(args)
    work=local/'PDRM_Local_Render_Engine_v1'/'oppo_finish_v32'
    assert not list(work.rglob('*.wav')) and not list(work.rglob('*.mp3')),'Successful batch left large audio caches'
    assert tree_bytes(work)<5*1024*1024,'Successful cleanup left excessive workspace data'
    checks.append('Per-track successful cleanup leaves no cached WAV/MP3 in LOCALAPPDATA')
    for src,h,ref in fixtures:
        r,rout=pub.run_file(ref,area/'ref_work',targets=target,backend=n);out=src.parent/'processed';record=json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
        assert h==sha(src) and record['request']['engine_version']==n.VERSION
        for key,lufs,tp in (('master_metrics',-18,-2),('codec_metrics',-20,-3)):
            m=record[key];assert abs(m['lufs_i']-lufs)<=.03 and m['true_peak_max_dbtp_estimate']<=tp
        for ext in ('.wav','.mp3'):
            a,b=out/(src.stem+ext),rout/(ref.stem+ext);assert (pub.io.pcm_hash(a)==pub.io.pcm_hash(b)) if ext=='.wav' else (sha(a)==sha(b))
        measurements.append(dict(source=src.name,rate=sf.info(src).samplerate,master=record['master_metrics'],mp3=record['codec_metrics']))
    checks.append('44.1/48/96 kHz source/EXE equality and independent targets')
    run(args);checks.append('Published receipts permit idempotent rerun after caches were deleted')
    # Force a normal per-track processing failure and verify that only a compact diagnostic remains.
    bad=area/'bad'/'too_hot.wav';bad.parent.mkdir();t=np.arange(48000)/48000.;x=np.column_stack((.1*np.sin(2*np.pi*440*t),.1*np.sin(2*np.pi*443*t)));x[24000]=20;sf.write(bad,x,48000,subtype='FLOAT')
    run([bad,'--wav-lufs','-8','--wav-tp','-12','--mp3-lufs','-8','--mp3-tp','-12'],expected=1)
    assert not list(work.rglob('*.wav')) and not list(work.rglob('*.mp3')),'Failed track left audio cache'
    assert list((work/'diagnostics').glob('*.json')),'Failed track did not retain compact diagnostic'
    checks.append('Failed track deletes large intermediates and retains small diagnostic only')
    report=dict(status='PASS',checks=checks,measurements=measurements,bundle_check=bundle_result,gui_check=gui,
        windows=os.environ.get('ImageOS'),python_removed_from_path=True,caveat='Windows runner has Python installed but execution PATH does not expose it')
    (original/'EXE_SMOKE_RESULTS.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8');print(json.dumps(dict(status='PASS',checks=checks),ensure_ascii=False))
if __name__=='__main__':main()
