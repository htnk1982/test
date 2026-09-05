"""Distribution v2: HE -> shared peak preparation -> Note-Sub -> HFTC -> peak master.

Explicit user-authorized limiter and HarmonicElasticity, added 2026-09-05.
No production imports/modifications, no recreation claim for the undocumented
three-song peak processor. All audio and full reports stay in the chosen folder.
"""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_key, '1')
import argparse
from dataclasses import asdict
import hashlib
import importlib.metadata
from pathlib import Path
import re
import shutil
import sys
import threading
import traceback
import numpy as np
import soundfile as sf
from scipy import signal
import accepted_finish as legacy
import note_sub_lab as io
import note_sub_lab_v02 as ns
import hf_temporal_contrast_lab as hf
import distribution_peak as peak

VERSION = 'distribution-finish-2.0.0'
MASTER_LUFS, MASTER_TP, LISTEN_LUFS = -12.0, -2.0, -14.0
PREP_LUFS, PREP_TP = -14.0, -2.5
FILES = ('MASTER_12LUFS.wav', 'LISTEN_14LUFS.wav', 'LISTEN_14LUFS_320kbps.mp3')
_LOCK = threading.RLock()


def harmonic_elasticity(x):
    # Exact existing float32 transfer (operators.py blob 7821843f...): no increase.
    u = np.asarray(x, dtype=np.float32)
    a, q = .105, .30
    return (u - a * (u ** 3) + q * (a * a) * (u ** 5)).astype(np.float32, copy=False)


def render_harmonic(source: Path, dest: Path, progress=None):
    context = dict(source=io.file_hash(source), code=io.file_hash(__file__),
                   amount=.105, quintic_scale=.30, oversample=4, chunk_seconds=8, pad_seconds=.08)
    marker = dest.with_suffix('.he.json')
    if dest.exists() and marker.exists():
        r = io.read_json(marker)
        if r.get('context') == context and r.get('sha256') == io.file_hash(dest):
            return
    temp = dest.with_suffix('.partial.wav')
    with sf.SoundFile(source) as src, sf.SoundFile(temp, 'w', samplerate=src.samplerate,
            channels=2, format='WAV', subtype='FLOAT') as dst:
        sr, n = src.samplerate, src.frames
        width, pad = 8 * sr, round(.08 * sr)
        for start in range(0, n, width):
            end = min(n, start + width)
            a, b = max(0, start-pad), min(n, end+pad)
            src.seek(a)
            x = src.read(b-a, dtype='float32', always_2d=True)
            io.finite(x)
            up = signal.resample_poly(x, 4, 1, axis=0, window=('kaiser', 10.5)).astype('float32')
            processed = harmonic_elasticity(up)
            down = signal.resample_poly(processed, 1, 4, axis=0, window=('kaiser', 10.5)).astype('float32')
            if len(down) < len(x):
                down = np.pad(down, ((0, len(x)-len(down)), (0, 0)))
            y = down[start-a:end-a]
            io.finite(y)
            dst.write(y)
            if progress:
                progress.set('HARMONIC_ELASTICITY', end, n)
    io.sync_owned_file(temp)
    os.replace(temp, dest)
    io.atomic_json(marker, dict(context=context, sha256=io.file_hash(dest)))


def write_pcm24(source: Path, dest: Path, gain_db=0.0):
    gain = 10 ** (gain_db / 20)
    temp = dest.with_suffix('.partial.wav')
    with sf.SoundFile(source) as src, sf.SoundFile(temp, 'w', samplerate=src.samplerate,
            channels=src.channels, format='WAV', subtype='PCM_24') as dst:
        for x in src.blocks(blocksize=65536, dtype='float64', always_2d=True):
            y = x * gain
            io.finite(y)
            if np.max(np.abs(y)) >= 1:
                raise RuntimeError('24-bit export would clip')
            dst.write(y)
    io.sync_owned_file(temp)
    os.replace(temp, dest)


def validate_paths(source: Path, root: Path):
    # Same parent is allowed: outputs use a new uniquely-owned subdirectory.
    if root.exists() and not root.is_dir():
        raise ValueError('Output folder is not a directory')
    bad = ('finished', 'sub_augmented', 'hftc_candidate', 'pdrm_accepted', 'master_12lufs', 'listen_14lufs')
    if source.stem.lower().startswith(bad) or any(p.name in ('.pdrm_work_v2', 'RESULT') for p in source.parents):
        raise ValueError('Already-processed output is not a fresh input')


def safe_name(name: str) -> str:
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:64]
    return s or 'audio'


def verify_final(final: Path, ident: dict) -> dict:
    try:
        proof = io.read_json(final / 'PROOF.json')
    except (OSError, ValueError):
        raise RuntimeError('Foreign/incomplete result; nothing overwritten') from None
    expected = set(FILES if ident['mp3'] else FILES[:2]) | {'RUN_REPORT.json', '完了.md'}
    if proof.get('identity') != ident or set(proof.get('files', {})) != expected:
        raise RuntimeError('Result identity/file set differs; nothing overwritten')
    for name, sha in proof['files'].items():
        p = final / name
        if not p.is_file() or io.file_hash(p) != sha:
            raise RuntimeError('Result modified; nothing overwritten: ' + name)
    return io.read_json(final / 'RUN_REPORT.json')


def register(root, report):
    for sha in report['output_pcm_sha256'].values():
        io.atomic_json(root / '.pdrm_processed_v2' / (sha+'.json'),
                       dict(version=VERSION, pcm_sha256=sha))


def _run_file(source, root, *, write_mp3=True, interrupt_after=None):
    source, root = Path(source).resolve(strict=True), Path(root).resolve()
    validate_paths(source, root)
    dsp = legacy.verify_dsp()
    info = sf.info(source)
    if source.suffix.lower() not in ('.wav', '.flac') or info.channels != 2 or info.duration < .5:
        raise ValueError('Stereo WAV/FLAC, at least 0.5 seconds required')
    hf.Config().validate(info.samplerate)
    h, pcm = io.file_hash(source), io.pcm_hash(source)
    if (h in legacy.KNOWN_PROCESSED_FILES or
            (root / '.pdrm_processed_v2' / (pcm+'.json')).exists() or
            (root / 'processed_pcm' / (pcm+'.json')).exists()):
        raise ValueError('This PCM has already been processed')
    ff = io.ffmpeg_path()
    if not ff:
        raise RuntimeError('Existing FFmpeg is required for peak protection; nothing installed')
    peak.check_ffmpeg(ff)
    ident = dict(version=VERSION, source_sha256=h, source_pcm_sha256=pcm,
                 code={n: io.file_hash(Path(__file__).with_name(n)) for n in
                       ('distribution_finish.py', 'distribution_peak.py', 'accepted_finish.py')},
                 frozen_dsp=dsp, ffmpeg_sha256=io.file_hash(ff),
                 versions={n: importlib.metadata.version(n) for n in
                           ('numpy', 'scipy', 'soundfile', 'pyloudnorm')},
                 targets=dict(master_lufs=MASTER_LUFS, master_tp_ceiling=MASTER_TP,
                              listen_lufs=LISTEN_LUFS, prep_lufs=PREP_LUFS, prep_tp_ceiling=PREP_TP),
                 peak_config=asdict(peak.PeakConfig()), he=True, mp3=write_mp3)
    key = io.obj_hash(ident)[:20]
    job = root / '.pdrm_work_v2' / key
    final = root / (safe_name(source.stem) + '__PDRM_' + key[:12])
    job.mkdir(parents=True, exist_ok=True)
    with io.job_lock(job / 'job.lock'), io.Progress(job) as progress:
        if final.exists():
            report = verify_final(final, ident)
            register(root, report)
            return dict(report, rerun_status='IDEMPOTENT_SKIP'), final
        identity_file = job / 'identity.json'
        if identity_file.exists() and io.read_json(identity_file) != ident:
            raise RuntimeError('Job identity differs')
        io.atomic_json(identity_file, ident)
        try:
            baseline = peak.measure(source, progress, 'BASELINE')
            if baseline['lufs_i'] is None:
                raise ValueError('Silent input cannot be normalized to finite LUFS')
            (job / 'input').mkdir(exist_ok=True)
            he = job / 'input' / 'HARMONIC.wav'
            render_harmonic(source, he, progress)
            prep = job / 'input' / 'PREPARED.wav'
            prep_report = peak.fit(he, prep, job/'prep_peak', PREP_LUFS, PREP_TP, ff, progress)
            if interrupt_after == 'prepare':
                raise RuntimeError('TEST_INTERRUPTION_AFTER_PREPARE')
            # All adopted DSP thresholds stay unchanged, including the -14 anchor.
            note_report, note_out = ns.run_job(prep, job/'note', write_mp3=False,
                                             expected_hash=io.file_hash(prep))
            note_wav = note_out / 'SUB_AUGMENTED.wav'
            if interrupt_after == 'note':
                raise RuntimeError('TEST_INTERRUPTION_AFTER_NOTE')
            cfg = hf.Config()
            times, gains, stats = hf.analyze_control(note_wav, cfg, progress)
            raw, hf_cache = hf.render_raw(note_wav, job/'hf', times, gains, cfg, progress)
            master_float = job/'MASTER_FLOAT.wav'
            master_report = peak.fit(raw, master_float, job/'master_peak', MASTER_LUFS, MASTER_TP, ff, progress)
            if interrupt_after == 'master':
                raise RuntimeError('TEST_INTERRUPTION_AFTER_MASTER')
            staged = job/'publish_staging'
            if staged.exists():
                shutil.rmtree(staged)
            staged.mkdir()
            master = staged/FILES[0]
            listen = staged/FILES[1]
            write_pcm24(master_float, master)
            master_qc = peak.measure(master, progress, 'MASTER_24BIT')
            # Generate the -14 WAV from the actual published -12 WAV, not the
            # original or an MP3, and do not limit again.
            listen_gain = LISTEN_LUFS - master_qc['lufs_i']
            write_pcm24(master, listen, listen_gain)
            listen_qc = peak.measure(listen, progress, 'LISTEN_24BIT')
            for met, target in ((master_qc, MASTER_LUFS), (listen_qc, LISTEN_LUFS)):
                if (met['lufs_i'] is None or abs(met['lufs_i']-target) > .03 or
                        met['true_peak_max_dbtp_estimate'] > MASTER_TP or
                        (met['frames'], met['samplerate'], met['channels']) !=
                        (info.frames, info.samplerate, info.channels)):
                    raise RuntimeError('Published WAV LUFS/TP/shape gate failed')
            codec_qc = None
            if write_mp3:
                codec_rate = info.samplerate if info.samplerate <= 48000 else 48000
                mp3 = staged/FILES[2]
                peak.execute(ff, ['-i', str(listen), '-map', '0:a:0', '-map_metadata', '-1',
                     '-ar', str(codec_rate), '-c:a', 'libmp3lame', '-b:a', '320k', str(mp3)],
                     job/'mp3_encode.log', progress, 'ENCODE_MP3_FROM_14_WAV')
                decoded = job/'MP3_DECODED.wav'
                peak.execute(ff, ['-i', str(mp3), '-map_metadata', '-1', '-c:a', 'pcm_f32le', str(decoded)],
                             job/'mp3_decode.log', progress, 'MP3_DECODE')
                codec_qc = peak.measure(decoded, progress, 'MP3_ROUNDTRIP')
                expected_frames = round(info.frames * codec_rate / info.samplerate)
                if (codec_qc['lufs_i'] is None or abs(codec_qc['lufs_i']-LISTEN_LUFS) > .10 or
                        codec_qc['true_peak_max_dbtp_estimate'] > MASTER_TP or
                        abs(codec_qc['frames']-expected_frames) > (0 if codec_rate == info.samplerate else 1) or
                        codec_qc['samplerate'] != codec_rate or codec_qc['channels'] != 2):
                    raise RuntimeError('MP3 LUFS/TP/length gate failed; no false completion')
            if io.file_hash(source) != h:
                raise RuntimeError('Source changed during processing')
            report = dict(version=VERSION, status='COMPLETE', source_name=source.name,
                          source_unchanged=True, identity=ident, baseline_metrics=baseline,
                          harmonic_elasticity_applied=True, peak_protection_implemented=True,
                          peak_preparation=prep_report, master_peak=master_report,
                          note_status=note_report['status'], note_scale=note_report['selected_scale'],
                          note_events=note_report['selected_events'], hf_stats=stats, hf_cache=hf_cache,
                          master_metrics=master_qc, listen_metrics=listen_qc, codec_metrics=codec_qc,
                          listen_gain_db=listen_gain, mp3_source=FILES[1],
                          output_pcm_sha256={p.name: io.pcm_hash(p) for p in (master, listen)},
                          scope='New authorized full chain, not a recreation of undocumented old peak protection')
            io.atomic_json(staged/'RUN_REPORT.json', report)
            md = (f'# 配信用出力完了 — {source.name}\n\n'
                  'HarmonicElasticity → 共通ピーク整形 → Note-Sub v0.2.1 → HFTC v0.1 → 配信用ゲイン・ピーク調整。\n\n'
                  f'| 出力 | LUFS-I | TP推定（4x/8xの大きい方） |\n|---|---:|---:|\n'
                  f'| {FILES[0]} | {master_qc["lufs_i"]:.4f} | {master_qc["true_peak_max_dbtp_estimate"]:.4f} dBTP |\n'
                  f'| {FILES[1]} | {listen_qc["lufs_i"]:.4f} | {listen_qc["true_peak_max_dbtp_estimate"]:.4f} dBTP |\n')
            if codec_qc:
                md += f'| {FILES[2]}（復号後） | {codec_qc["lufs_i"]:.4f} | {codec_qc["true_peak_max_dbtp_estimate"]:.4f} dBTP |\n'
            md += ('\n−2 dBTPは上限。−14 WAVは−12 WAVから一定ゲインで作り、MP3は−14 WAVから符号化しました。'
                   '\n\nWAVは24-bit PCM、入力と同じサンプルレート。MP3は44.1/48kHz。原音未変更。'
                   '\n\nこの出力を再度入力せず、やり直す場合は元のWAV/FLACを選んでください。'
                   '\n\n旧3曲比較の未記録ピーク処理の再現ではなく、4倍処理・遅延補償付きalimiterを今回明示実装しました。'
                   'True Peakは数値推定で、聴感を保証する指標ではありません。\n')
            (staged/'完了.md').write_text(md, encoding='utf-8')
            io.atomic_json(staged/'PROOF.json', dict(identity=ident, files={p.name:io.file_hash(p)
                           for p in staged.iterdir() if p.is_file()}))
            for p in staged.iterdir():
                io.sync_owned_file(p)
            if final.exists():
                raise RuntimeError('Result appeared; nothing overwritten')
            os.rename(staged, final)
            register(root, report)
            progress.set('COMPLETE', 1, 1)
            return report, final
        except Exception as exc:
            io.atomic_json(job/'FAILURE.json', dict(error=repr(exc), stage=progress.state,
                                                  traceback=traceback.format_exc()))
            raise


def run_file(source, root, *, write_mp3=True, interrupt_after=None):
    with _LOCK, legacy._RUNTIME_LOCK:
        return _run_file(source, root, write_mp3=write_mp3, interrupt_after=interrupt_after)


def choose_paths(sources, root):
    if sources and root is not None:
        return [Path(s) for s in sources], Path(root)
    import tkinter as tk
    from tkinter import filedialog
    app = tk.Tk()
    app.withdraw()
    try:
        if not sources:
            sources = filedialog.askopenfilenames(title='PDRM配信用：未処理のWAV/FLACを選択（複数可）',
                                                 filetypes=[('Audio', '*.wav *.flac')])
        if not sources:
            return [], None
        if root is None:
            root = filedialog.askdirectory(title='完成WAV・MP3の保存先フォルダを選択', mustexist=True)
        if not root:
            return [], None
        return [Path(s) for s in sources], Path(root)
    finally:
        app.destroy()


def main():
    parser = argparse.ArgumentParser(description='PDRM配信用 v2: -12 WAV / -14 WAV・MP3 / 最大-2 dBTP')
    parser.add_argument('sources', nargs='*', type=Path)
    parser.add_argument('--output-root', type=Path)
    parser.add_argument('--wav-only', action='store_true')
    args = parser.parse_args()
    sources, root = choose_paths(args.sources, args.output_root)
    if not sources:
        print('中止しました。音声は変更していません。')
        return 0
    root.mkdir(parents=True, exist_ok=True)
    rows, failed = [], 0
    for i, source in enumerate(sources, 1):
        print(f'[{i}/{len(sources)}] {source.name}', flush=True)
        try:
            report, final = run_file(source, root, write_mp3=not args.wav_only)
            rows.append(f'- {source.name}: 完了 `{final}`')
            print('完了:', final, flush=True)
        except Exception as exc:
            failed += 1
            rows.append(f'- {source.name}: 未出力 — {exc}')
            print('未出力:', source.name, str(exc), flush=True)
    summary = root/'LAST_RUN_Distribution_v2.md'
    summary.write_text('# PDRM 配信用 v2 実行結果\n\n'+'\n'.join(rows)+'\n', encoding='utf-8')
    if os.name == 'nt':
        try:
            os.startfile(str(root))
        except OSError:
            pass
    return 1 if failed else 0

if __name__ == '__main__':
    raise SystemExit(main())
