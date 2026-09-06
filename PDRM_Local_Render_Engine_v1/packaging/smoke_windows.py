"""Test the built EXE outside checkout with Python/FFmpeg absent from PATH."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import numpy as np
import soundfile as sf

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT))
import processed_finish as app
from target_settings import Targets


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    original = ROOT/'dist'/'PDRM_Processed'
    area = Path(tempfile.mkdtemp(prefix='PDRM_EXE_', dir=os.environ.get('RUNNER_TEMP')))
    bundle = area/'配布版 単体'/'PDRM_Processed'
    shutil.copytree(original, bundle)
    exe = bundle/'PDRM_Processed.exe'; ff = bundle/'_internal/native/ffmpeg.exe'
    env = os.environ.copy()
    for name in list(env):
        if name.upper().startswith(('PYTHON', 'VIRTUAL_ENV', 'CONDA')): env.pop(name, None)
    win = Path(os.environ.get('SystemRoot', 'C:/Windows'))
    env.update(PATH=str(win/'System32') + os.pathsep + str(win),
               LOCALAPPDATA=str(area/'ユーザー'), IMAGEIO_FFMPEG_EXE='NOT_AN_EXTERNAL_FFMPEG.exe')
    def run(args, expected=0):
        mode = [] if args and str(args[0]) in ('--bundle-check','--gui-check') else ['--headless']
        p = subprocess.run([str(exe), '--no-pause', '--no-open', *mode, *map(str,args)], cwd=area,
                           env=env, capture_output=True, timeout=600)
        (area/'last-exe-output.log').write_bytes(p.stdout + p.stderr)
        if p.returncode != expected:
            raise RuntimeError(f'EXE return {p.returncode}, expected {expected}: ' + (p.stdout+p.stderr).decode('utf-8','replace')[-5000:])
        return p
    checks = []
    infofile = area/'bundle-check.json'; run(['--bundle-check',infofile])
    info = json.loads(infofile.read_text(encoding='utf-8'))
    assert info['frozen'] is True
    assert Path(info['ffmpeg']).samefile(ff)
    checks.append('Frozen imports, metadata, source hashes, bundled FFmpeg and Tk window')
    gui_check = area/'gui-check.json'; run(['--gui-check',gui_check])
    gui = json.loads(gui_check.read_text(encoding='utf-8'))
    assert gui['status']=='PASS'
    checks.append('Actual Tk controls: 4 values, validation, confirm, saved settings, reset/cancel')
    app.io.ffmpeg_path = lambda: str(ff)
    fixtures = []
    for i, sr in enumerate((44100, 48000, 96000), 1):
        t = np.arange(sr*4, dtype=np.float64)/sr
        envnote = ((t % 1) > .06).astype(float) * np.minimum(1, (1-t%1)/.05)
        bass = .09*envnote*(np.sin(2*np.pi*82.406889*t)+.45*np.sin(4*np.pi*82.406889*t))
        kick = .12*np.exp(-35*(t%.5))*np.sin(2*np.pi*61*t)
        high = (.005+.035*(np.sin(2*np.pi*3*t)>.6))*np.sin(2*np.pi*11000*t)
        x = np.stack((bass+kick+high, .93*bass+kick-.75*high), axis=1)
        x[:sr//10] = 0; x[-sr//10:] = 0
        filename = f'{i:02d} - 検証 曲.v1.wav' if i!=2 else '02 - 検証 FLAC.v1.flac'
        input_dir = area/'曲'/f'ケース{i}'; input_dir.mkdir(parents=True)
        source = input_dir/filename
        sf.write(source,x,sr,subtype='PCM_24' if i==2 else 'FLOAT')
        refdir = area/'reference'/f'case{i}'; refdir.mkdir(parents=True)
        reference = refdir/filename; shutil.copy2(source,reference)
        fixtures.append((source,sha(source),reference))
    run([s for s,_,_ in fixtures]); checks.append('EXE default batch: Japanese paths, WAV/FLAC, 44.1/48/96 kHz')
    measured = []
    for source,before,reference in fixtures:
        r, refout = app.run_file(reference, area/'reference_work')
        out = source.parent/'processed'
        outputs = [out/(source.stem+ext) for ext in ('.wav','.mp3')]
        assert sha(source) == before
        assert {p.name for p in out.iterdir() if p.is_file()} == {p.name for p in outputs}
        receipt = json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
        for key,target,tol in (('master_metrics',-12,.03),('codec_metrics',-14,.10)):
            m=receipt[key]
            assert abs(m['lufs_i']-target)<=tol, m
            assert m['true_peak_max_dbtp_estimate']<=-2, m
        for p in outputs:
            ref = refout/p.name
            if p.suffix=='.wav':
                assert app.io.pcm_hash(p)==app.io.pcm_hash(ref), 'Source/EXE WAV PCM mismatch'
            else:
                assert sha(p)==sha(ref), 'Source/EXE MP3 mismatch'
        stamp={p.name:p.stat().st_mtime_ns for p in outputs}
        run([source])
        assert stamp=={p.name:p.stat().st_mtime_ns for p in outputs}, 'Idempotence changed output'
        measured.append(dict(input=source.name, wav=receipt['master_metrics'], mp3=receipt['codec_metrics'],
                             source_vs_exe='PCM and MP3 match', rerun='unchanged'))
    checks.append('Original preserved; same-name output; targets; source/EXE equivalence; rerun skip')
    custom = Targets(**gui['targets'])
    source = fixtures[1][0]
    args = [str(source), '--replace-managed']
    for key,value in custom.to_dict().items(): args.extend(['--'+key.replace('_','-'),str(value)])
    out=source.parent/'processed'
    old={p.name:sha(p) for p in out.iterdir() if p.is_file()}
    run(args)
    receipt=json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
    backup=Path(receipt['backup'])
    for name,digest in old.items():assert sha(backup/name)==digest
    for key,target,tp in (('master_metrics',custom.wav_lufs,custom.wav_tp),('codec_metrics',custom.mp3_lufs,custom.mp3_tp)):
        m=receipt[key];assert abs(m['lufs_i']-target)<=.03 and m['true_peak_max_dbtp_estimate']<=tp,m
    ref=fixtures[1][2]
    _,refout=app.run_file(ref,area/'reference_work',targets=custom,replace_managed=True)
    for ext in ('.wav','.mp3'):
        a,b=out/(source.stem+ext),refout/(ref.stem+ext)
        assert (app.io.pcm_hash(a)==app.io.pcm_hash(b)) if ext=='.wav' else (sha(a)==sha(b))
    run(args) # same custom targets now skip
    checks.append('GUI-derived custom 4 values reach EXE outputs; source equivalence; backup and rerun')
    # Independent MP3 can be louder than WAV; WAV stays at its own target.
    t=Targets(-18,-3,-14,-4)
    source=fixtures[2][0];args=[str(source),'--replace-managed']
    for key,value in t.to_dict().items():args.extend(['--'+key.replace('_','-'),str(value)])
    run(args)
    out=source.parent/'processed';receipt=json.loads(next((out/'.pdrm').glob('*.json')).read_text(encoding='utf-8'))
    assert abs(receipt['master_metrics']['lufs_i']+18)<=.03
    assert receipt['master_metrics']['true_peak_max_dbtp_estimate']<=-3
    assert abs(receipt['codec_metrics']['lufs_i']+14)<=.03
    assert receipt['codec_metrics']['true_peak_max_dbtp_estimate']<=-4
    checks.append('Independent louder-MP3 / stricter-TP targets; WAV target unaffected')

    source=fixtures[0][0]; output=source.parent/'processed'/(source.stem+'.wav')
    run([output],expected=1); checks.append('Processed input refused')
    mp3=output.with_suffix('.mp3'); mp3.write_bytes(b'USER_EDIT_KEEP')
    run([source],expected=1); assert mp3.read_bytes()==b'USER_EDIT_KEEP'
    checks.append('User-modified output refused, not overwritten')
    broken=area/'bad.wav'; broken.write_bytes(b'NOT_A_WAV')
    run([broken],expected=1); assert not (area/'processed').exists()
    checks.append('Wrong file header rejected')
    module=bundle/'_internal'/'note_sub_lab.py'; contents=module.read_bytes()
    module.write_bytes(contents+b'\n# simulated change\n')
    run(['--bundle-check', area/'bad-check.json'],expected=1)
    module.write_bytes(contents); checks.append('Bundled source tampering detected')
    report=dict(status='PASS',checks=checks,measurements=measured,bundle_check=info,gui_check=gui,
                windows=os.environ.get('ImageOS'),python_removed_from_path=True,
                note='Windows runner still has Python installed; execution PATH and PYTHONPATH do not expose it')
    (original/'EXE_SMOKE_RESULTS.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(dict(status='PASS',checks=checks),ensure_ascii=False,indent=2))


if __name__ == '__main__': main()
