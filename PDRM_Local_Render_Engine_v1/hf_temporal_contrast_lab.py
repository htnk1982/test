"""HFTC v0.1: isolated offline high-frequency temporal-contrast experiment.

Never modifies the source, Note-Sub, or production runtime. No source separation,
no claim of semantic hat/consonant protection, no automatic quality approval.
The branch gain is bounded; time-varying band processing is not an ideal brickwall.
"""
from __future__ import annotations
import os
for _name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
    os.environ.setdefault(_name, '1')
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import importlib.metadata
import math
import secrets
import shutil
import zipfile
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import convolve1d, maximum_filter1d, percentile_filter, uniform_filter1d
import note_sub_lab as io  # Read-only reuse of isolated I/O/QC helpers; NO monkeypatch.

VERSION = 'hftc-lab-0.1.0'
KNOWN_B = 'c244ad14170ac4054f9564d7a20a7b3fbcca26991b8c611888c71f42da84d329'


@dataclass(frozen=True)
class Config:
    max_cut_db: float = 1.0
    low_hz: float = 8300.0
    high_hz: float = 15700.0
    fir_seconds: float = 0.020
    grid_seconds: float = 0.005
    envelope_seconds: float = 0.020
    fast_seconds: float = 0.005
    context_seconds: float = 2.0
    protect_below_p90_db: float = 3.0
    onset_rise_db: float = 6.0
    guard_seconds: float = 0.030
    smooth_seconds: float = 0.060
    chunk_seconds: float = 8.0
    pcm_ceiling_dbtp: float = -1.5
    codec_ceiling_dbtp: float = -1.0
    max_match_gain_db: float = 0.10

    def validate(self, sr: int) -> None:
        if not all(math.isfinite(v) for v in asdict(self).values()):
            raise ValueError('Non-finite configuration')
        if sr not in (44100, 48000, 88200, 96000):
            raise ValueError('Supported rates: 44.1/48/88.2/96 kHz')
        if not 0 <= self.max_cut_db <= 1 or not 8000 <= self.low_hz < self.high_hz <= 16000:
            raise ValueError('Scope is 8-16 kHz, at most 1 dB branch attenuation')
        if min(self.fir_seconds, self.grid_seconds, self.envelope_seconds,
               self.fast_seconds, self.context_seconds, self.smooth_seconds,
               self.chunk_seconds) <= 0 or self.guard_seconds < 0:
            raise ValueError('Invalid time constants')
        if not 0 < self.protect_below_p90_db < 20 or self.onset_rise_db <= 0:
            raise ValueError('Invalid detector thresholds')
        if self.max_match_gain_db < 0:
            raise ValueError('Invalid matching budget')


def coefficients(sr: int, cfg: Config) -> np.ndarray:
    cfg.validate(sr)
    taps = max(3, int(round(cfg.fir_seconds * sr)) | 1)
    return signal.firwin(taps, [cfg.low_hz, cfg.high_hz], pass_zero=False,
                         window=('kaiser', 10.5), fs=sr)


def extract_band(x: np.ndarray, taps: np.ndarray) -> np.ndarray:
    """Centered FIR (integer delay compensated), same length, no channel mixing."""
    x = np.asarray(x, dtype=np.float64)
    if x.ndim != 2 or x.shape[1] != 2 or len(x) == 0:
        raise ValueError('Nonempty stereo array required')
    io.finite(x)
    return signal.oaconvolve(x, taps[:, None], mode='same', axes=0)


def plan_gain(power: np.ndarray, fast: np.ndarray, full: np.ndarray,
              dt: float, cfg: Config) -> tuple[np.ndarray, dict]:
    """Stereo-linked, centered finite-context control. Constant HF is a no-op.

    Protect strong-energy/onset *evidence*, not instrument identities. A compact
    smoothing kernel cannot bleed attenuation into the interior of guard zones.
    """
    power, fast, full = (np.asarray(v, dtype=np.float64) for v in (power, fast, full))
    if not len(power) or power.shape != fast.shape or power.shape != full.shape:
        raise ValueError('Envelope lengths must match')
    if dt <= 0 or not math.isfinite(dt):
        raise ValueError('Invalid control interval')
    for v in (power, fast, full):
        io.finite(v)
        if np.any(v < 0):
            raise ValueError('Power cannot be negative')
    level = 10 * np.log10(np.maximum(power, 1e-24))
    fast_db = 10 * np.log10(np.maximum(fast, 1e-24))
    context = max(3, int(round(cfg.context_seconds / dt)) | 1)
    p90 = percentile_filter(level, 90, size=context, mode='nearest')
    p50 = percentile_filter(level, 50, size=context, mode='nearest')
    presence = (power > np.maximum(full * 1e-6, 1e-14)) & (full > 1e-14)
    depth = cfg.max_cut_db * io.smoother(
        (p90 - level - cfg.protect_below_p90_db) /
        np.maximum(p90 - p50 - cfg.protect_below_p90_db, 3.0))
    depth[~presence] = 0.0
    lag = max(1, int(round(.040 / dt)))
    previous = np.r_[np.full(lag, fast_db[0]), fast_db][0:len(fast_db)]
    onset = (fast_db - previous >= cfg.onset_rise_db) & (fast_db >= p90 - 12) & presence
    strong = (level >= p90 - cfg.protect_below_p90_db) & presence
    protected = strong | onset | ~presence
    radius = max(1, int(round(cfg.smooth_seconds / dt / 2)))
    guard = int(math.ceil(cfg.guard_seconds / dt))
    expanded = maximum_filter1d(protected.astype(np.uint8),
        size=2 * (radius + guard) + 1, mode='nearest').astype(bool)
    depth[expanded] = 0.0
    depth[:guard + radius + 1] = 0.0
    depth[-guard - radius - 1:] = 0.0
    kernel = np.hanning(2 * radius + 1)
    depth = convolve1d(depth, kernel / np.sum(kernel), mode='nearest')
    depth = np.clip(depth, 0.0, cfg.max_cut_db)
    # Preserve a clean start/end; interpolation cannot introduce a boundary step.
    depth[:guard + 1] = 0.0
    depth[-guard - 1:] = 0.0
    gain = 10 ** (-depth / 20)
    return gain, dict(max_cut_db=float(np.max(depth)), mean_cut_db=float(np.mean(depth)),
        control_fraction_over_0_05db=float(np.mean(depth > .05)),
        protected_points=int(np.sum(protected)),
        protected_max_cut_db=float(np.max(depth[protected])) if np.any(protected) else 0.0,
        control_interval_seconds=dt, scope='Heuristic energy/onset protection, not semantic separation')


def analyze_control(source: Path, cfg: Config, progress=None) -> tuple[np.ndarray, np.ndarray, dict]:
    info = sf.info(source)
    taps = coefficients(info.samplerate, cfg)
    sr = info.samplerate
    step = max(1, int(round(sr * cfg.grid_seconds)))
    centers = np.arange(0, info.frames, step, dtype=np.int64)
    power, fast, full = (np.empty(len(centers)) for _ in range(3))
    win = max(1, int(round(cfg.envelope_seconds * sr)))
    fw = max(1, int(round(cfg.fast_seconds * sr)))
    pad = len(taps) // 2 + max(win, fw) + 2
    width = max(1, int(round(cfg.chunk_seconds * sr)))
    with sf.SoundFile(source) as f:
        for start in range(0, info.frames, width):
            end = min(info.frames, start + width)
            a, b = max(0, start - pad), min(info.frames, end + pad)
            f.seek(a)
            x = f.read(b - a, dtype='float64', always_2d=True)
            band = extract_band(x, taps)
            bp = np.mean(band * band, axis=1)
            xp = np.mean(x * x, axis=1)
            sel = (centers >= start) & (centers < end)
            idx = centers[sel] - a
            power[sel] = np.maximum(uniform_filter1d(bp, win, mode='constant')[idx], 0)
            fast[sel] = np.maximum(uniform_filter1d(bp, fw, mode='constant')[idx], 0)
            full[sel] = np.maximum(uniform_filter1d(xp, win, mode='constant')[idx], 0)
            if progress:
                progress.set('HFTC_ANALYZE', end, info.frames)
    gain, stats = plan_gain(power, fast, full, step / sr, cfg)
    return centers / sr, gain, stats


def render_raw(source: Path, job: Path, times: np.ndarray, gain: np.ndarray,
               cfg: Config, progress=None, interrupt_after=None) -> tuple[Path, dict]:
    """Restartable chunks use one global control curve and FIR context padding."""
    info = sf.info(source)
    sr = info.samplerate
    taps = coefficients(sr, cfg)
    pad = len(taps) // 2
    width = max(1, int(round(sr * cfg.chunk_seconds)))
    job.mkdir(parents=True, exist_ok=True)
    context = io.obj_hash(dict(source=io.file_hash(source), config=asdict(cfg),
        times=np.asarray(times).tolist(), gains=np.asarray(gain).tolist(),
        code=io.file_hash(__file__)))
    chunks = job / ('chunks_' + context[:16])
    chunks.mkdir(exist_ok=True)
    paths, computed, reused = [], 0, 0
    with sf.SoundFile(source) as f:
        for i, start in enumerate(range(0, info.frames, width)):
            end = min(info.frames, start + width)
            out = chunks / f'{i:05d}.wav'
            marker = out.with_suffix('.json')
            if io.valid_audio_cache(out, marker):
                reused += 1
            else:
                a, b = max(0, start - pad), min(info.frames, end + pad)
                f.seek(a)
                x = f.read(b - a, dtype='float64', always_2d=True)
                io.finite(x)
                dry = x[start - a:end - a]
                band = extract_band(x, taps)[start - a:end - a]
                t = np.arange(start, end, dtype=np.float64) / sr
                g = np.interp(t, times, gain)
                delta = (g - 1)[:, None] * band
                # Do not spread FIR tails into exact digital silence.
                delta[np.all(dry == 0.0, axis=1)] = 0.0
                y = dry + delta
                io.finite(y)
                io.atomic_wav(out, y, sr, 'FLOAT')
                io.atomic_json(marker, {'sha256': io.file_hash(out)})
                computed += 1
                if interrupt_after is not None and computed >= interrupt_after:
                    raise RuntimeError('TEST_INTERRUPTION_AFTER_HFTC_CHUNK')
            paths.append(out)
            if progress:
                progress.set('HFTC_RENDER', end, info.frames)
    raw = job / ('raw_' + context[:16] + '.wav')
    temp = raw.with_suffix('.partial.wav')
    with sf.SoundFile(temp, 'w', samplerate=sr, channels=2, format='WAV', subtype='FLOAT') as dst:
        for p in paths:
            with sf.SoundFile(p) as src:
                for x in src.blocks(blocksize=65536, dtype='float32', always_2d=True):
                    dst.write(x)
    io.sync_owned_file(temp)
    os.replace(temp, raw)
    return raw, dict(computed_chunks=computed, reused_chunks=reused)


def write_scaled(source: Path, dest: Path, gain: float) -> None:
    with sf.SoundFile(source) as src, sf.SoundFile(dest, 'w', samplerate=src.samplerate,
            channels=src.channels, format='WAV', subtype='FLOAT') as dst:
        for x in src.blocks(blocksize=65536, dtype='float64', always_2d=True):
            dst.write(x * gain)
    io.sync_owned_file(dest)


def run_job(source, root, cfg=Config(), *, expected_hash=KNOWN_B, write_mp3=True):
    source, root = Path(source).resolve(), Path(root).resolve()
    if root == source.parent or source.parent in root.parents:
        raise ValueError('Output must be outside the source directory')
    info = sf.info(source)
    cfg.validate(info.samplerate)
    if source.suffix.lower() != '.wav' or info.channels != 2 or info.duration < .5:
        raise ValueError('Stereo WAV of at least 0.5 seconds required')
    h = io.file_hash(source)
    if expected_hash is not None and h != expected_hash:
        raise ValueError('Select the accepted SUB_AUGMENTED.wav, not C or another processed copy')
    ff = io.ffmpeg_path() if write_mp3 else None
    if write_mp3 and not ff:
        raise RuntimeError('ffmpeg unavailable; nothing installed')
    ident = dict(version=VERSION, input_sha256=h, config=asdict(cfg),
        code_sha256=io.file_hash(__file__), io_sha256=io.file_hash(io.__file__),
        versions={n: importlib.metadata.version(n) for n in ('numpy', 'scipy', 'soundfile', 'pyloudnorm')},
        ffmpeg_sha256=io.file_hash(ff) if ff else None, write_mp3=write_mp3)
    job = root / ('hftc_' + io.obj_hash(ident)[:20])
    job.mkdir(parents=True, exist_ok=True)
    with io.job_lock(job / 'job.lock'), io.Progress(job) as progress:
        final = job / 'RESULT'
        if final.exists():
            proof = final / 'PROOF.json'
            if not proof.is_file():
                raise RuntimeError('Foreign RESULT; nothing overwritten')
            saved = io.read_json(proof)
            if saved.get('identity') != ident:
                raise RuntimeError('Foreign RESULT identity')
            for name, sha in saved['files'].items():
                if io.file_hash(final / name) != sha:
                    raise RuntimeError('Result modified: ' + name)
            return io.read_json(final / 'HFTC_REPORT.json'), final
        base = io.measure(source, progress, 'HFTC_BASELINE')
        if base['lufs_i'] is None or abs(base['lufs_i'] + 14) > .10:
            raise ValueError('Use the already level-matched -14 LUFS baseline')
        if base['true_peak_dbtp_estimate'] > cfg.pcm_ceiling_dbtp:
            raise ValueError('Baseline peak exceeds limit; no limiter will be added')
        times, gain, stats = analyze_control(source, cfg, progress)
        raw, cache = render_raw(source, job, times, gain, cfg, progress)
        raw_metrics = io.measure(raw, progress, 'HFTC_RAW_QC')
        gain_db = base['lufs_i'] - raw_metrics['lufs_i']
        if abs(gain_db) > cfg.max_match_gain_db:
            raise RuntimeError('Matching budget exceeded; no trial published')
        staged = job / 'staging'
        if staged.exists():
            shutil.rmtree(staged)
        staged.mkdir()
        shutil.copyfile(source, staged / 'CONTROL_B.wav')
        write_scaled(raw, staged / 'HFTC_CANDIDATE.wav', 10 ** (gain_db / 20))
        candidate = io.measure(staged / 'HFTC_CANDIDATE.wav', progress, 'HFTC_FINAL_QC')
        if candidate['true_peak_dbtp_estimate'] > cfg.pcm_ceiling_dbtp or abs(candidate['lufs_i'] - base['lufs_i']) > .01:
            raise RuntimeError('PCM peak/level gate failed; no trial published')
        mapping_path = job / 'private_blind_mapping.json'
        if mapping_path.exists():
            mapping = io.read_json(mapping_path)
        else:
            names = ['CONTROL_B', 'HFTC_CANDIDATE']
            if secrets.randbelow(2):
                names.reverse()
            mapping = dict(zip(('X', 'Y'), names))
            io.atomic_json(mapping_path, mapping)
        codecs = {}
        if ff:
            blind = staged / 'BLIND_TEST'
            blind.mkdir()
            for letter, name in mapping.items():
                io.codec_file(ff, staged / (name + '.wav'), blind / f'HFTC_{letter}_320kbps.mp3')
                decoded = job / (name + '_decoded.wav')
                io.codec_file(ff, blind / f'HFTC_{letter}_320kbps.mp3', decoded, True)
                m = io.measure(decoded, progress, 'HFTC_CODEC_QC')
                if m['frames'] != info.frames or m['samplerate'] != info.samplerate:
                    raise RuntimeError('MP3 decoded alignment/length changed')
                codecs[name] = m
            levels = [v['lufs_i'] for v in codecs.values()]
            if any(v is None for v in levels) or max(levels) - min(levels) > .10 or any(v['true_peak_dbtp_estimate'] > cfg.codec_ceiling_dbtp for v in codecs.values()):
                raise RuntimeError('MP3 peak/level gate failed; no trial published')
            with zipfile.ZipFile(staged / 'PDRM_HFTC_v01_BLIND_MP3.zip', 'w', zipfile.ZIP_STORED) as z:
                for p in sorted(blind.glob('*.mp3')):
                    z.write(p, p.name)
        (staged / 'REVEAL_AFTER_LISTENING.txt').write_text('\n'.join(f'{k} = {v}' for k, v in mapping.items()) + '\n', encoding='utf-8')
        if io.file_hash(source) != h or io.file_hash(staged / 'CONTROL_B.wav') != h:
            raise RuntimeError('Input/control fingerprint changed')
        report = dict(status='RENDERED_EXPERIMENT_NOT_QUALITY_APPROVAL', identity=ident,
            source_unchanged=True, baseline_metrics=base, raw_metrics=raw_metrics,
            candidate_metrics=candidate, normalization_gain_db=gain_db,
            control_stats=stats, cache=cache, codec=codecs,
            limits=['No instrument identification; semantic attack protection not proven.',
                    'FIR transitions and gain modulation have finite leakage.',
                    'Matching gain acts on all bands, though DSP targets 8-16 kHz.',
                    'Reference contrast gap is not a defect diagnosis or target.',
                    'Previous B preference does not identify its causal mechanism.',
                    'A one-dB branch ceiling cannot close a six-to-seven-dB reference contrast gap.'])
        io.atomic_json(staged / 'HFTC_REPORT.json', report)
        hashes = {str(p.relative_to(staged)).replace('\\', '/'): io.file_hash(p)
                  for p in staged.rglob('*') if p.is_file()}
        io.atomic_json(staged / 'PROOF.json', dict(identity=ident, files=hashes))
        if final.exists():
            raise RuntimeError('RESULT appeared; nothing overwritten')
        os.rename(staged, final)
        progress.set('COMPLETE', 1, 1)
        return report, final


def main():
    parser = argparse.ArgumentParser(description='HFTC: one isolated trial on the accepted B')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args()
    source = args.source
    if source is None:
        import tkinter as tk
        from tkinter import filedialog
        app = tk.Tk(); app.withdraw()
        name = filedialog.askopenfilename(title='Select accepted SUB_AUGMENTED.wav', filetypes=[('WAV', '*.wav')])
        app.destroy()
        if not name:
            return
        source = Path(name)
    root = args.output_root or Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'hftc_lab'
    report, result = run_job(source, root)
    print(report['status']); print(result)


if __name__ == '__main__':
    main()
