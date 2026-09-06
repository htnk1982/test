"""Whole-track OPPO chain, gain-only preparation, four independent output targets.

Default gain-only mode calls no conventional limiter. Compatibility frontend
is available only through an explicit, separately identified preparation choice. The accepted spectral
weights/solver and the Note-Sub/HFTC rules stay frozen. Current v2.2 is retained
as a separate legacy entry, not an automatic fallback for failed new results.
"""
from __future__ import annotations
import importlib.metadata
from dataclasses import asdict
from pathlib import Path
import os
import shutil
import threading
import traceback
import numpy as np
import soundfile as sf
import distribution_finish as common
import note_sub_conditioned as conditioned
import offline_peak_stream as oppo
import offline_peak_lab as kernel
import hf_temporal_contrast_lab as hf
from target_settings import Targets

io=common.io
legacy=common.legacy
VERSION='natural-finish-3.0.0'
FILES=('MASTER.wav','ENCODE_INPUT.wav','LISTEN_320kbps.mp3')
IDENTITY_MODULES=('natural_finish.py','offline_peak_stream.py','offline_peak_lab.py',
    'note_sub_conditioned.py','distribution_finish.py','distribution_peak.py','accepted_finish.py',
    'note_sub_lab.py','note_sub_lab_v02.py','hf_temporal_contrast_lab.py','target_settings.py')
_LOCK=threading.RLock()


def verify_final(final, ident):
    expected=set(FILES if ident['mp3'] else FILES[:1])|{'RUN_REPORT.json','完了.md'}
    try: saved=io.read_json(final/'PROOF.json')
    except (OSError,ValueError):raise RuntimeError('Missing result proof; nothing overwritten') from None
    if saved.get('identity')!=ident or set(saved.get('files',{}))!=expected:
        raise RuntimeError('Result identity differs; nothing overwritten')
    for name,h in saved['files'].items():
        p=final/name
        if not p.is_file() or p.is_symlink() or io.file_hash(p)!=h:
            raise RuntimeError('Output modified; nothing overwritten: '+name)
    return io.read_json(final/'RUN_REPORT.json')


def register(root, report):
    for h in report['output_pcm_sha256'].values():
        io.atomic_json(root/'.pdrm_processed_v2'/(h+'.json'),dict(version=VERSION,pcm_sha256=h))


def codec_branch(master, listen, mp3, job, targets, ff, progress):
    """From delivered WAV; peak changes, when required, use OPPO only."""
    original=io.file_hash(master);info=sf.info(master)
    pcm=oppo.measure(master,progress,'CODEC_MASTER')
    target,ceiling=targets.mp3_lufs,targets.mp3_tp
    trials=[]
    for attempt in range(6):
        # Every pass reads the same delivered WAV, not the previous candidate.
        branch=job/f'CODEC_PASS_{attempt}.wav'
        report=oppo.fit(master,branch,job/'codec_work',target,ceiling,progress=progress)
        common.write_pcm24(branch,listen)
        rate=info.samplerate if info.samplerate<=48000 else 48000
        common.peak.execute(ff,['-i',str(listen),'-map','0:a:0','-map_metadata','-1',
            '-ar',str(rate),'-c:a','libmp3lame','-b:a','320k',str(mp3)],
            job/'encode.log',progress,'OPPO_ENCODE_MP3')
        decoded=job/'MP3_DECODED.wav'
        common.peak.execute(ff,['-i',str(mp3),'-map_metadata','-1','-c:a','pcm_f32le',str(decoded)],
            job/'decode.log',progress,'OPPO_DECODE_MP3')
        m=oppo.measure(decoded,progress,'OPPO_MP3_QC')
        shape=(m['samplerate']==rate and m['channels']==info.channels and
            abs(m['frames']-round(info.frames*rate/info.samplerate))<=(0 if rate==info.samplerate else 1))
        if m['lufs_i'] is None or not shape:raise RuntimeError('MP3 decoded shape/loudness invalid')
        error=targets.mp3_lufs-m['lufs_i'];excess=m['true_peak_max_dbtp_estimate']-targets.mp3_tp
        trials.append(dict(pass_index=attempt,encoder_lufs=target,encoder_tp=ceiling,
                           waveform_report=report,decoded_metrics=m))
        if abs(error)<=.03 and excess<=0:
            if io.file_hash(master)!=original:raise RuntimeError('MP3 altered delivered WAV')
            return m,dict(trials=trials,conventional_limiter_used=False,
                optimizer_used=any(v['waveform_report']['optimizer_used'] for v in trials),master_sha256=original)
        target+=error
        if excess>0:ceiling-=excess+max(0.,error)+.05
        if not -30<=target<=-8 or not -12<=ceiling<=-1:
            raise kernel.NotFeasible('MP3 target outside the finite adjustment budget')
    raise kernel.NotFeasible('MP3 target not reached; no limiter fallback')


def _run_file(source, root, *, targets=None, write_mp3=True, interrupt_after=None, preparation='gain_only'):
    if preparation not in ('gain_only','legacy_peak'):raise ValueError('Unknown frontend mode')
    targets=(targets or Targets()).validate()
    source,root=Path(source).resolve(strict=True),Path(root).resolve()
    common.validate_paths(source,root)
    info=oppo.validate_source(source,kernel.Config())
    if source.suffix.lower() not in ('.wav','.flac'):raise ValueError('Original WAV/FLAC required')
    h=io.file_hash(source);pcm_hash=io.pcm_hash(source)
    if h in legacy.KNOWN_PROCESSED_FILES or (root/'.pdrm_processed_v2'/(pcm_hash+'.json')).exists():
        raise ValueError('Already-processed audio; use the original source')
    ff=io.ffmpeg_path() if write_mp3 or preparation=='legacy_peak' else None
    if (write_mp3 or preparation=='legacy_peak') and not ff:raise RuntimeError('Bundled FFmpeg is missing')
    ident=dict(version=VERSION,source_sha256=h,source_pcm_sha256=pcm_hash,
        code={n:io.file_hash(Path(__file__).with_name(n)) for n in IDENTITY_MODULES},
        frozen_dsp=legacy.verify_dsp(),kernel=oppo.verify_kernel(),targets=targets.to_dict(),
        config=asdict(kernel.Config()),preparation=preparation,mp3=write_mp3,ffmpeg_sha256=io.file_hash(ff) if ff else None,
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    key=io.obj_hash(ident)[:20];job=root/'.oppo_work_v3'/key
    final=root/(common.safe_name(source.stem)+'__OPPO_'+key[:12])
    job.mkdir(parents=True,exist_ok=True)
    with io.job_lock(job/'job.lock'),io.Progress(job) as progress:
        if final.exists():
            report=verify_final(final,ident);register(root,report)
            return dict(report,rerun_status='IDEMPOTENT_SKIP'),final
        try:
            # Estimate disk, not RAM: doubles plus committed/rejected candidates.
            free=shutil.disk_usage(root).free
            if free<info.frames*2*8*6+64*1024**2:
                raise OSError('Insufficient working disk space for safe offline checkpoints')
            io.atomic_json(job/'identity.json',ident)
            baseline=oppo.measure(source,progress,'BASELINE')
            if baseline['lufs_i'] is None:raise ValueError('Silent input cannot reach a finite LUFS target')
            he=job/'HARMONIC.wav'
            common.render_harmonic(source,he,progress)
            if preparation=='gain_only':
                note,ns_report=conditioned.run(he,job/'conditioned',progress,
                    interrupt_after='analysis' if interrupt_after=='analysis' else None)
            else:
                # This is an explicit compatibility choice, never a fallback
                # following failure of the gain-only mode.
                (job/'legacy_input').mkdir(exist_ok=True)
                prep=job/'legacy_input'/'PREPARED.wav'
                pr=common.peak.fit(he,prep,job/'legacy_peak',-14.,-2.5,ff,progress)
                nr,folder=common.ns.run_job(prep,job/'legacy_note',write_mp3=False,
                                           expected_hash=io.file_hash(prep))
                note=folder/'SUB_AUGMENTED.wav'
                ns_report=dict(nr,physical_target_lufs=-14.,analysis_anchor_lufs=-14.,
                    prep_limiter_used=pr['limiter_engaged'],prepared_metrics=pr['output_metrics'],
                    peak_preparation=pr)

            if interrupt_after=='note':raise InterruptedError('TEST_NATURAL_AFTER_NOTE')
            # HFTC observations use the same analysis anchor; the resulting
            # common stereo control curve is applied at the safe physical level.
            nm=oppo.measure(note,progress,'HF_INPUT')
            hf_anchor=(oppo.scaled_file(note,job/'HF_ANALYSIS.wav',-14-nm['lufs_i'],progress)
                       if preparation=='gain_only' else note)
            cfg=hf.Config()
            hf_identity=dict(source=io.file_hash(note),anchor=io.file_hash(hf_anchor),
                             config=asdict(cfg),code=io.file_hash(hf.__file__))
            hf_marker=job/'HF_READY.json'
            saved_hf=io.read_json(hf_marker) if hf_marker.exists() else None
            if (saved_hf and saved_hf.get('identity')==hf_identity and
                Path(saved_hf['raw']).is_file() and io.file_hash(saved_hf['raw'])==saved_hf['sha256']):
                raw=Path(saved_hf['raw']);stats=saved_hf['stats'];cache=saved_hf['cache']
            else:
                times,gains,stats=hf.analyze_control(hf_anchor,cfg,progress)
                raw,cache=hf.render_raw(note,job/'hf',times,gains,cfg,progress)
                io.atomic_json(hf_marker,dict(identity=hf_identity,raw=str(raw),
                    sha256=io.file_hash(raw),stats=stats,cache=cache))
            if interrupt_after=='hf':raise InterruptedError('TEST_NATURAL_AFTER_HF')
            master_float=job/'OPPO_MASTER_FLOAT.wav'
            master_report=oppo.fit(raw,master_float,job/'master',targets.wav_lufs,targets.wav_tp,
                progress=progress,interrupt_after=1 if interrupt_after=='oppo_chunk' else None)
            if interrupt_after=='master':raise InterruptedError('TEST_NATURAL_AFTER_MASTER')
            staged=job/'publish_staging'
            if staged.exists():shutil.rmtree(staged)
            staged.mkdir()
            master=staged/FILES[0]
            stable_master=job/'MASTER_PCM24.wav';pcm_marker=job/'MASTER_PCM24.json'
            pcm_identity=dict(source=io.file_hash(master_float),quantizer=io.file_hash(common.__file__))
            if not (io.valid_audio_cache(stable_master,pcm_marker) and
                    io.read_json(pcm_marker).get('identity')==pcm_identity):
                common.write_pcm24(master_float,stable_master)
                io.atomic_json(pcm_marker,dict(identity=pcm_identity,sha256=io.file_hash(stable_master)))
            # Keep the exact header and PCM across publication/codec retries.
            shutil.copyfile(stable_master,master)
            mq=oppo.measure(master,progress,'MASTER_PCM24_QC')
            if (mq['lufs_i'] is None or abs(mq['lufs_i']-targets.wav_lufs)>.03 or
                mq['true_peak_max_dbtp_estimate']>targets.wav_tp or
                (mq['frames'],mq['samplerate'],mq['channels'])!=(info.frames,info.samplerate,info.channels)):
                raise kernel.NotFeasible('PCM24 output target not met; no false completion')
            cq=cr=None
            if write_mp3:
                cq,cr=codec_branch(master,staged/FILES[1],staged/FILES[2],job,targets,ff,progress)
            if io.file_hash(source)!=h:raise RuntimeError('Source changed')
            report=dict(version=VERSION,status='COMPLETE',identity=ident,source_name=source.name,
                source_unchanged=True,requested_targets=targets.to_dict(),harmonic_elasticity_applied=True,
                chain='HarmonicElasticity -> '+preparation+' -> Note-Sub -> HFTC -> OPPO',
                peak_preparation=ns_report,preparation=preparation,prep_limiter_used=ns_report['prep_limiter_used'],
                conventional_limiter_used=ns_report['prep_limiter_used'],final_conventional_limiter_used=False,
                note_status=ns_report['status'],note_events=ns_report['selected_events'],note_scale=ns_report['selected_scale'],
                hf_stats=stats,hf_cache=cache,master_peak=master_report,
                master_metrics=mq,codec_metrics=cq,codec_branch=cr,
                output_pcm_sha256={FILES[0]:io.pcm_hash(master)},
                mp3_source=FILES[1] if write_mp3 else None,
                naturalness='USER_SELECTED_V01_KERNEL;_GAIN_ONLY_FRONTEND_IS_A_SEPARATE_INTEGRATION_CHANGE')
            if write_mp3:report['output_pcm_sha256'][FILES[1]]=io.pcm_hash(staged/FILES[1])
            io.atomic_json(staged/'RUN_REPORT.json',report)
            text=(f'# PDRM OPPO 完了 — {source.name}\n\n'
                f'HarmonicElasticity → 前段 {preparation} → Note-Sub → HFTC → オフライン波形最適化。\n'
                f'前段リミッター: {ns_report["prep_limiter_used"]}。最終段・MP3分岐に通常リミッターはありません。\n\n'
                f'WAV: {mq["lufs_i"]:.4f} LUFS / TP推定 {mq["true_peak_max_dbtp_estimate"]:.4f} dBTP。\n'
                f'前段の描画基準: {ns_report["physical_target_lufs"]:.4f} LUFS。分析参照は−14 LUFS。\n')
            if cq:text+=f'MP3: {cq["lufs_i"]:.4f} LUFS / TP推定 {cq["true_peak_max_dbtp_estimate"]:.4f} dBTP。\n'
            text+='\n元音は未変更。TPは4倍・8倍補間の数値推定。知覚品質の保証値ではありません。\n'
            (staged/'完了.md').write_text(text,encoding='utf-8')
            io.atomic_json(staged/'PROOF.json',dict(identity=ident,files={p.name:io.file_hash(p) for p in staged.iterdir() if p.is_file()}))
            for p in staged.iterdir():io.sync_owned_file(p)
            if final.exists():raise RuntimeError('Result appeared; nothing overwritten')
            os.rename(staged,final);register(root,report);progress.set('COMPLETE',1,1)
            return report,final
        except Exception as exc:
            io.atomic_json(job/'FAILURE.json',dict(error=repr(exc),stage=progress.state,traceback=traceback.format_exc()))
            raise


def run_file(source,root,*,targets=None,write_mp3=True,interrupt_after=None,preparation='gain_only'):
    with _LOCK,legacy._RUNTIME_LOCK:
        return _run_file(source,root,targets=targets,write_mp3=write_mp3,interrupt_after=interrupt_after,preparation=preparation)
