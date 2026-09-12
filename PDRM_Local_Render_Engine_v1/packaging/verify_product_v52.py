"""P08-A acceptance: real isolated Spleeter through product worker and P07 publisher.

Only generated audio is used. This verifies wiring and invariants, not musical
quality. The private canonical reference and user tracks never enter CI.
"""
from __future__ import annotations
from pathlib import Path
import argparse,hashlib,json,subprocess,sys,tempfile,zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

import numpy as np
import soundfile as sf

import gui_runtime_v44 as gui44
import p01_private_calibration_entry as p01core
import p01_private_calibration_bootstrap as refadapt
import product_gui_runtime_v52 as request
import product_worker_v52 as worker
from integration_contract_v40 import file_hash
from target_settings import Targets

OUT=ROOT/'P08A_EVIDENCE'


def dump(name,value):
    OUT.mkdir(exist_ok=True)
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def make_reference(root):
    refs=root/'refs';refs.mkdir();mp3s=[]
    for i in range(24):
        wav=refs/f'ref{i:02d}.wav';wav44=refs/f'ref{i:02d}_44.wav';mp3=refs/f'ref{i:02d}.mp3'
        sf.write(wav,p01core._fixture_reference(phase=.071*i,level=.100+.0007*i),48000,subtype='DOUBLE')
        command=[refadapt._ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-y',
                 '-i',str(wav),'-ar','44100','-c:a','pcm_f32le',str(wav44)]
        r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
        if r.returncode:raise RuntimeError('fixture 44.1 kHz conversion failed: '+r.stdout[-2000:])
        p01core._encode_mp3(wav44,mp3);mp3s.append(mp3);wav.unlink();wav44.unlink()
    archive=root/'reference.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in mp3s:z.write(p,arcname='reference/'+p.name)
    return archive


def marker_records(folder):
    meta=folder/'.pdrm';out=[]
    for p in meta.glob('*.json'):
        if p.name.endswith('.integration.json'):continue
        value=json.loads(p.read_text(encoding='utf-8'))
        if value.get('status')=='COMPLETE':out.append(value)
    return out


def require(cond,label,payload):
    if cond:return
    dump('FAILED_'+label+'.json',payload)
    raise AssertionError(label)


def main(argv=None):
    ap=argparse.ArgumentParser();ap.add_argument('--runtime',type=Path,required=True);a=ap.parse_args(argv)
    runtime=a.runtime.resolve(strict=True);OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='p08a_product_') as td:
        root=Path(td);inputs=root/'日本語 入力';inputs.mkdir();work=root/'work';session=root/'session'
        archive=make_reference(root);ref_sha=file_hash(archive)
        x=p01core._fixture_source();sources=[];source_hashes={}
        for i,audio in enumerate((x,np.column_stack((x[:,1]*.97,x[:,0]*.97))),1):
            p=inputs/f'{i:02d} 製品候補.wav';sf.write(p,audio,48000,subtype='DOUBLE');sources.append(p);source_hashes[p.name]=file_hash(p)
        targets=Targets()
        manifest=request._body(sources,archive,targets,False,work,session,expected_reference_sha=ref_sha)
        manifest_path=root/'product_request.json';request.write_manifest(manifest_path,manifest)

        final=worker.run_manifest(
            manifest_path,runtime_override=runtime,expected_reference_sha=ref_sha,
            allow_fixture_reference=True)
        require(final.get('overall')=='COMPLETE' and len(final.get('completed',[]))==2 and not final.get('failures'),
                'BATCH_COMPLETE',dict(final=final))
        ident=final.get('planner_identity') or {}
        require(ident.get('planner_id')=='automatic-joint-lab-0.4.0','PLANNER_IDENTITY',ident)
        obs=ident.get('observer') or {}
        require(obs.get('provider')=='spleeter_runtime48' and obs.get('stem_audio_in_master') is False and
                obs.get('runtime_model_download') is False,'OBSERVER_IDENTITY',obs)

        for source in sources:
            require(file_hash(source)==source_hashes[source.name],'SOURCE_CHANGED',dict(source=source.name))
        processed=inputs/'processed'
        for source in sources:
            require((processed/(source.stem+'.wav')).is_file() and (processed/(source.stem+'.mp3')).is_file(),
                    'OUTPUT_PAIR',dict(source=source.name,files=[p.name for p in processed.glob('*')]))
        markers=marker_records(processed)
        require(len(markers)==2,'PUBLISH_MARKERS',dict(count=len(markers),markers=markers))
        metric_rows=[]
        for marker in markers:
            mm=marker['master_metrics'];cm=marker['codec_metrics'];req=marker['request']
            require(abs(mm['lufs_i']-targets.wav_lufs)<=.03 and mm['true_peak_max_dbtp_estimate']<=targets.wav_tp,
                    'MASTER_QC',mm)
            require(abs(cm['lufs_i']-targets.mp3_lufs)<=.03 and cm['true_peak_max_dbtp_estimate']<=targets.mp3_tp,
                    'CODEC_QC',cm)
            require(req['targets']==dict(wav_lufs=-12.0,wav_tp_ceiling=-2.0,mp3_lufs=-14.0,mp3_tp_ceiling=-2.0),
                    'TARGET_IDENTITY',req)
            metric_rows.append(dict(source=req['source_name'],master=mm,codec=cm,files=marker['files']))

        require(not list(work.glob('p08_reference_*')) and not list(work.glob('p08_observer_*')),
                'PRIVATE_TEMP_CLEANUP',dict(work=[str(p) for p in work.iterdir()]))
        render_root=work/'renders'
        require(not list(render_root.glob('.pdrm-owned-*')),'OWNED_WORK_CLEANUP',
                dict(left=[str(p) for p in render_root.glob('*')]))

        evidence=dict(
            task='P08-A',success=True,scope='generated-audio technical integration only; not listening acceptance',
            product_worker=worker.VERSION,product_runtime=request.VERSION,
            planner_id=ident['planner_id'],observer_provider=obs['provider'],
            render_backend='joint-v46',finalizer='auto-peak-v3.4.0',
            finalizer_policy='GAIN_ONLY -> OPPO -> LIMITER_IF_OPPO_NOT_FEASIBLE',
            targets=targets.to_dict(),batch_files=2,source_unchanged=True,
            private_audio=False,fixture_reference_sha256=ref_sha,canonical_reference_used=False,
            reference_decode_local_temp=True,stem_audio_in_master=False,runtime_model_download=False,
            metrics=metric_rows,completed=final['completed'],
        )
        dump('P08A_PRODUCT_INTEGRATION.json',evidence)
        print('P08A '+json.dumps(evidence,ensure_ascii=True),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
