"""Smoke-test the built OPPO v3.1 EXE outside the build environment."""
from pathlib import Path
import json,os,shutil,subprocess,sys,tempfile
import numpy as np
import soundfile as sf
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import natural_finish_v31 as n
import processed_finish as pub
from target_settings import Targets
from test_offline_peak_lab import mixture

def sha(p):return pub.io.file_hash(p)

def main():
    original=ROOT/'dist'/'PDRM_OPPO';area=Path(tempfile.mkdtemp(prefix='OPPO31_EXE_',dir=os.environ.get('RUNNER_TEMP')))
    bundle=area/'配布 単体'/'PDRM_OPPO';shutil.copytree(original,bundle)
    exe=bundle/'PDRM_OPPO.exe';ff=bundle/'_internal/native/ffmpeg.exe'
    env=os.environ.copy()
    for name in list(env):
        if name.upper().startswith(('PYTHON','VIRTUAL_ENV','CONDA')):env.pop(name,None)
    win=Path(os.environ.get('SystemRoot','C:/Windows'))
    env.update(PATH=str(win/'System32')+os.pathsep+str(win),LOCALAPPDATA=str(area/'ユーザー'))
    checks=[];measurements=[]
    def run(args,expected=0):
        mode=[] if args and str(args[0]) in ('--bundle-check','--gui-check') else ['--headless']
        p=subprocess.run([str(exe),'--no-pause','--no-open',*mode,*map(str,args)],cwd=area,env=env,
            capture_output=True,timeout=900)
        (original/'last-smoke.log').write_bytes(p.stdout+p.stderr)
        if p.returncode!=expected:raise RuntimeError((p.stdout+p.stderr).decode('utf-8','replace')[-7000:])
        return p
    run(['--bundle-check',area/'bundle.json']);run(['--gui-check',area/'gui.json'])
    bundle_result=json.loads((area/'bundle.json').read_text(encoding='utf-8'))
    assert bundle_result['frozen'] and Path(bundle_result['ffmpeg']).samefile(ff)
    assert 'offline_peak_rescue.py' in bundle_result['manifest']['resources']
    gui=json.loads((area/'gui.json').read_text(encoding='utf-8'));assert gui['status']=='PASS'
    checks.append('Bundle integrity, rescue module, bundled FFmpeg and actual Tk controls')
    pub.io.ffmpeg_path=lambda:str(ff)
    fixtures=[]
    for i,sr in enumerate((44100,48000,96000)):
        d=area/'曲'/str(i);d.mkdir(parents=True);src=d/('試験.v1.flac' if i==1 else '試験.v1.wav')
        x=mixture(sr=sr)
        # Add a very narrow legal float transient to exercise high-crest input.
        if i==1:
            t=np.arange(len(x))/sr;x+=.45*np.exp(-.5*((t-.63)/.00008)**2)[:,None]
        sf.write(src,x,sr,subtype='PCM_24' if i==1 else 'FLOAT')
        rd=area/'reference'/str(i);rd.mkdir(parents=True);ref=rd/src.name;shutil.copy2(src,ref)
        fixtures.append((src,sha(src),ref))
    target=Targets(-18,-2,-20,-3)
    args=[str(s) for s,_,_ in fixtures]
    for k,v in target.to_dict().items():args.extend(['--'+k.replace('_','-'),str(v)])
    run(args)
    for src,h,ref in fixtures:
        r,rout=pub.run_file(ref,area/'ref_work',targets=target,backend=n)
        out=src.parent/'processed';record=json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
        assert h==sha(src) and record['request']['engine_version']==n.VERSION
        for key,lufs,tp in (('master_metrics',-18,-2),('codec_metrics',-20,-3)):
            m=record[key];assert abs(m['lufs_i']-lufs)<=.03 and m['true_peak_max_dbtp_estimate']<=tp
        for ext in ('.wav','.mp3'):
            a,b=out/(src.stem+ext),rout/(ref.stem+ext)
            assert (pub.io.pcm_hash(a)==pub.io.pcm_hash(b)) if ext=='.wav' else (sha(a)==sha(b))
        measurements.append(dict(source=src.name,rate=sf.info(src).samplerate,master=record['master_metrics'],mp3=record['codec_metrics']))
    checks.append('44.1/48/96 kHz source/EXE equality and independent targets')
    run(args);checks.append('Same input/settings verified idempotence')
    src=fixtures[1][0]
    run([src,'--replace-managed','--preparation','legacy_peak','--wav-lufs','-18','--wav-tp','-2','--mp3-lufs','-20','--mp3-tp','-3'])
    record=json.loads(next(((src.parent/'processed')/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
    assert 'legacy' in record['request']['engine_version'];checks.append('Explicit compatibility frontend remains separate')
    report=dict(status='PASS',checks=checks,measurements=measurements,bundle_check=bundle_result,gui_check=gui,
        windows=os.environ.get('ImageOS'),python_removed_from_path=True,
        caveat='Windows runner has Python installed but execution PATH does not expose it')
    (original/'EXE_SMOKE_RESULTS.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(dict(status='PASS',checks=checks),ensure_ascii=False))
if __name__=='__main__':main()
