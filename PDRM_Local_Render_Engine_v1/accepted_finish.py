"""Explicit opt-in Note-Sub -> HFTC entry. Frozen DSP, no blind tests or limiter.

This is a new orchestration path, not a reconstruction of the old three-song
peak-protected comparison. Production modules and single-track launchers remain
untouched. All job state and personal audio stay on the local machine.
"""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_key, '1')
import argparse
from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import importlib.metadata
from pathlib import Path
import shutil
import sys
import threading
import traceback

import soundfile as sf
import note_sub_lab as io
import note_sub_lab_v02 as ns
import hf_temporal_contrast_lab as hf

VERSION = 'accepted-finish-1.0.0'
DSP_SHA256 = {
    'note_sub_lab.py': '468f9faf79176da369f0284ee3d1d415929c9610b423d16a996980ca573fcdf6',
    'note_sub_lab_v02.py': 'bf151b4a3b98d1d34c1aae6ba14f50dcf7d19a1d935d0153e7ffcc6561a3c470',
    'hf_temporal_contrast_lab.py': 'c111290018159969597a2bd58516d7720b77989f85cf50c32d40caab4f1acf90',
}
TARGET_LUFS = -14.0
INPUT_TP = -2.5     # One dB of headroom below the existing Note-Sub PCM ceiling.
FINAL_TP = -1.5
CODEC_TP = -1.0
_RUNTIME_LOCK = threading.RLock()
KNOWN_PROCESSED_FILES = {
    hf.KNOWN_B,
    'fe2671d0300562f325f67d6ac5cf5ea07b0e94c6498278c13233fcd01ac3200c',
}


def verify_dsp() -> dict[str, str]:
    actual = {}
    for module in (io, ns, hf):
        p = Path(module.__file__)
        text = p.read_text(encoding='utf-8-sig')
        sha = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if DSP_SHA256.get(p.name) != sha:
            raise RuntimeError('Frozen DSP differs: ' + p.name)
        actual[p.name] = sha
    return actual


def safe_target(metrics: dict) -> float:
    """Lower the constant normalization level instead of adding a limiter."""
    lufs = metrics['lufs_i']
    if lufs is None:
        raise ValueError('Silent input: nothing to finish')
    return float(min(TARGET_LUFS, lufs + INPUT_TP - metrics['true_peak_dbtp_estimate']))


@contextmanager
def _note_level(target: float):
    # ns already uses a temporary compatibility bridge. Serialize it and restore
    # the entire dictionary reference even on exceptions. Change only the level
    # anchor, never pitch thresholds, synthesis caps or HF detector parameters.
    with _RUNTIME_LOCK:
        original = ns.CONFIG
        ns.CONFIG = dict(original, target_lufs=target)
        try:
            yield
        finally:
            ns.CONFIG = original


def _scaled_cache(source: Path, dest: Path, gain: float) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    marker = dest.with_suffix('.done.json')
    context = dict(source=io.file_hash(source), gain=float(gain))
    if io.valid_audio_cache(dest, marker):
        if io.read_json(marker).get('context') == context:
            return
    temp = dest.with_suffix('.partial.wav')
    hf.write_scaled(source, temp, gain)
    os.replace(temp, dest)
    io.atomic_json(marker, dict(sha256=io.file_hash(dest), context=context))


def _verify_result(final: Path, ident: dict) -> dict:
    proof = io.read_json(final / 'PROOF.json')
    if proof.get('identity') != ident:
        raise RuntimeError('Result identity differs; nothing overwritten')
    for name, sha in proof['files'].items():
        p = (final / name).resolve()
        if final.resolve() not in p.parents or not p.is_file() or io.file_hash(p) != sha:
            raise RuntimeError('Result modified; nothing overwritten: ' + name)
    return io.read_json(final / 'RUN_REPORT.json')


def _register_output(root: Path, report: dict) -> None:
    io.atomic_json(root / 'processed_pcm' / (report['output_pcm_sha256'] + '.json'),
                   dict(version=VERSION, output_pcm_sha256=report['output_pcm_sha256']))


def _validate_paths(source: Path, root: Path) -> None:
    if (root == source.parent or source.parent in root.parents or root in source.parents):
        raise ValueError('Output must be outside the source directory; processed output is not an input')
    bad_names = ('finished', 'sub_augmented', 'hftc_candidate', 'pdrm_accepted')
    if source.stem.lower().startswith(bad_names) or source.stem.lower().endswith('_pdrm'):
        raise ValueError('Already-processed filename: do not apply the chain twice')


def _run_file(source, root, *, write_mp3=True, interrupt_after=None) -> tuple[dict, Path]:
    source, root = Path(source).resolve(strict=True), Path(root).resolve()
    _validate_paths(source, root)
    hashes = verify_dsp()
    info = sf.info(source)
    hf.Config().validate(info.samplerate)
    if source.suffix.lower() not in ('.wav', '.flac') or info.channels != 2 or info.duration < .5:
        raise ValueError('Stereo WAV/FLAC, 44.1/48/88.2/96 kHz, at least 0.5 seconds required')
    source_hash = io.file_hash(source)
    source_pcm = io.pcm_hash(source)
    if (source_hash in KNOWN_PROCESSED_FILES or
            (root / 'processed_pcm' / (source_pcm + '.json')).is_file()):
        raise ValueError('This PCM has already been processed; renamed copies are not fresh inputs')
    ff = io.ffmpeg_path() if write_mp3 else None
    if write_mp3 and not ff:
        raise RuntimeError('Existing ffmpeg not found; no installation was attempted')
    ident = dict(version=VERSION, source_sha256=source_hash, source_pcm_sha256=source_pcm,
                 entry_sha256=io.file_hash(__file__), dsp_sha256=hashes,
                 versions={n: importlib.metadata.version(n) for n in
                           ('numpy', 'scipy', 'soundfile', 'pyloudnorm')},
                 policy=dict(target_lufs=TARGET_LUFS, input_tp=INPUT_TP,
                             final_tp=FINAL_TP, codec_tp=CODEC_TP, limiter=False,
                             harmonic_elasticity=False),
                 hf_config=asdict(hf.Config()), write_mp3=write_mp3,
                 ffmpeg_sha256=io.file_hash(ff) if ff else None)
    job = root / ('finish_' + io.obj_hash(ident)[:20])
    job.mkdir(parents=True, exist_ok=True)
    with io.job_lock(job / 'job.lock'), io.Progress(job) as progress:
        final = job / 'RESULT'
        if final.exists():
            report = _verify_result(final, ident)
            _register_output(root, report)
            report = dict(report, rerun_status='IDEMPOTENT_SKIP')
            return report, final
        identity_path = job / 'identity.json'
        if identity_path.exists() and io.read_json(identity_path) != ident:
            raise RuntimeError('Job identity differs; nothing overwritten')
        io.atomic_json(identity_path, ident)
        try:
            baseline = io.measure(source, progress, 'INPUT_LEVEL')
            target = safe_target(baseline)
            reference = job / 'input' / 'REFERENCE.wav'
            _scaled_cache(source, reference, 10 ** ((target - baseline['lufs_i']) / 20))
            reference_metrics = io.measure(reference, progress, 'REFERENCE_QC')
            if (abs(reference_metrics['lufs_i'] - target) > .01 or
                    reference_metrics['true_peak_dbtp_estimate'] > INPUT_TP + 1e-5):
                raise RuntimeError('Constant-gain input normalization failed')
            with _note_level(target):
                note_report, note_result = ns.run_job(
                    reference, job / 'note_jobs', write_mp3=False,
                    expected_hash=io.file_hash(reference),
                    interrupt_after=interrupt_after if isinstance(interrupt_after, int) else None)
            note_wav = note_result / 'SUB_AUGMENTED.wav'
            note_hash = io.file_hash(note_wav)
            if interrupt_after == 'note':
                raise RuntimeError('TEST_INTERRUPTION_AFTER_NOTE')
            cfg = hf.Config()
            times, gain, stats = hf.analyze_control(note_wav, cfg, progress)
            raw, cache = hf.render_raw(note_wav, job / 'hf_work', times, gain, cfg, progress)
            raw_metrics = io.measure(raw, progress, 'HF_QC')
            requested_gain = target - raw_metrics['lufs_i']
            if abs(requested_gain) > cfg.max_match_gain_db:
                raise RuntimeError('HF level-matching budget exceeded; no output published')
            final_gain = min(requested_gain,
                             FINAL_TP - .01 - raw_metrics['true_peak_dbtp_estimate'])
            staged = job / 'publish_staging'
            if staged.exists():
                shutil.rmtree(staged)
            staged.mkdir()
            hf.write_scaled(raw, staged / 'FINISHED.wav', 10 ** (final_gain / 20))
            metrics = io.measure(staged / 'FINISHED.wav', progress, 'FINAL_PCM_QC')
            final_target = raw_metrics['lufs_i'] + final_gain
            if (metrics['true_peak_dbtp_estimate'] > FINAL_TP or
                    abs(metrics['lufs_i'] - final_target) > .01 or
                    metrics['lufs_i'] > TARGET_LUFS + .01 or
                    (metrics['frames'], metrics['samplerate'], metrics['channels']) !=
                    (info.frames, info.samplerate, info.channels)):
                raise RuntimeError('Final PCM gate failed; no output published')
            codec = None
            if ff:
                io.codec_file(ff, staged / 'FINISHED.wav', staged / 'FINISHED_320kbps.mp3')
                decoded = job / 'codec_decoded.wav'
                io.codec_file(ff, staged / 'FINISHED_320kbps.mp3', decoded, True)
                codec = io.measure(decoded, progress, 'MP3_QC')
                if (codec['lufs_i'] is None or
                        abs(codec['lufs_i'] - metrics['lufs_i']) > .10 or
                        codec['true_peak_dbtp_estimate'] > CODEC_TP or
                        (codec['frames'], codec['samplerate'], codec['channels']) !=
                        (info.frames, info.samplerate, info.channels)):
                    raise RuntimeError('MP3 gate failed; nothing published and no limiter added')
            if io.file_hash(source) != source_hash or io.file_hash(note_wav) != note_hash:
                raise RuntimeError('Input/intermediate changed; nothing published')
            report = dict(version=VERSION, status='COMPLETE', source_name=source.name,
                          source_unchanged=True, identity=ident,
                          baseline_metrics=baseline, reference_metrics=reference_metrics,
                          normalization_target_lufs=target, output_target_lufs=final_target,
                          output_metrics=metrics, codec_metrics=codec,
                          peak_limited_level=final_target < TARGET_LUFS - .01,
                          limiter_added=False, harmonic_elasticity_applied=False,
                          note_status=note_report['status'],
                          note_selected_scale=note_report['selected_scale'],
                          note_selected_events=note_report['selected_events'],
                          note_selected_seconds=note_report['selected_seconds'],
                          hf_stats=stats, hf_cache=cache, hf_final_gain_db=final_gain,
                          output_pcm_sha256=io.pcm_hash(staged / 'FINISHED.wav'),
                          listening_acceptance='USER_ACCEPTED_COMBINATION_20260905',
                          scope='New two-stage entry; not an exact recreation of old peak-protected trials')
            io.atomic_json(staged / 'RUN_REPORT.json', report)
            text = (f'# PDRM 完了 — {source.name}\n\n'
                    f'Note-Sub v0.2.1 → HFTC v0.1。出力: FINISHED.wav / FINISHED_320kbps.mp3。\n\n'
                    f'全曲音量: {metrics["lufs_i"]:.3f} LUFS。ピーク推定: '
                    f'{metrics["true_peak_dbtp_estimate"]:.3f} dBTP。\n\n'
                    + ('ピーク余裕を優先して−14 LUFSより低い音量で保存しました。\n\n'
                       if report['peak_limited_level'] else '')
                    + '原音は未変更。リミッター追加・HarmonicElasticity再適用・A/B選択はありません。\n\n'
                    + f'低域段の状態: {note_report["status"]}。追加不要・不確実な区間は既存規則で見送ります。\n\n'
                    + 'この出力を再び入力しないでください。再実行は元の入力を選びます。\n')
            (staged / '完了.md').write_text(text, encoding='utf-8')
            proof = {p.name: io.file_hash(p) for p in staged.iterdir() if p.is_file()}
            io.atomic_json(staged / 'PROOF.json', dict(identity=ident, files=proof))
            for p in staged.iterdir():
                io.sync_owned_file(p)
            if final.exists():
                raise RuntimeError('Result appeared during publication; nothing overwritten')
            os.rename(staged, final)
            _register_output(root, report)
            progress.set('COMPLETE', 1, 1)
            return report, final
        except Exception as exc:
            io.atomic_json(job / 'FAILURE.json', dict(error=repr(exc), traceback=traceback.format_exc(),
                                                   stage=progress.state))
            raise


def run_file(source, root, *, write_mp3=True, interrupt_after=None) -> tuple[dict, Path]:
    # The frozen Note-Sub bridge mutates module globals temporarily. Serialize
    # the entire entry, including identity checks and the HF stage, in-process.
    with _RUNTIME_LOCK:
        return _run_file(source, root, write_mp3=write_mp3, interrupt_after=interrupt_after)


def main() -> int:
    p = argparse.ArgumentParser(description='採用済みNote-Sub＋HFTCを一括実行。原音上書き・追加リミッターなし。')
    p.add_argument('sources', nargs='*', type=Path)
    p.add_argument('--output-root', type=Path)
    p.add_argument('--wav-only', action='store_true')
    args = p.parse_args()
    sources = args.sources
    if not sources:
        import tkinter as tk
        from tkinter import filedialog
        app = tk.Tk(); app.withdraw()
        try:
            sources = [Path(n) for n in filedialog.askopenfilenames(
                title='仕上げるステレオWAV/FLACを選択（複数可・PDRM追加2段の適用前）',
                filetypes=[('Audio', '*.wav *.flac')])]
        finally:
            app.destroy()
    if not sources:
        return 0
    root = args.output_root or Path(os.environ.get('LOCALAPPDATA',
                    str(Path.home() / '.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'accepted_finish'
    root.mkdir(parents=True, exist_ok=True)
    rows, failures = [], 0
    for i, source in enumerate(sources, 1):
        print(f'[{i}/{len(sources)}] {source.name}', flush=True)
        try:
            r, final = run_file(source, root, write_mp3=not args.wav_only)
            print('完了:', final, flush=True)
            rows.append(f'- {source.name}: 完了 {final}\n')
        except Exception as exc:
            failures += 1
            print('未出力:', source.name, str(exc), flush=True)
            rows.append(f'- {source.name}: 未出力 {exc}\n')
    summary = root / 'LAST_RUN.md'
    summary.write_text('# 一括処理結果\n\n' + ''.join(rows), encoding='utf-8')
    print('結果一覧:', summary, flush=True)
    if os.name == 'nt':
        try:
            os.startfile(str(root))
        except OSError:
            pass  # Audio publication is complete even when Explorer cannot open.
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
