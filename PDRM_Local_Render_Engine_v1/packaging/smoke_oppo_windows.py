"""Built native EXE, custom targets, original preservation and explicit frontend mode."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,tempfile
import numpy as np
import soundfile as sf
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
import natural_finish as n
import processed_finish as pub
from target_settings import Targets
from test_offline_peak_lab import mixture

def sha(p):return pub.io.file_hash(p)

def main():
    original=ROOT/'dist'/'PDRM_OPPO';area=Path(tempfile.mkdtemp(prefix='OPPO_EXE_',dir=os.environ.get('RUNNER_TEMP')))
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
        if p.returncode!=expected:raise RuntimeError((p.stdout+p.stderr).decode('utf-8','replace')[-6000:])
    run(['--bundle-check',area/'bundle.json']);run(['--gui-check',area/'gui.json'])
    bundle_result=json.loads((area/'bundle.json').read_text(encoding='utf-8'))
    assert bundle_result['frozen'] and Path(bundle_result['ffmpeg']).samefile(ff)
    gui=json.loads((area/'gui.json').read_text(encoding='utf-8'));assert gui['status']=='PASS'
    checks.append('Frozen dependencies, source integrity, bundled FFmpeg and actual Tk controls')
    pub.io.ffmpeg_path=lambda:str(ff)
    fixtures=[]
    for i,sr in enumerate((44100,48000,96000)):
        d=area/'曲'/str(i);d.mkdir(parents=True);src=d/('試験.v1.flac' if i==1 else '試験.v1.wav')
        sf.write(src,mixture(sr=sr),sr,subtype='PCM_24' if i==1 else 'FLOAT')
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
    checks.append('44.1/48/96 kHz original WAV/FLAC, same-name outputs, custom targets, source/EXE equality')
    run(args);checks.append('Same input and settings: verified idempotence')
    src=fixtures[1][0];args=[str(src),'--replace-managed','--wav-lufs','-20','--wav-tp','-3','--mp3-lufs','-18','--mp3-tp','-2']
    run(args);out=src.parent/'processed';record=json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
    assert Path(record['backup']).exists() and abs(record['codec_metrics']['lufs_i']+18)<=.03
    checks.append('Changed four targets, louder MP3 branch, explicit backup replacement')
    # Same original, deliberately selected compatibility frontend; no silent mode switch.
    run([src,'--replace-managed','--preparation','legacy_peak','--wav-lufs','-18','--wav-tp','-2','--mp3-lufs','-20','--mp3-tp','-3'])
    record=json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
    assert 'legacy' in record['request']['engine_version']
    checks.append('Explicit compatibility frontend is a separate result identity')
    wav=out/(src.stem+'.wav');run([wav],expected=1)
    mp3=out/(src.stem+'.mp3');mp3.write_bytes(b'USER_EDIT')
    run([src,'--replace-managed'],expected=1);assert mp3.read_bytes()==b'USER_EDIT'
    checks.append('Reprocessing outputs and overwriting edited files refused')
    report=dict(status='PASS',checks=checks,measurements=measurements,bundle_check=bundle_result,gui_check=gui,
        windows=os.environ.get('ImageOS'),python_removed_from_path=True,
        caveat='Windows runner has Python installed but it is not exposed on execution PATH')
    (original/'EXE_SMOKE_RESULTS.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(dict(status='PASS',checks=checks),ensure_ascii=False))
if __name__=='__main__':main()
