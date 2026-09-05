"""User-authorized release stage: -12 LUFS PCM24 WAV, then -14 LUFS MP3.

Frozen Note-Sub/HFTC are reused through accepted_finish; no production imports.
--finished explicitly skips both stages for an already finished lossless source.
The MP3 is ALWAYS encoded from the delivered WAV, with constant gain only.
No dynamic loudnorm, no hard clipping, no silent lowering of the WAV target.
"""
from __future__ import annotations
import os
for _key in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS'):
    os.environ.setdefault(_key, '1')
import argparse
from dataclasses import asdict, dataclass
import importlib.metadata
import math
from pathlib import Path
import shutil
import subprocess
import traceback
import numpy as np
import soundfile as sf
from scipy import signal
import note_sub_lab as io
import accepted_finish as accepted

VERSION = 'release-finish-1.1.0'
WAV_NAME = 'FINISHED_-12LUFS_-2dBTP.wav'
MP3_NAME = 'FINISHED_-14LUFS_320kbps.mp3'


@dataclass(frozen=True)
class Config:
    wav_lufs: float = -12.0
    wav_tp: float = -2.0
    mp3_lufs: float = -14.0
    mp3_tp: float = -2.0
    tolerance_lu: float = 0.03
    ceiling_margin_db: float = 0.05
    attack_ms: float = 5.0
    release_ms: float = 50.0
    oversample: int = 4
    tp_oversample: int = 8
    max_passes: int = 8
    max_gain_db: float = 36.0

    def validate(self) -> None:
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Non-finite configuration')
        if not (-30 <= self.wav_lufs <= -8 and -30 <= self.mp3_lufs <= -8):
            raise ValueError('Unsupported loudness target')
        if not (-10 <= self.wav_tp <= -1 and -10 <= self.mp3_tp <= -1):
            raise ValueError('Invalid peak ceiling')
        if not (0.001 <= self.tolerance_lu <= 0.05 and 0.02 <= self.ceiling_margin_db <= 0.5):
            raise ValueError('Invalid measurement budget')
        if not (0.1 <= self.attack_ms <= 80 and 1 <= self.release_ms <= 8000):
            raise ValueError('Invalid limiter timing')
        if self.oversample not in (4, 8) or self.tp_oversample not in (8, 16):
            raise ValueError('Oversampling not supported')
        if not isinstance(self.max_passes, int) or not 1 <= self.max_passes <= 12:
            raise ValueError('Invalid finite pass budget')
        if not 0 < self.max_gain_db <= 60:
            raise ValueError('Invalid gain budget')


def run_ffmpeg(ff: str, args: list[str]) -> None:
    command = [ff, '-y', '-nostdin', '-hide_banner', '-loglevel', 'error', '-threads', '1'] + args
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.PIPE, timeout=1800)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError('FFmpeg failed: ' + exc.stderr.decode('utf-8', 'replace')[-2500:]) from exc


def measure(path: Path, progress=None, label='RELEASE_QC', factor=8) -> dict:
    """BS.1770 loudness via existing streaming meter, plus 8x native-rate TP.

    Not a certified meter. Also retain the previous 4x estimate, taking the
    greater of the two for the engineering gate. Chunk context is 256 samples.
    """
    m = io.measure(path, progress, label)
    peak = 0.0
    with sf.SoundFile(path) as src:
        width = src.samplerate * 2
        for a in range(0, len(src), width):
            if progress:
                progress.set(label + '_TRUE_PEAK', a, len(src))
            b = min(len(src), a + width); left = max(0, a - 256); right = min(len(src), b + 256)
            src.seek(left); x = src.read(right - left, dtype='float64', always_2d=True)
            io.finite(x)
            up = signal.resample_poly(x, factor, 1, axis=0, window=('kaiser', 10.5))
            peak = max(peak, float(np.max(np.abs(up[(a-left)*factor:(b-left)*factor]))))
    m['true_peak_dbtp_4x'] = m['true_peak_dbtp_estimate']
    m['true_peak_dbtp_8x'] = float(20 * np.log10(max(peak, 1e-12)))
    m['true_peak_dbtp_estimate'] = max(m['true_peak_dbtp_4x'], m['true_peak_dbtp_8x'])
    m['tp_interpolation_factor'] = factor
    return m


def _shape(m: dict) -> tuple:
    return m['frames'], m['samplerate'], m['channels']


def quantize24(source: Path, dest: Path, gain_db: float = 0.0) -> None:
    """Deterministic TPDF at one 24-bit LSB, no dither on exact zero samples.

    Round explicitly before libsndfile conversion; no truncation bias. Refuse
    clipping rather than hiding it. Each output is finalized atomically.
    """
    tmp = dest.with_suffix('.partial.wav'); rng = np.random.default_rng(0x5044524D)
    step = 2.0 ** -23; gain = 10.0 ** (gain_db / 20)
    try:
        with sf.SoundFile(source) as src, sf.SoundFile(tmp, 'w', samplerate=src.samplerate,
                channels=src.channels, format='WAV', subtype='PCM_24') as dst:
            while True:
                x = src.read(65536, dtype='float64', always_2d=True)
                if not len(x): break
                io.finite(x); y = x * gain
                dither = (rng.random(x.shape) - rng.random(x.shape)) * step
                y = np.rint((y + np.where(x == 0, 0.0, dither)) / step) * step
                if np.max(np.abs(y)) >= 1.0:
                    raise RuntimeError('PCM24 would clip; publication refused')
                dst.write(y)
        io.sync_owned_file(tmp); os.replace(tmp, dest)
    finally:
        if tmp.exists(): tmp.unlink()


def limited_pass(source: Path, dest: Path, ff: str, drive_db: float,
                 limit_db: float, cfg: Config) -> None:
    """4x look-ahead peak control; linked channels, makeup OFF, delay corrected.

    Return to native sample rate before QC. Every trial starts from source,
    never from the previously limited trial. No hidden corrective clipping.
    """
    cfg.validate(); sr = sf.info(source).samplerate
    if abs(drive_db) > cfg.max_gain_db:
        raise RuntimeError('Requested gain exceeds the configured gain budget')
    af = (f'aformat=sample_fmts=dbl,volume={drive_db:.12f}dB:precision=double,'
          f'aresample={sr * cfg.oversample},'
          f'alimiter=limit={10**(limit_db/20):.15f}:attack={cfg.attack_ms}:'
          f'release={cfg.release_ms}:level=false:latency=true:asc=false,'
          f'aresample={sr}')
    tmp = dest.with_suffix('.partial.wav')
    try:
        run_ffmpeg(ff, ['-i', str(source), '-map_metadata', '-1', '-af', af,
                       '-c:a', 'pcm_f64le', str(tmp)])
        io.sync_owned_file(tmp); os.replace(tmp, dest)
    finally:
        if tmp.exists(): tmp.unlink()


def master_wav(source: Path, work: Path, dest: Path, ff: str, cfg: Config,
               progress=None) -> dict:
    cfg.validate(); work.mkdir(parents=True, exist_ok=True)
    baseline = measure(source, progress, 'PREMASTER', cfg.tp_oversample)
    if baseline['lufs_i'] is None:
        raise ValueError('Silent input has no finite LUFS target')
    gain = cfg.wav_lufs - baseline['lufs_i']
    if abs(gain) > cfg.max_gain_db:
        raise RuntimeError('Input requires excessive gain; no output published')
    limit = cfg.wav_tp - cfg.ceiling_margin_db
    before_peak = baseline['true_peak_dbtp_estimate'] + gain
    trials = []; bypass = before_peak <= limit
    if bypass:
        quantize24(source, dest, gain)
        met = measure(dest, progress, 'FINAL_WAV', cfg.tp_oversample)
        trials.append(dict(kind='constant_gain_only', drive_db=gain, metrics=met))
    else:
        raw = work / 'limited_float64.wav'; met = None
        for i in range(cfg.max_passes):
            if progress: progress.set('LOUDNESS_PEAK_PASS', i + 1, cfg.max_passes)
            key = dict(source_sha256=io.file_hash(source), drive_db=gain, limit_db=limit,
                       cfg=asdict(cfg), ffmpeg=io.file_hash(ff))
            marker = raw.with_suffix('.done.json')
            if not (io.valid_audio_cache(raw, marker) and io.read_json(marker).get('context') == key):
                limited_pass(source, raw, ff, gain, limit, cfg)
                io.atomic_json(marker, dict(sha256=io.file_hash(raw), context=key))
            quantize24(raw, dest)
            met = measure(dest, progress, 'WAV_PASS_QC', cfg.tp_oversample)
            if _shape(met) != _shape(baseline):
                raise RuntimeError('Limiter changed audio length/rate/channels')
            error = cfg.wav_lufs - met['lufs_i']
            excess = met['true_peak_dbtp_estimate'] - cfg.wav_tp
            trials.append(dict(kind='oversampled_lookahead', pass_index=i + 1,
                               drive_db=gain, internal_limit_db=limit, metrics=met))
            if abs(error) <= cfg.tolerance_lu and excess <= 0:
                break
            gain += error
            if excess > 0:
                limit -= excess + cfg.ceiling_margin_db
        else:
            raise RuntimeError('Cannot meet WAV LUFS and TP together within finite pass budget')
    if (met['lufs_i'] is None or abs(met['lufs_i'] - cfg.wav_lufs) > cfg.tolerance_lu or
            met['true_peak_dbtp_estimate'] > cfg.wav_tp or _shape(met) != _shape(baseline)):
        raise RuntimeError('Final PCM24 file failed target gate')
    return dict(baseline_metrics=baseline, output_metrics=met, trials=trials,
                limiter_used=not bypass, gain_db=gain,
                predicted_gain_only_tp_dbtp=before_peak,
                loudness_loss_due_to_peak_processing_lu=baseline['lufs_i'] + gain - met['lufs_i'],
                output_subtype='PCM_24', dither='deterministic_TPDF_1LSB_zero_preserving')


def mp3_from_wav(source: Path, work: Path, dest: Path, ff: str, cfg: Config,
                 progress=None) -> dict:
    """Encode delivered WAV with constant gain; decoded MP3 must reach -14.

    Codec correction adjusts that same scalar only. The WAV never changes.
    MP3 supports 44.1/48 kHz: high-rate WAVs are converted to half rate here.
    """
    cfg.validate(); work.mkdir(parents=True, exist_ok=True)
    source_hash = io.file_hash(source)
    base = measure(source, progress, 'MP3_SOURCE_WAV', cfg.tp_oversample)
    if base['lufs_i'] is None: raise ValueError('Silent WAV cannot be normalized')
    sr = base['samplerate']; mp3_sr = sr if sr <= 48000 else sr // 2
    gain = cfg.mp3_lufs - base['lufs_i']; trials = []
    decoded = work / 'mp3_decoded.wav'; tmp = dest.with_suffix('.partial.mp3')
    try:
        for i in range(4):
            if progress: progress.set('MP3_GAIN_ONLY', i + 1, 4)
            run_ffmpeg(ff, ['-i', str(source), '-map_metadata', '-1',
                '-af', f'volume={gain:.12f}dB:precision=double', '-ar', str(mp3_sr),
                '-c:a', 'libmp3lame', '-b:a', '320k', str(tmp)])
            run_ffmpeg(ff, ['-i', str(tmp), '-map_metadata', '-1', '-c:a', 'pcm_f32le', str(decoded)])
            m = measure(decoded, progress, 'DECODED_MP3_QC', cfg.tp_oversample)
            if (m['channels'] != base['channels'] or m['samplerate'] != mp3_sr or
                    abs(m['frames'] - round(base['frames'] * mp3_sr / sr)) > (0 if sr == mp3_sr else 1)):
                raise RuntimeError('MP3 changed length/rate/channels unexpectedly')
            if m['lufs_i'] is None: raise RuntimeError('Silent decoded MP3')
            error = cfg.mp3_lufs - m['lufs_i']
            trials.append(dict(pass_index=i + 1, constant_gain_db=gain, metrics=m))
            if abs(error) <= cfg.tolerance_lu:
                if m['true_peak_dbtp_estimate'] > cfg.mp3_tp:
                    raise RuntimeError('MP3 codec peak gate failed; no extra limiter or hidden level change')
                break
            gain += error
        else:
            raise RuntimeError('MP3 loudness target not met')
        if io.file_hash(source) != source_hash:
            raise RuntimeError('Delivered WAV changed during MP3 encoding')
        io.sync_owned_file(tmp); os.replace(tmp, dest)
    finally:
        if tmp.exists(): tmp.unlink()
    return dict(metrics=m, trials=trials, constant_gain_db=gain, limiter_used=False,
                encoded_from_delivered_wav_sha256=source_hash, samplerate=mp3_sr)


def run_file(source, root, *, finished=False, write_mp3=True, cfg=Config(),
             interrupt_after=None) -> tuple[dict, Path]:
    source, root = Path(source).resolve(strict=True), Path(root).resolve()
    cfg.validate()
    if root == source.parent or source.parent in root.parents or root in source.parents:
        raise ValueError('Output must be outside source directory')
    if source.suffix.lower() not in ('.wav', '.flac'):
        raise ValueError('Lossless WAV/FLAC source required, not MP3')
    info = sf.info(source)
    if info.channels != 2 or info.samplerate not in (44100, 48000, 88200, 96000) or info.duration < .5:
        raise ValueError('Stereo 44.1/48/88.2/96 kHz, at least 0.5 seconds required')
    dsp = accepted.verify_dsp(); ff = io.ffmpeg_path()
    if not ff: raise RuntimeError('Existing FFmpeg is required; nothing installed')
    source_hash = io.file_hash(source); pcm = io.pcm_hash(source)
    if (root / 'release_pcm' / (pcm + '.json')).exists() or source.name == WAV_NAME:
        raise ValueError('Already released: select the original or pre-release WAV, not this output')
    ident = dict(version=VERSION, source_sha256=source_hash, source_pcm_sha256=pcm,
        mode='finished_wav_export' if finished else 'note_sub_hftc_then_export',
        code_sha256=io.file_hash(__file__), accepted_entry_sha256=io.file_hash(accepted.__file__),
        dsp_sha256=dsp, config=asdict(cfg), ffmpeg_sha256=io.file_hash(ff),
        versions={n: importlib.metadata.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')},
        write_mp3=write_mp3)
    job = root / ('release_' + io.obj_hash(ident)[:20]); job.mkdir(parents=True, exist_ok=True)
    with io.job_lock(job / 'job.lock'), io.Progress(job) as progress:
        final = job / 'RESULT'
        if final.exists():
            report = accepted._verify_result(final, ident)
            return dict(report, rerun_status='IDEMPOTENT_SKIP'), final
        ip = job / 'identity.json'
        if ip.exists() and io.read_json(ip) != ident:
            raise RuntimeError('Job identity differs; not overwritten')
        io.atomic_json(ip, ident)
        try:
            if finished:
                premaster = source; chain_report = None
            else:
                chain_report, chain_path = accepted.run_file(source, job / 'accepted_jobs', write_mp3=False)
                premaster = chain_path / 'FINISHED.wav'
            if interrupt_after == 'chain': raise RuntimeError('TEST_INTERRUPTION_AFTER_CHAIN')
            staged = job / 'publish_staging'
            if staged.exists(): shutil.rmtree(staged)
            staged.mkdir()
            wave = master_wav(premaster, job / 'peak_work', staged / WAV_NAME, ff, cfg, progress)
            if interrupt_after == 'wav': raise RuntimeError('TEST_INTERRUPTION_AFTER_WAV')
            codec = mp3_from_wav(staged / WAV_NAME, job / 'mp3_work', staged / MP3_NAME, ff, cfg, progress) if write_mp3 else None
            if io.file_hash(source) != source_hash: raise RuntimeError('Source changed; not published')
            output_pcm = io.pcm_hash(staged / WAV_NAME)
            report = dict(version=VERSION, status='COMPLETE', identity=ident, source_name=source.name,
                source_unchanged=True, frozen_dsp_unchanged=True, production_runtime_modified=False,
                input_is_finished=finished, note_hftc_applied=not finished,
                accepted_chain_report=chain_report, premaster_sha256=io.file_hash(premaster),
                wave=wave, codec=codec, output_pcm_sha256=output_pcm,
                wav_file=WAV_NAME, mp3_file=MP3_NAME if codec else None)
            io.atomic_json(staged / 'RUN_REPORT.json', report)
            m = wave['output_metrics']
            text = (f'# 配信用仕上げ完了 — {source.name}\n\n'
                f'WAV: {m["lufs_i"]:.3f} LUFS-I / TP数値推定 {m["true_peak_dbtp_estimate"]:.3f} dBTP / PCM24。\n\n'
                f'ゲイン: {wave["gain_db"]:+.3f} dB。ピークリミッター: {wave["limiter_used"]}。\n\n'
                + (f'MP3: {codec["metrics"]["lufs_i"]:.3f} LUFS-I / '
                   f'TP数値推定 {codec["metrics"]["true_peak_dbtp_estimate"]:.3f} dBTP / 320kbps。\n\n' if codec else '')
                + 'MP3は上記完成WAVから一定ゲインのみで生成。MP3化で追加リミッターなし。\n\n'
                + ('入力は完成WAVとして扱い、Note-Sub/HFTCを再適用していません。\n\n' if finished else
                   'Note-Sub v0.2.1 → HFTC v0.1の後段にゲイン・ピーク仕上げを一度適用。\n\n')
                + '−2 dBTPは上限であり、低いピークを無理に引き上げません。測定器間の完全一致・聴感不変は保証しません。\n\n'
                + '原音は未変更。本番runtimeと採用DSPは未変更。同じ出力へ再適用しないでください。\n')
            (staged / '完了.md').write_text(text, encoding='utf-8')
            io.atomic_json(staged / 'PROOF.json', dict(identity=ident,
                files={p.name: io.file_hash(p) for p in staged.iterdir() if p.is_file()}))
            for p in staged.iterdir(): io.sync_owned_file(p)
            if final.exists(): raise RuntimeError('Result appeared during publication')
            os.rename(staged, final)
            io.atomic_json(root / 'release_pcm' / (output_pcm + '.json'), dict(version=VERSION))
            progress.set('COMPLETE', 1, 1)
            return report, final
        except Exception as exc:
            io.atomic_json(job / 'FAILURE.json', dict(error=repr(exc), traceback=traceback.format_exc(), stage=progress.state))
            raise


def main() -> int:
    p = argparse.ArgumentParser(description='WAV -12 LUFS / TP<=-2 dBTP; completed WAV -> MP3 -14 LUFS')
    p.add_argument('sources', nargs='*', type=Path)
    p.add_argument('--finished', action='store_true', help='Skip Note-Sub/HFTC; input is already finished lossless audio')
    p.add_argument('--wav-only', action='store_true'); p.add_argument('--output-root', type=Path)
    args = p.parse_args(); sources = args.sources
    if not sources:
        import tkinter as tk
        from tkinter import filedialog
        app = tk.Tk(); app.withdraw()
        try:
            title = '完成WAVを選択（音作りは再適用せず音圧仕上げのみ）' if args.finished else 'Note-Sub/HFTC適用前のWAV/FLACを選択'
            sources = [Path(n) for n in filedialog.askopenfilenames(title=title, filetypes=[('Lossless audio', '*.wav *.flac')])]
        finally: app.destroy()
    if not sources: return 0
    root = args.output_root or Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'release_finish_v1_1'
    root.mkdir(parents=True, exist_ok=True); rows = []; failures = 0
    for i, source in enumerate(sources, 1):
        print(f'[{i}/{len(sources)}] {source.name}', flush=True)
        try:
            report, out = run_file(source, root, finished=args.finished, write_mp3=not args.wav_only)
            rows.append(f'- {source.name}: 完了 {out}'); print('完了:', out, flush=True)
        except Exception as exc:
            failures += 1; rows.append(f'- {source.name}: 未出力 {exc}'); print('未出力:', str(exc), flush=True)
    (root / 'LAST_RUN.md').write_text('# 配信用書き出し結果\n\n'+'\n'.join(rows)+'\n', encoding='utf-8')
    print('結果一覧:', root / 'LAST_RUN.md', flush=True)
    if os.name == 'nt':
        try: os.startfile(str(root))
        except OSError: pass
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
