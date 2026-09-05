"""Versioned peak protection: oversampled FFmpeg alimiter plus measured LUFS fit.

No silent fallback to a lower loudness. Every iteration reads the SAME input;
limited output is never fed back into the limiter. True peak is a numerical
4x/8x estimate, not a certified analogue reconstruction bound.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import math
import os
import subprocess
import time
import numpy as np
import soundfile as sf
from scipy import signal
import note_sub_lab as io
import hf_temporal_contrast_lab as hf

VERSION = 'distribution-peak-1.0.0'

@dataclass(frozen=True)
class PeakConfig:
    oversample: int = 4
    attack_ms: float = 5.0
    release_ms: float = 80.0
    asc_level: float = 0.5
    ceiling_margin_db: float = 0.20
    max_iterations: int = 8
    max_drive_db: float = 36.0

    def validate(self):
        if self.oversample != 4 or not 0.1 <= self.attack_ms <= 80:
            raise ValueError('Invalid oversampling or attack')
        if not 1 <= self.release_ms <= 8000 or not 0 <= self.asc_level <= 1:
            raise ValueError('Invalid release configuration')
        if not 0.02 <= self.ceiling_margin_db <= 1 or not 1 <= self.max_iterations <= 12:
            raise ValueError('Invalid limiter solver budget')
        if not 0 < self.max_drive_db <= 60:
            raise ValueError('Invalid drive budget')
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Non-finite configuration')


def execute(ff: str, arguments: list[str], log: Path, progress=None, stage='FFMPEG'):
    """No shell. Poll cancellation; retain a bounded-error log. Kill on exit."""
    log.parent.mkdir(parents=True, exist_ok=True)
    command = [str(ff), '-nostdin', '-hide_banner', '-loglevel', 'error', '-y'] + arguments
    with log.open('wb') as err:
        child = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=err)
        start = time.monotonic()
        try:
            while child.poll() is None:
                if progress:
                    progress.set(stage)
                if time.monotonic() - start > 1800:
                    raise TimeoutError('Encoder/limiter exceeded 1800 seconds')
                time.sleep(.1)
            if child.returncode:
                detail = log.read_text(encoding='utf-8', errors='replace')[-3000:]
                raise RuntimeError(f'{stage} failed ({child.returncode}): {detail}')
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=10)


def check_ffmpeg(ff: str):
    p = subprocess.run([ff, '-hide_banner', '-h', 'filter=alimiter'],
                       capture_output=True, text=True, timeout=20)
    text = p.stdout + p.stderr
    if p.returncode or not all(k in text for k in ('latency', 'level', 'asc_level')):
        raise RuntimeError('Existing FFmpeg lacks required alimiter options; no installation attempted')


def measure(path: Path, progress=None, label='LEVEL_TP_QC') -> dict:
    m = io.measure(path, progress, label)
    peak = 0.0
    with sf.SoundFile(path) as f:
        sr = f.samplerate
        for a in range(0, f.frames, 2 * sr):
            b = min(f.frames, a + 2 * sr)
            left, right = max(0, a - 256), min(f.frames, b + 256)
            f.seek(left)
            x = f.read(right - left, dtype='float64', always_2d=True)
            io.finite(x)
            up = signal.resample_poly(x, 8, 1, axis=0, window=('kaiser', 10.5))
            peak = max(peak, float(np.max(np.abs(up[(a-left)*8:(b-left)*8]))))
            if progress:
                progress.set(label + '_8X', b, f.frames)
    m['true_peak_8x_dbtp_estimate'] = float(20 * np.log10(max(peak, 1e-12)))
    m['true_peak_max_dbtp_estimate'] = max(m['true_peak_dbtp_estimate'], m['true_peak_8x_dbtp_estimate'])
    return m


def render_limited(source: Path, dest: Path, gain_db: float, limit_db: float,
                   ff: str, cfg=PeakConfig(), progress=None):
    cfg.validate()
    if not math.isfinite(gain_db) or abs(gain_db) > 80 or not -24 <= limit_db <= 0:
        raise ValueError('Invalid limiter level')
    info = sf.info(source)
    rate = info.samplerate
    limit = 10 ** (limit_db / 20)
    # Explicitly disable alimiter's default makeup-to-0dB. Compensate lookahead
    # delay and flush its EOF buffer. Finite-rate oversampling is checked after SRC.
    filters = (f'volume={gain_db:.12f}dB:precision=double,'
               f'aresample={rate*cfg.oversample}:filter_size=64:cutoff=0.98,'
               f'alimiter=limit={limit:.14f}:attack={cfg.attack_ms}:release={cfg.release_ms}:'
               f'asc=1:asc_level={cfg.asc_level}:level=0:latency=1,'
               f'aresample={rate}:filter_size=64:cutoff=0.98')
    temp = dest.with_suffix('.partial.wav')
    execute(ff, ['-i', str(source), '-map', '0:a:0', '-map_metadata', '-1',
                 '-af', filters, '-c:a', 'pcm_f32le', str(temp)],
            dest.with_suffix('.ffmpeg.log'), progress, 'PEAK_RENDER')
    shape = sf.info(temp)
    if (shape.frames, shape.channels, shape.samplerate) != (info.frames, info.channels, rate):
        raise RuntimeError('Limiter changed length/channels/rate; refusing to pad or trim silently')
    io.sync_owned_file(temp)
    os.replace(temp, dest)


def fit(source: Path, dest: Path, work: Path, target: float, ceiling: float,
        ff: str, progress=None, cfg=PeakConfig()) -> dict:
    cfg.validate()
    if not math.isfinite(target) or not -30 <= target <= -8 or not -12 <= ceiling <= -1:
        raise ValueError('Unsupported loudness/peak target')
    work.mkdir(parents=True, exist_ok=True)
    ident = dict(source=io.file_hash(source), version=VERSION, code=io.file_hash(__file__),
                 ffmpeg=io.file_hash(ff), target=target, ceiling=ceiling, config=asdict(cfg))
    marker = dest.with_suffix('.peak.json')
    if dest.exists() and marker.exists():
        saved = io.read_json(marker)
        if saved.get('identity') == ident and saved.get('sha256') == io.file_hash(dest):
            return saved['report']
    base = measure(source, progress, 'PEAK_INPUT')
    if base['lufs_i'] is None:
        raise ValueError('Silent audio has no finite LUFS target')
    gain_db = target - base['lufs_i']
    tp = base['true_peak_max_dbtp_estimate']
    trials = []
    if tp + gain_db <= ceiling - .02:
        hf.write_scaled(source, dest, 10 ** (gain_db / 20))
        final = measure(dest, progress, 'GAIN_ONLY_QC')
        report = dict(limiter_engaged=False, input_gain_db=gain_db, correction_gain_db=0.0,
                      baseline_metrics=base, output_metrics=final, trials=trials,
                      target_lufs=target, ceiling_dbtp=ceiling, config=asdict(cfg))
    else:
        limit_db = ceiling - cfg.ceiling_margin_db
        report = None
        for i in range(cfg.max_iterations):
            if gain_db > cfg.max_drive_db:
                raise RuntimeError('Loudness target requires excessive drive; no mislabeled output published')
            raw = work / f'limited_{i:02d}.wav'
            render_limited(source, raw, gain_db, limit_db, ff, cfg, progress)
            m = measure(raw, progress, 'LIMITED_QC')
            if m['lufs_i'] is None:
                raise RuntimeError('Limiter returned silent audio')
            correction = target - m['lufs_i']
            predicted_peak = m['true_peak_max_dbtp_estimate'] + correction
            trials.append(dict(iteration=i, input_gain_db=gain_db, limit_db=limit_db,
                               correction_gain_db=correction, metrics=m))
            if predicted_peak <= ceiling - .015:
                hf.write_scaled(raw, dest, 10 ** (correction / 20))
                final = measure(dest, progress, 'FITTED_QC')
                report = dict(limiter_engaged=True, input_gain_db=gain_db,
                              correction_gain_db=correction, baseline_metrics=base,
                              output_metrics=final, trials=trials, config=asdict(cfg),
                              target_lufs=target, ceiling_dbtp=ceiling)
                break
            # More input drive compensates loudness lost to peak reduction.
            # If SRC overshoot itself dominates, lower the internal limiter cap.
            gain_db += max(.05, correction)
            overshoot = m['true_peak_max_dbtp_estimate'] - limit_db
            if overshoot > cfg.ceiling_margin_db:
                limit_db -= min(.5, overshoot - cfg.ceiling_margin_db + .05)
        if report is None:
            raise RuntimeError('LUFS/TP fit did not converge; no lower-level substitute published')
    m = report['output_metrics']
    if abs(m['lufs_i'] - target) > .03 or m['true_peak_max_dbtp_estimate'] > ceiling:
        raise RuntimeError('Final loudness/true-peak gate failed')
    io.atomic_json(marker, dict(identity=ident, sha256=io.file_hash(dest), report=report))
    return report
