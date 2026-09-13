"""Generated-audio self-test for the frozen P08 product candidate.

The test proves that the product ships a valid precomputed calibration, installs
it without any reference path, reuses it on the second request, and honors the
current 0.5 dB target grid/defaults. No user/private/reference audio enters CI.
"""
from __future__ import annotations
from pathlib import Path
import json,sys,tempfile
import soundfile as sf

import accepted_calibration_cache_v53 as calcache
import p01_private_calibration_entry as p01core
import product_gui_runtime_v52 as request
import product_worker_v52 as worker
from integration_contract_v40 import file_hash
from target_settings import Targets

VERSION='product-selftest-0.5.0'


def _target_contract():
    defaults=Targets().validate();expected=dict(wav_lufs=-10.0,wav_tp=-0.5,mp3_lufs=-14.0,mp3_tp=-1.0)
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
        root=Path(td);inputs=root/'日本語 空白 入力';inputs.mkdir();work=root/'work';session=root/'session';cache_root=root/'calibration_cache';targets=_target_contract()

        # Validate shipped derived metadata before any worker process uses it.
        precomputed=calcache.read_precomputed()
        if precomputed.get('sha256')!=calcache.EXPECTED_CALIBRATION_SHA256:raise RuntimeError('Precomputed calibration identity mismatch')
        if calcache.load(root=cache_root) is not None:raise RuntimeError('Self-test cache unexpectedly pre-populated')

        source=inputs/'製品 自己試験.wav';sf.write(source,p01core._fixture_source(),48000,subtype='DOUBLE');source_sha=file_hash(source)
        manifest=request._body([source],None,targets,False,work,session,expected_reference_sha=calcache.EXPECTED_REFERENCE_ZIP_SHA256,cache_ready=True)
        manifest_path=root/'request.json';request.write_manifest(manifest_path,manifest)
        final=worker.run_manifest(manifest_path,runtime_override=worker.runtime_root(),cache_root_override=cache_root)
        if final.get('overall')!='COMPLETE' or len(final.get('completed',[]))!=1 or final.get('failures'):raise RuntimeError('Frozen precomputed-calibration product self-test failed')
        if (final.get('calibration_cache') or {}).get('state')!='PRECOMPUTED_INSTALLED':raise RuntimeError('Precomputed calibration was not installed')
        ident=final.get('planner_identity') or {};obs=ident.get('observer') or {}
        cached=calcache.load(root=cache_root)
        if cached is None or cached.get('sha256')!=calcache.EXPECTED_CALIBRATION_SHA256:raise RuntimeError('Installed calibration cannot be reloaded')

        source2=inputs/'製品 キャッシュ試験.wav';sf.write(source2,p01core._fixture_source(),48000,subtype='DOUBLE')
        session2=root/'session_cache_hit';m2=request._body([source2],None,targets,False,work,session2,expected_reference_sha=calcache.EXPECTED_REFERENCE_ZIP_SHA256,cache_ready=True)
        p2=root/'request_cache.json';request.write_manifest(p2,m2)
        final2=worker.run_manifest(p2,runtime_override=worker.runtime_root(),cache_root_override=cache_root)
        if final2.get('overall')!='COMPLETE' or (final2.get('calibration_cache') or {}).get('state')!='HIT':raise RuntimeError('Second request did not reuse precomputed calibration cache')

        output=inputs/'processed'/'製品 自己試験.wav';mp3=inputs/'processed'/'製品 自己試験.mp3'
        if not output.is_file() or not mp3.is_file():raise RuntimeError('Frozen product outputs missing')
        if file_hash(source)!=source_sha:raise RuntimeError('Frozen product self-test changed source')
        if ident.get('planner_id')!='automatic-joint-lab-0.4.0' or ident.get('calibration_sha256')!=calcache.EXPECTED_CALIBRATION_SHA256:raise RuntimeError('Frozen planner/calibration identity changed')
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
            planner_id=ident['planner_id'],calibration_sha256=ident.get('calibration_sha256'),p01_accepted_calibration_sha256=calcache.P01_ACCEPTED_CALIBRATION_SHA256,
            precomputed_calibration_valid=True,precomputed_install_state=final['calibration_cache']['state'],cache_second_request_state=final2['calibration_cache']['state'],reference_free_product_request=True,reference_audio_bundled=False,reference_audio_required=False,
            observer_provider=obs['provider'],observer_runtime_manifest_sha256=obs.get('runtime_manifest_sha256'),source_unchanged=True,stem_audio_in_master=False,runtime_model_download=False,
            target_contract=dict(lufs_step_db=.5,tp_step_db=.5,tp_max_dbtp=-.5,off_grid_lufs_rejected=True,off_grid_tp_rejected=True,tp_above_max_rejected=True,defaults=targets.to_dict()),
            targets=targets.to_dict(),master_metrics=mm,codec_metrics=cm,product_worker=worker.VERSION,product_runtime=request.VERSION,
            scope='generated-audio frozen distribution/precomputed-calibration/default-target-contract self-test; not listening acceptance')
        (dest/'P08_PRODUCT_SELFTEST.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');return summary
