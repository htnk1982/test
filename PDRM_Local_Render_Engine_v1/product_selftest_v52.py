"""Generated-audio self-test for the frozen P08 product candidate.

The test proves release properties for calibration caching and output targets:
1. single-pass calibration is SHA-identical to the accepted legacy double scan;
2. after one bootstrap, a second product request runs from the sealed calibration
   cache without any reference path;
3. LUFS and TP targets are accepted on a 0.5 dB grid, TP ceilings extend through
   -0.5 dBTP, and the current product defaults propagate through the frozen path.
No user/private audio enters this path.
"""
from __future__ import annotations
from pathlib import Path
import json,subprocess,sys,tempfile,zipfile

import soundfile as sf

import accepted_calibration_cache_v53 as calcache
import automatic_joint_v51 as planner51
import p01_private_calibration_entry as p01core
import p01_private_calibration_bootstrap as refadapt
import product_gui_runtime_v52 as request
import product_worker_v52 as worker
from integration_contract_v40 import file_hash
from target_settings import Targets

VERSION='product-selftest-0.4.0'


def _make_reference(root):
    refs=root/'refs';refs.mkdir();mp3s=[]
    for i in range(24):
        wav=refs/f'ref{i:02d}.wav';wav44=refs/f'ref{i:02d}_44.wav';mp3=refs/f'ref{i:02d}.mp3'
        sf.write(wav,p01core._fixture_reference(phase=.071*i,level=.100+.0007*i),48000,subtype='DOUBLE')
        command=[refadapt._ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(wav),'-ar','44100','-c:a','pcm_f32le',str(wav44)]
        r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
        if r.returncode:raise RuntimeError('self-test reference conversion failed: '+r.stdout[-2000:])
        p01core._encode_mp3(wav44,mp3);mp3s.append(mp3);wav.unlink();wav44.unlink()
    archive=root/'reference.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in mp3s:z.write(p,arcname='reference/'+p.name)
    return archive


def _quick_calibration_parity(root):
    refs=root/'parity_refs';refs.mkdir();specs=[]
    for i in range(4):
        p=refs/f'p{i}.wav';sf.write(p,p01core._fixture_reference(seconds=2.0,phase=.17*i,level=.105+.003*i),48000,subtype='DOUBLE')
        specs.append(dict(path=p,role='bass',quality='positive'))
    legacy=planner51.make_calibration(specs);fast=calcache.build_calibration(specs)
    if legacy['sha256']!=fast['sha256'] or legacy!=fast:
        raise RuntimeError('Single-pass calibration is not bit-identical to legacy calibration')
    return legacy['sha256']


def _target_contract():
    defaults=Targets().validate()
    expected=dict(wav_lufs=-10.0,wav_tp=-0.5,mp3_lufs=-14.0,mp3_tp=-1.0)
    if defaults.to_dict()!=expected:raise RuntimeError('Product target defaults changed unexpectedly')
    Targets(wav_lufs=-12.5,wav_tp=-0.5,mp3_lufs=-14.5,mp3_tp=-1.0).validate()
    for bad in (
        dict(wav_lufs=-12.25,wav_tp=-0.5,mp3_lufs=-14.5,mp3_tp=-1.0),
        dict(wav_lufs=-12.5,wav_tp=-0.75,mp3_lufs=-14.5,mp3_tp=-1.0),
        dict(wav_lufs=-12.5,wav_tp=-0.4,mp3_lufs=-14.5,mp3_tp=-1.0),
    ):
        try:Targets(**bad).validate()
        except ValueError:pass
        else:raise RuntimeError('Invalid target contract value was not rejected: '+str(bad))
    return defaults


def self_test(destination):
    dest=Path(destination).resolve();dest.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='p08_frozen_selftest_') as td:
        root=Path(td);inputs=root/'日本語 空白 入力';inputs.mkdir();work=root/'work';session=root/'session';cache_root=root/'calibration_cache'
        parity_sha=_quick_calibration_parity(root);targets=_target_contract()
        archive=_make_reference(root);ref_sha=file_hash(archive)
        source=inputs/'製品 自己試験.wav';sf.write(source,p01core._fixture_source(),48000,subtype='DOUBLE');source_sha=file_hash(source)
        manifest=request._body([source],archive,targets,False,work,session,expected_reference_sha=ref_sha)
        manifest_path=root/'request.json';request.write_manifest(manifest_path,manifest)
        final=worker.run_manifest(manifest_path,runtime_override=worker.runtime_root(),expected_reference_sha=ref_sha,allow_fixture_reference=True,cache_root_override=cache_root)
        if final.get('overall')!='COMPLETE' or len(final.get('completed',[]))!=1 or final.get('failures'):raise RuntimeError('Frozen product self-test batch failed')
        if (final.get('calibration_cache') or {}).get('state')!='BUILT_AND_SAVED':raise RuntimeError('One-time calibration cache was not built')
        ident=final.get('planner_identity') or {};obs=ident.get('observer') or {}
        cached=calcache.load(ref_sha,expected_calibration_sha=ident.get('calibration_sha256'),root=cache_root)
        if cached is None:raise RuntimeError('Saved calibration cache cannot be reloaded')

        source2=inputs/'製品 キャッシュ試験.wav';sf.write(source2,p01core._fixture_source(),48000,subtype='DOUBLE')
        session2=root/'session_cache_hit';m2=request._body([source2],None,targets,False,work,session2,expected_reference_sha=ref_sha,cache_ready=True)
        p2=root/'request_cache.json';request.write_manifest(p2,m2)
        final2=worker.run_manifest(p2,runtime_override=worker.runtime_root(),expected_reference_sha=ref_sha,allow_fixture_reference=True,cache_root_override=cache_root)
        if final2.get('overall')!='COMPLETE' or (final2.get('calibration_cache') or {}).get('state')!='HIT':raise RuntimeError('Reference-free cache-hit product path failed')

        output=inputs/'processed'/'製品 自己試験.wav';mp3=inputs/'processed'/'製品 自己試験.mp3'
        if not output.is_file() or not mp3.is_file():raise RuntimeError('Frozen product outputs missing')
        if file_hash(source)!=source_sha:raise RuntimeError('Frozen product self-test changed source')
        if ident.get('planner_id')!='automatic-joint-lab-0.4.0':raise RuntimeError('Frozen planner identity changed')
        if obs.get('provider')!='spleeter_runtime48' or obs.get('stem_audio_in_master') is not False:raise RuntimeError('Frozen observer identity changed')
        marker=[p for p in (inputs/'processed'/'.pdrm').glob('*.json') if not p.name.endswith('.integration.json')]
        if len(marker)!=2:raise RuntimeError('Frozen publication markers missing')
        first=[p for p in marker if json.loads(p.read_text(encoding='utf-8'))['request']['source_name']==source.name]
        if len(first)!=1:raise RuntimeError('First publication marker not found')
        receipt=json.loads(first[0].read_text(encoding='utf-8'));mm=receipt['master_metrics'];cm=receipt['codec_metrics']
        if abs(mm['lufs_i']-targets.wav_lufs)>.03 or mm['true_peak_max_dbtp_estimate']>targets.wav_tp:raise RuntimeError('Frozen WAV target failed')
        if abs(cm['lufs_i']-targets.mp3_lufs)>.03 or cm['true_peak_max_dbtp_estimate']>targets.mp3_tp:raise RuntimeError('Frozen MP3 target failed')
        summary=dict(
            success=True,version=VERSION,frozen=bool(getattr(sys,'frozen',False)),executable=str(Path(sys.executable).resolve()),
            planner_id=ident['planner_id'],calibration_sha256=ident.get('calibration_sha256'),observer_provider=obs['provider'],
            observer_runtime_manifest_sha256=obs.get('runtime_manifest_sha256'),source_unchanged=True,stem_audio_in_master=False,runtime_model_download=False,
            canonical_reference_used=False,fixture_reference_sha256=ref_sha,calibration_single_pass_parity=True,parity_calibration_sha256=parity_sha,
            cache_bootstrap_state=final['calibration_cache']['state'],cache_second_request_state=final2['calibration_cache']['state'],reference_free_second_request=True,
            target_contract=dict(lufs_step_db=.5,tp_step_db=.5,tp_max_dbtp=-.5,off_grid_lufs_rejected=True,off_grid_tp_rejected=True,tp_above_max_rejected=True,defaults=targets.to_dict()),
            targets=targets.to_dict(),master_metrics=mm,codec_metrics=cm,product_worker=worker.VERSION,product_runtime=request.VERSION,
            scope='generated-audio frozen distribution/cache/default-target-contract self-test; not listening acceptance')
        (dest/'P08_PRODUCT_SELFTEST.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');return summary
