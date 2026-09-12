"""Generated-audio self-test for the frozen P08 product candidate.

This path never accepts user audio. It creates its own reference fixture and one
source, then runs the same v51 worker/publication stack against the sibling
observer runtime. Its alternate reference hash exists only inside this function;
the normal GUI/--worker-manifest path remains pinned to the canonical archive.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json,subprocess,sys,tempfile,zipfile

import soundfile as sf

import p01_private_calibration_entry as p01core
import p01_private_calibration_bootstrap as refadapt
import product_gui_runtime_v52 as request
import product_worker_v52 as worker
from integration_contract_v40 import file_hash
from target_settings import Targets

VERSION='product-selftest-0.1.0'


def _make_reference(root):
    refs=root/'refs';refs.mkdir();mp3s=[]
    for i in range(24):
        wav=refs/f'ref{i:02d}.wav';wav44=refs/f'ref{i:02d}_44.wav';mp3=refs/f'ref{i:02d}.mp3'
        sf.write(wav,p01core._fixture_reference(phase=.071*i,level=.100+.0007*i),48000,subtype='DOUBLE')
        command=[refadapt._ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-y',
                 '-i',str(wav),'-ar','44100','-c:a','pcm_f32le',str(wav44)]
        r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
        if r.returncode:raise RuntimeError('self-test reference conversion failed: '+r.stdout[-2000:])
        p01core._encode_mp3(wav44,mp3);mp3s.append(mp3);wav.unlink();wav44.unlink()
    archive=root/'reference.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in mp3s:z.write(p,arcname='reference/'+p.name)
    return archive


def self_test(destination):
    dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='p08_frozen_selftest_') as td:
        root=Path(td);inputs=root/'日本語 空白 入力';inputs.mkdir();work=root/'work';session=root/'session'
        archive=_make_reference(root);ref_sha=file_hash(archive)
        source=inputs/'製品 自己試験.wav';sf.write(source,p01core._fixture_source(),48000,subtype='DOUBLE')
        source_sha=file_hash(source)
        manifest=request._body([source],archive,Targets(),False,work,session,expected_reference_sha=ref_sha)
        manifest_path=root/'request.json';request.write_manifest(manifest_path,manifest)
        final=worker.run_manifest(
            manifest_path,runtime_override=worker.runtime_root(),expected_reference_sha=ref_sha,
            allow_fixture_reference=True)
        if final.get('overall')!='COMPLETE' or len(final.get('completed',[]))!=1 or final.get('failures'):
            raise RuntimeError('Frozen product self-test batch failed')
        ident=final.get('planner_identity') or {};obs=ident.get('observer') or {}
        output=inputs/'processed'/'製品 自己試験.wav';mp3=inputs/'processed'/'製品 自己試験.mp3'
        if not output.is_file() or not mp3.is_file():raise RuntimeError('Frozen product outputs missing')
        if file_hash(source)!=source_sha:raise RuntimeError('Frozen product self-test changed source')
        if ident.get('planner_id')!='automatic-joint-lab-0.4.0':raise RuntimeError('Frozen planner identity changed')
        if obs.get('provider')!='spleeter_runtime48' or obs.get('stem_audio_in_master') is not False:
            raise RuntimeError('Frozen observer identity changed')
        marker=[p for p in (inputs/'processed'/'.pdrm').glob('*.json') if not p.name.endswith('.integration.json')]
        if len(marker)!=1:raise RuntimeError('Frozen publication marker missing')
        receipt=json.loads(marker[0].read_text(encoding='utf-8'));mm=receipt['master_metrics'];cm=receipt['codec_metrics']
        if abs(mm['lufs_i']+12)>.03 or mm['true_peak_max_dbtp_estimate']>-2:raise RuntimeError('Frozen WAV target failed')
        if abs(cm['lufs_i']+14)>.03 or cm['true_peak_max_dbtp_estimate']>-2:raise RuntimeError('Frozen MP3 target failed')
        summary=dict(
            success=True,version=VERSION,frozen=bool(getattr(sys,'frozen',False)),
            executable=str(Path(sys.executable).resolve()),planner_id=ident['planner_id'],
            observer_provider=obs['provider'],observer_runtime_manifest_sha256=obs.get('runtime_manifest_sha256'),
            source_unchanged=True,stem_audio_in_master=False,runtime_model_download=False,
            canonical_reference_used=False,fixture_reference_sha256=ref_sha,
            targets=Targets().to_dict(),master_metrics=mm,codec_metrics=cm,
            product_worker=worker.VERSION,product_runtime=request.VERSION,
            scope='generated-audio frozen distribution self-test; not listening acceptance',
        )
        (dest/'P08_PRODUCT_SELFTEST.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        return summary
