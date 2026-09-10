"""Explicit-planner integration LAB. Not the production GUI entry.

Actual existing HE/AUTO/HFTC/codec are retained. Backend selection is explicit,
from a fixed registry: original broad path or joint broad+narrow path. A JSON
plan never imports code. Model/planner/taste approval are separate release gates.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
import importlib.metadata
import json
import os
import shutil
import numpy as np
import soundfile as sf
import distribution_finish as common
import auto_peak_v34 as auto
import hf_temporal_contrast_lab as hf
from target_settings import Targets
import lowend_coordinator_v40 as coordinator
from integration_contract_v40 import AudioIdentity, RenderSnapshot, capture, digest, file_hash, valid_hash

VERSION = 'integrated-finish-lab-0.2.0'
MODULES = ('integration_contract_v40.py', 'lowend_coordinator_v40.py', 'integrated_finish_v40.py',
           'lowend_boundary_lab.py', 'distribution_finish.py', 'auto_peak_v34.py',
           'hf_temporal_contrast_lab.py', 'offline_peak_stream_v34.py',
           'offline_peak_stream_v32.py', 'offline_peak_context_v34.py',
           'offline_peak_lab.py', 'distribution_peak.py', 'target_settings.py')
io = common.io


@dataclass(frozen=True)
class PlanningContext:
    source_path: Path
    physical_path: Path
    snapshot: RenderSnapshot


class Planner(Protocol):
    def identity(self) -> dict: ...
    def preflight(self) -> None: ...
    def build(self, context: PlanningContext, progress=None) -> dict: ...


def _verify_audio(path, template, lufs, tp, progress, stage):
    result = auto.measure(path, progress, stage)
    if (result['lufs_i'] is None or abs(result['lufs_i']-lufs) > .03 or
            result['true_peak_max_dbtp_estimate'] > tp or
            (result['samplerate'], result['frames'], result['channels']) !=
            (template.samplerate, template.frames, template.channels)):
        raise RuntimeError('Saved audio failed geometry/LUFS/TP: ' + stage)
    return result


def _codec(master, stage, work, targets, ff, progress):
    """Same delivered WAV as source for EVERY attempt. No MP3-to-MP3 chain."""
    master_hash = file_hash(master); info = sf.info(master)
    target, ceiling = targets.mp3_lufs, targets.mp3_tp
    trials = []; mp3 = stage/'LISTEN_320kbps.mp3'; listen = stage/'ENCODE_INPUT.wav'
    for attempt in range(6):
        branch = work/f'CODEC_PASS_{attempt}.wav'
        report = auto.fit(master, branch, work/f'codec_{attempt}', target, ceiling, progress=progress)
        common.write_pcm24(branch, listen)
        rate = info.samplerate if info.samplerate <= 48000 else 48000
        common.peak.execute(ff, ['-i',str(listen),'-map','0:a:0','-map_metadata','-1',
            '-ar',str(rate),'-c:a','libmp3lame','-b:a','320k',str(mp3)],
            work/'encode.log', progress, 'INTEGRATED_ENCODE_MP3')
        decoded = work/'MP3_DECODED.wav'
        common.peak.execute(ff, ['-i',str(mp3),'-map_metadata','-1','-c:a','pcm_f32le',str(decoded)],
            work/'decode.log', progress, 'INTEGRATED_DECODE_MP3')
        met = auto.measure(decoded, progress, 'INTEGRATED_MP3_QC')
        expected = round(info.frames*rate/info.samplerate)
        if met['lufs_i'] is None or met['samplerate'] != rate or met['channels'] != info.channels or abs(met['frames']-expected) > (0 if rate==info.samplerate else 1):
            raise RuntimeError('Decoded codec geometry/loudness invalid')
        error = targets.mp3_lufs-met['lufs_i']; excess = met['true_peak_max_dbtp_estimate']-targets.mp3_tp
        trials.append(dict(attempt=attempt, auto_report=report, decoded_metrics=met))
        if abs(error) <= .03 and excess <= 0:
            if file_hash(master) != master_hash: raise RuntimeError('Delivered master changed in codec branch')
            return met, trials
        target += error
        if excess > 0: ceiling -= excess+max(0.,error)+.05
        if not -30 <= target <= -8 or not -12 <= ceiling <= -1:
            break
    raise RuntimeError('Codec targets unresolved within bounded attempts; no false completion')


def _proof(final, identity):
    proof = io.read_json(final/'PROOF.json')
    if proof.get('identity') != identity:
        raise RuntimeError('Foreign output identity')
    expected = {'MASTER.wav', 'RUN_REPORT.json', '完了.md'}
    if identity['write_mp3']: expected |= {'ENCODE_INPUT.wav','LISTEN_320kbps.mp3'}
    if set(proof.get('files',{})) != expected or {p.name for p in final.iterdir()} != expected | {'PROOF.json'}:
        raise RuntimeError('Output file set changed')
    for name, value in proof['files'].items():
        p = final/name
        if p.is_symlink() or not p.is_file() or file_hash(p) != value:
            raise RuntimeError('Saved output changed: ' + name)
    return io.read_json(final/'RUN_REPORT.json')


def run_lab(source, root, planner: Planner | None, *, targets=None, write_mp3=True,
            enable_lab=False, progress=None, render_backend='broad-v40'):
    """Finite, explicitly requested LAB path; production entry is unchanged.

    Does not yet resume a crash or publish into processed. Only a newly owned
    temporary job is cleaned. Backend identity is included in cached outputs.
    """
    if enable_lab is not True:
        raise RuntimeError('Release blocked: automatic planner/model acceptance is not complete')
    if render_backend == 'broad-v40':
        engine=coordinator;extra_modules=()
    elif render_backend == 'joint-v42':
        import joint_lowend_v42 as engine
        extra_modules=('joint_lowend_v42.py','physical_decay_bridge_v42.py')
    else:
        raise ValueError('Unknown fixed-registry renderer; no dynamic module import')
    if planner is None:
        raise ValueError('An explicit planner is required; no silent KEEP fallback')
    pid = planner.identity()
    if not isinstance(pid, dict) or not isinstance(pid.get('planner_id'), str) or not pid['planner_id'] or not valid_hash(pid.get('calibration_sha256')) or pid.get('evidence_scope') not in ('engineering_fixture','research_observer'):
        raise ValueError('Invalid LAB planner identity')
    pid = json.loads(json.dumps(pid, sort_keys=True, allow_nan=False))
    planner.preflight()
    targets = (targets or Targets()).validate()
    if type(write_mp3) is not bool: raise ValueError('Explicit codec flag required')
    source = Path(source).resolve(strict=True); root = Path(root)
    if root.is_symlink(): raise ValueError('Work root must not be a symlink')
    root = root.resolve()
    if root == source.parent or source.parent in root.parents:
        raise ValueError('LAB root must be outside the original source folder')
    original = capture(source)
    common.legacy.verify_dsp(); auto.verify_kernel()
    ff = io.ffmpeg_path()
    if not ff: raise RuntimeError('FFmpeg required for existing AUTO safety policy')
    common.peak.check_ffmpeg(ff)
    identity = dict(version=VERSION, source=original.token, planner=pid,render_backend=render_backend,
        code={name:file_hash(Path(__file__).with_name(name)) for name in MODULES+extra_modules},
        targets=targets.to_dict(), write_mp3=write_mp3, ffmpeg_sha256=file_hash(ff),
        versions={n:importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')})
    key = digest(identity)[:24]
    root.mkdir(parents=True, exist_ok=True)
    final = root/('INTEGRATION_LAB_'+key)
    with io.job_lock(root/(key+'.lock')):
        if final.exists():
            result = _proof(final, identity)
            return dict(result, rerun_status='IDEMPOTENT_SKIP'), final
        if shutil.disk_usage(root).free < original.frames*2*8*8 + 64*1024**2:
            raise OSError('Insufficient working space')
        state = 'PREPARE'
        try:
            with TemporaryDirectory(prefix='.integration40_', dir=root) as owned:
                owned = Path(owned); work = owned/'work'; work.mkdir(); stage = owned/'result'; stage.mkdir()
                with io.Progress(work) as default_progress:
                    pr = progress or default_progress
                    he = work/'HARMONIC.wav'; common.render_harmonic(source, he, pr)
                    physical = work/'PHYSICAL.wav'
                    prep = auto.fit(he, physical, work/'prep', -14., -2.5, progress=pr)
                    physical_id = capture(physical)
                    _verify_audio(physical, original, -14., -2.5, pr, 'PREPARED_QC')
                    snapshot = RenderSnapshot.bind(original, physical_id,
                        dict(he_code=identity['code']['distribution_finish.py'], auto_code=identity['code']['auto_peak_v34.py'],
                             preparation_lufs=-14., preparation_tp=-2.5, route=prep['auto_route']))
                    state = 'PLAN'
                    context = PlanningContext(source, physical, snapshot)
                    plan = planner.build(context, pr)
                    if planner.identity() != pid: raise RuntimeError('Planner identity changed mid-job')
                    if not isinstance(plan, dict) or any(plan.get(k) != pid[k] for k in ('planner_id','calibration_sha256','evidence_scope')):
                        raise ValueError('Plan provenance differs from selected planner')
                    snapshot.verify(source, physical); engine.validate_plan(plan, snapshot)
                    note = work/'LOWEND.wav'
                    state = 'LOWEND_RENDER'
                    low = engine.render(source, physical, note, snapshot, plan, progress=pr)
                    nm = auto.measure(note, pr, 'LOWEND_QC')
                    if nm['lufs_i'] is None: raise RuntimeError('Low-end candidate is silent')
                    state = 'HFTC'
                    anchor = auto.scaled_file(note, work/'HF_ANALYSIS.wav', -14.-nm['lufs_i'], pr)
                    times, gains, hf_stats = hf.analyze_control(anchor, hf.Config(), pr)
                    hf_raw, hf_cache = hf.render_raw(note, work/'hf', times, gains, hf.Config(), pr)
                    state = 'MASTER'
                    master_float = work/'MASTER_FLOAT.wav'
                    master_report = auto.fit(hf_raw, master_float, work/'master', targets.wav_lufs, targets.wav_tp, progress=pr)
                    master = stage/'MASTER.wav'; common.write_pcm24(master_float, master)
                    mq = _verify_audio(master, original, targets.wav_lufs, targets.wav_tp, pr, 'SAVED_MASTER_QC')
                    cm = None; trials = []
                    if write_mp3:
                        state = 'CODEC'; cm, trials = _codec(master, stage, work, targets, ff, pr)
                    original.verify(source)
                    report = dict(version=VERSION, status='LAB_RENDER_COMPLETE_NOT_LISTENING_APPROVED',
                        identity=identity, source_name=source.name, source_unchanged=True,
                        chain='HE -> AUTO_PREP -> NEW_LOWEND_COORDINATOR -> HFTC -> AUTO_MASTER -> CODEC_QC',
                        old_note_sub_called=False, sub_synthesis='NOT_CONNECTED',render_backend=render_backend,
                        lowend_assessment=plan['assessment'], lowend_report=low,
                        planner_report=getattr(planner,'last_report',None),
                        planner_evidence_scope=pid['evidence_scope'], snapshot_sha256=snapshot.token,
                        requested_targets=targets.to_dict(), preparation=prep, master=master_report,
                        master_metrics=mq, codec_metrics=cm, codec_trials=trials, hf_stats=hf_stats,
                        hf_cache=hf_cache, calibration_is_personal_taste_approval=False,
                        production_gui_changed=False, resume_supported=False)
                    pr.set('LAB_AUDIO_VERIFIED', 1, 1)
                work_bytes = sum(p.stat().st_size for p in work.rglob('*') if p.is_file())
                shutil.rmtree(work)
                if work.exists(): raise RuntimeError('Job workspace cleanup incomplete')
                report['intermediate_audio_removed'] = True
                report['work_bytes_removed'] = work_bytes
                io.atomic_json(stage/'RUN_REPORT.json', report)
                (stage/'完了.md').write_text('# PDRM 統合LAB\n\n'
                    '既存HE・AUTO・HFTCへ、新低域入口を接続した研究結果です。新規サブ生成は未接続。\n'
                    '実曲の改善・配布版の完成を意味しません。\n'
                    f'低域描画: {render_backend}。判断: {plan["assessment"]}。前段: {prep["auto_route"]}。最終: {master_report["auto_route"]}。\n'
                    f'WAV: {mq["lufs_i"]:.5f} LUFS / {mq["true_peak_max_dbtp_estimate"]:.5f} dBTP。\n'
                    f'中間作業物削除: {work_bytes} bytes。元音源は未変更。\n', encoding='utf-8')
                io.atomic_json(stage/'PROOF.json', dict(identity=identity,
                    files={p.name:file_hash(p) for p in stage.iterdir() if p.is_file()}))
                for p in stage.iterdir(): io.sync_owned_file(p)
                if final.exists(): raise FileExistsError('Result appeared; nothing overwritten')
                os.rename(stage, final)
            return _proof(final, identity), final
        except BaseException as exc:
            io.atomic_json(root/(key+'.failure.json'), dict(version=VERSION, stage=state,
                error_type=type(exc).__name__, error=str(exc), status='LAB_NOT_COMPLETED'))
            raise
