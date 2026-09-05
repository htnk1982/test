"""PDRM Note-Sub Lab v0.2: separated note tracking, target selection, amount control and rendering.

This module deliberately layers on the isolated v0.1.1 lab infrastructure.  It does
not import or modify pdrm_engine, pdrm_runtime, pdrm_operator_lab, the accepted C,
or any production DSP.  v0.2 changes only the experimental note-sub analysis and
synthesis path.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from scipy import signal

import note_sub_lab as _v011

VERSION = 'note-sub-lab-0.2.1'
EPS = _v011.EPS
CONFIG = dict(_v011.CONFIG)
CONFIG.update(
    track_octave_tolerance_cents=40.0,
    transient_low_only_periodicity_min=0.94,
    reattack_drop_db=8.0,
    reattack_rise_db=8.0,
    adaptive_fade_fraction=0.25,
)

# Stable infrastructure remains delegated to the isolated v0.1.1 lab.
file_hash = _v011.file_hash
pcm_hash = _v011.pcm_hash
obj_hash = _v011.obj_hash
read_json = _v011.read_json
atomic_json = _v011.atomic_json
atomic_wav = _v011.atomic_wav
job_lock = _v011.job_lock
Progress = _v011.Progress
finite = _v011.finite
cents = _v011.cents
nsdf_pitch = _v011.nsdf_pitch
component = _v011.component
read_analysis = _v011.read_analysis
smoother = _v011.smoother
measure = _v011.measure
valid_audio_cache = _v011.valid_audio_cache
ffmpeg_path = _v011.ffmpeg_path
codec_file = _v011.codec_file
validate_manifest = _v011.validate_manifest


def select_generation_target(f0):
    """Map a tracked pitch to the one-octave-limited sub target.

    Target choice is intentionally independent of note lifetime and addition
    amount.  An f0 octave interpretation may change while this target stays the
    same; that alone must not terminate a note.
    """
    if f0 is None:
        return None
    f0 = float(f0)
    if CONFIG['min_sub_hz'] <= f0 <= CONFIG['max_sub_hz']:
        return f0
    lower = f0 / 2.0
    return lower if CONFIG['min_sub_hz'] <= lower <= CONFIG['max_sub_hz'] else None


# Backward-compatible public name used by the v0.1.1 tests and callers.
sub_frequency = select_generation_target


def _octave_equivalent(a, b):
    if a is None or b is None or a <= 0 or b <= 0:
        return False
    return abs(cents(float(a), float(b)) - 1200.0) <= CONFIG['track_octave_tolerance_cents']


def analyze_pitch_observation(wide, low, stereo, t):
    """Return note-tracking evidence only; do not decide whether to add sub."""
    out = {
        'time': float(t),
        'track_state': 'UNKNOWN',
        'track_reason': 'uncertain',
        'boundary_evidence': False,
        'amplitude': 0.0,
        'state': 'ABSTAIN',
        'reason': 'uncertain',
    }
    stereo = np.asarray(stereo, dtype=np.float64)
    wide = np.asarray(wide, dtype=np.float64)
    low = np.asarray(low, dtype=np.float64)
    rms = float(np.sqrt(np.mean(stereo * stereo)))
    out['source_rms'] = rms
    if rms < 1e-5:
        out.update(track_state='SILENCE', track_reason='silence', reason='silence')
        return out

    wide_power = float(np.mean(wide * wide))
    stereo_power = float(np.mean(stereo * stereo))
    low_power = float(np.mean(low * low))
    if wide_power < 0.04 * stereo_power:
        out.update(track_reason='no_centered_low_tonal_evidence',
                   reason='no_centered_low_tonal_evidence')
        return out

    q = np.array([np.mean(v * v) for v in np.array_split(wide, 4)])
    qdb = 10 * np.log10(np.maximum(q, EPS))
    qrange = float(np.max(qdb) - np.min(qdb))
    out['quarter_range_db'] = qrange
    out['boundary_evidence'] = qrange > CONFIG['max_quarter_range_db']

    fw, pw = nsdf_pitch(wide)
    fl, pl = nsdf_pitch(low)
    out.update(periodicity=float(pw), low_periodicity=float(pl))
    if fl is None or pl < CONFIG['low_periodicity_min']:
        out.update(track_reason='weak_periodicity', reason='weak_periodicity')
        return out

    wide_good = fw is not None and pw >= CONFIG['periodicity_min']
    pitch_relation = 'low_only'
    if wide_good:
        if cents(float(fw), float(fl)) <= CONFIG['agreement_cents']:
            f0 = float(fl)
            pitch_relation = 'views_agree'
        elif _octave_equivalent(fw, fl):
            f0 = float(min(fw, fl))
            pitch_relation = 'octave_ambiguous_views'
        else:
            out.update(track_reason='pitch_views_disagree',
                       reason='pitch_views_disagree',
                       wide_f0_hz=float(fw), low_f0_hz=float(fl))
            return out
    elif out['boundary_evidence'] and pl >= CONFIG['transient_low_only_periodicity_min']:
        # A short broadband hit may corrupt the wide view while the low tonal
        # trajectory remains strong. Keep it as tracking evidence, not as a
        # permission to synthesize blindly.
        f0 = float(fl)
        pitch_relation = 'low_view_during_transient'
    else:
        out.update(track_reason='weak_periodicity', reason='weak_periodicity')
        return out

    harmonics = [(h, component(wide, f0 * h, CONFIG['analysis_sr'])[0])
                 for h in range(1, 7) if f0 * h < 740]
    if not harmonics:
        out.update(track_reason='insufficient_harmonic_evidence',
                   reason='insufficient_harmonic_evidence')
        return out
    amps = np.array([a for _, a in harmonics], dtype=np.float64)
    largest = float(np.max(amps))
    support = int(np.count_nonzero(amps >= largest * CONFIG['harmonic_support_ratio']))
    wide_fit = float(min(1.0, np.sum(amps * amps / 2.0) / max(wide_power, EPS)))

    low_amps = np.array([
        component(low, f0 * h, CONFIG['analysis_sr'])[0]
        for h in range(1, 7) if f0 * h < 250
    ], dtype=np.float64)
    low_fit = (float(min(1.0, np.sum(low_amps * low_amps / 2.0) /
                         max(low_power, EPS))) if len(low_amps) else 0.0)
    fit = max(wide_fit, low_fit)
    tonal_strength = float(math.sqrt(max(np.sum(amps * amps / 2.0), 0.0)))
    out.update(
        f0_hz=f0,
        pitch_relation=pitch_relation,
        harmonic_support=support,
        harmonic_fraction=fit,
        reference_partial_amplitude=largest,
        tonal_strength=tonal_strength,
    )
    # A single sinusoid is still ambiguous between bass and a tonal drum.
    if support < CONFIG['min_harmonics'] or fit < CONFIG['harmonic_fraction_min']:
        out.update(track_reason='insufficient_harmonic_evidence',
                   reason='insufficient_harmonic_evidence')
        return out

    out.update(track_state='TRACK', track_reason='tonal_candidate')
    return out


def decide_addition_amount(observation, stereo, sub):
    """Choose target and amount without changing note-tracking state."""
    out = dict(observation)
    if out.get('track_state') != 'TRACK':
        return out

    target = select_generation_target(out.get('f0_hz'))
    if target is None:
        out.update(target_state='UNAVAILABLE', state='ABSTAIN',
                   reason='outside_single_octave_sub_range', amplitude=0.0)
        return out

    stereo = np.asarray(stereo, dtype=np.float64)
    sub = np.asarray(sub, dtype=np.float64)
    rms = float(out.get('source_rms', np.sqrt(np.mean(stereo * stereo))))
    existing, _ = component(np.mean(stereo, axis=1), target, CONFIG['analysis_sr'])
    reference = float(out.get('reference_partial_amplitude', 0.0))
    desired = min(reference * CONFIG['desired_partial_ratio'],
                  CONFIG['max_added_peak'],
                  rms * CONFIG['max_relative_peak'])
    sub_rms = float(np.sqrt(np.mean(sub * sub)))
    out.update(
        target_state='SELECTED',
        sub_hz=float(target),
        existing_target_amplitude=float(existing),
        existing_sub_rms=sub_rms,
        desired_amplitude=float(desired),
    )

    if existing >= desired * CONFIG['already_full_ratio'] or sub_rms >= desired / math.sqrt(2):
        out.update(amount_state='ZERO_SUFFICIENT', state='KEEP',
                   reason='existing_low_end_sufficient', amplitude=0.0)
        return out

    amount = min(max(0.0, desired - existing), CONFIG['max_added_peak'])
    if amount < 1e-5:
        out.update(amount_state='ZERO_NEGLIGIBLE', state='KEEP',
                   reason='negligible_addition', amplitude=0.0)
        return out

    out.update(
        amount_state='ADD',
        state='REINFORCE' if existing > desired * 0.20 else 'SYNTHESIZE',
        reason='eligible_tonal_interval',
        amplitude=float(amount),
    )
    return out


def analyze_frame(wide, low, stereo, sub, t):
    observation = analyze_pitch_observation(wide, low, stereo, t)
    return decide_addition_amount(observation, stereo, sub)


def collect_frames(path, job, progress, interrupt_after=None):
    """Analyze frames with v0.2 tracking evidence while retaining v0.1.1 cache semantics."""
    info = _v011.sf.info(path)
    chunk = CONFIG['analysis_chunk_seconds']
    sr = CONFIG['analysis_sr']
    hop = CONFIG['hop_seconds']
    half = int(round(CONFIG['frame_seconds'] * sr)) // 2
    rows = []
    reused = 0
    computed = 0
    count = math.ceil(info.duration / chunk)

    for i in range(count):
        progress.set('ANALYZE_NOTES', i, count)
        cache = Path(job) / 'analysis' / f'frames_{i:05d}.json'
        record = None
        if cache.exists():
            try:
                v = read_json(cache)
                if v.get('analysis_version') == VERSION and v['sha256'] == obj_hash(v['rows']):
                    record = v['rows']
            except (OSError, ValueError, KeyError, TypeError):
                pass
        if record is not None:
            reused += 1
            rows.extend(record)
            continue

        a, b = i * chunk, min(info.duration, (i + 1) * chunk)
        data, origin = read_analysis(path, a - 0.35, b + 0.35)
        mid = np.mean(data, axis=1)
        wide = signal.sosfiltfilt(
            signal.butter(4, [28, 750], btype='bandpass', fs=sr, output='sos'), mid)
        low = signal.sosfiltfilt(
            signal.butter(4, [28, 260], btype='bandpass', fs=sr, output='sos'), mid)
        sub = signal.sosfiltfilt(
            signal.butter(6, [25, 70], btype='bandpass', fs=sr, output='sos'), data, axis=0)

        record = []
        for j in range(int(round(a / hop)), int(math.ceil(b / hop))):
            t = j * hop
            center = int(round((t - origin) * sr))
            if (t - half / sr < 0 or t + half / sr > info.duration or
                    center - half < 0 or center + half > len(data)):
                record.append(dict(
                    time=t, track_state='UNKNOWN', track_reason='file_edge',
                    state='ABSTAIN', reason='file_edge', amplitude=0.0))
                continue
            sl = slice(center - half, center + half)
            record.append(analyze_frame(wide[sl], low[sl], data[sl], sub[sl], t))

        atomic_json(cache, {
            'analysis_version': VERSION,
            'rows': record,
            'sha256': obj_hash(record),
        })
        rows.extend(record)
        computed += 1
        if interrupt_after is not None and computed >= interrupt_after:
            raise RuntimeError('TEST_INTERRUPTION_AFTER_ANALYSIS_COMMIT')

    return rows, {'computed_chunks': computed, 'reused_chunks': reused}


def _is_trackable(row):
    if 'track_state' in row:
        return row.get('track_state') == 'TRACK'
    return row.get('f0_hz') is not None and select_generation_target(row.get('f0_hz')) is not None


def _row_target(row):
    target = row.get('tracking_target_hz')
    if target is None:
        target = row.get('sub_hz')
    if target is None:
        target = select_generation_target(row.get('f0_hz'))
    return None if target is None else float(target)


def stabilize_tracking_rows(rows):
    """Bridge only an isolated one-frame target outlier using neighboring evidence.

    The raw pitch/target observation is retained.  The outlier frame is forced to
    zero addition, so context may preserve note lifetime and phase but never turns
    uncertainty into an audible invented pitch.  SILENCE/UNKNOWN and explicit
    boundary/reattack evidence are never bridged.
    """
    stable = [dict(row) for row in rows]
    if len(stable) < 3:
        return stable
    hop_limit = CONFIG['hop_seconds'] * 1.5
    for i in range(1, len(stable) - 1):
        prev, row, nxt = stable[i - 1], stable[i], stable[i + 1]
        if not (_is_trackable(prev) and _is_trackable(row) and _is_trackable(nxt)):
            continue
        if row.get('boundary_evidence') or row.get('reattack_evidence'):
            continue
        if (float(row['time']) - float(prev['time']) > hop_limit or
                float(nxt['time']) - float(row['time']) > hop_limit):
            continue
        a, b, c = _row_target(prev), _row_target(row), _row_target(nxt)
        if a is None or b is None or c is None:
            continue
        if cents(a, c) > CONFIG['max_step_cents']:
            continue
        if (cents(b, a) <= CONFIG['max_step_cents'] or
                cents(b, c) <= CONFIG['max_step_cents']):
            continue
        bridged = float(math.sqrt(a * c))
        row['raw_tracking_target_hz'] = float(b)
        row['tracking_target_hz'] = bridged
        row['tracking_correction'] = 'isolated_target_outlier_bridged'
        row['amount_state'] = 'ZERO_TRACKING_OUTLIER'
        row['state'] = 'KEEP'
        row['reason'] = 'isolated_target_outlier_no_addition'
        row['amplitude'] = 0.0
    return stable


def _reattack_detected(group, row):
    if row.get('reattack_evidence') is True:
        return True
    if len(group) < 2:
        return False
    a = float(group[-2].get('tonal_strength', 0.0))
    b = float(group[-1].get('tonal_strength', 0.0))
    c = float(row.get('tonal_strength', 0.0))
    if min(a, b, c) <= EPS:
        return False
    drop = 20.0 * math.log10(a / b)
    rise = 20.0 * math.log10(c / b)
    return drop >= CONFIG['reattack_drop_db'] and rise >= CONFIG['reattack_rise_db']


def track_notes(rows):
    """Group tracked notes independently of addition amount.

    Unknown/silence closes a note; an amount of zero does not. An f0 octave
    switch does not close a note when the selected target remains continuous.
    A single contradictory target frame may be context-bridged, but it remains
    silent and its raw observation remains recorded.
    """
    tracks = []
    group = []

    def close():
        if group:
            tracks.append(group.copy())
            group.clear()

    for row in stabilize_tracking_rows(rows):
        if not _is_trackable(row):
            close()
            continue
        target = _row_target(row)
        if target is None:
            close()
            continue

        if group:
            prev = group[-1]
            prev_target = _row_target(prev)
            gap = float(row['time']) - float(prev['time'])
            target_jump = (prev_target is None or
                           cents(target, prev_target) > CONFIG['max_step_cents'])
            trial_targets = [_row_target(r) for r in group] + [target]
            trial_targets = [x for x in trial_targets if x is not None]
            span_too_wide = (
                len(trial_targets) > 1 and
                cents(max(trial_targets), min(trial_targets)) > CONFIG['max_event_span_cents']
            )
            if (gap > CONFIG['hop_seconds'] * 1.5 or target_jump or
                    span_too_wide or _reattack_detected(group, row)):
                close()

        group.append(row)

    close()
    return tracks


def event_wave(event, times, phase=None):
    """Draw one tracked note with continuous phase across internal zero-amount spans."""
    times = np.asarray(times, dtype=np.float64)
    knots = np.asarray(event['times'], dtype=np.float64)
    freq = np.asarray(event['frequencies'], dtype=np.float64)
    amps = np.asarray(event['amplitudes'], dtype=np.float64)
    integ = np.asarray(event['integral_cycles'], dtype=np.float64)
    if len(knots) < 2:
        return np.zeros_like(times)

    j = np.clip(np.searchsorted(knots, times, side='right') - 1, 0, len(knots) - 2)
    dt = times - knots[j]
    width = np.maximum(knots[j + 1] - knots[j], EPS)
    r = np.clip(dt / width, 0, 1)
    cycles = (integ[j] + freq[j] * dt +
              0.5 * (freq[j + 1] - freq[j]) / width * dt * dt)
    amp = amps[j] + (amps[j + 1] - amps[j]) * smoother(r)

    duration = max(float(event['end']) - float(event['start']), 0.0)
    default_fade = min(CONFIG['fade_seconds'],
                       duration * CONFIG['adaptive_fade_fraction'])
    attack = float(event.get('attack_seconds', default_fade))
    release = float(event.get('release_seconds', default_fade))
    env = np.ones_like(times)
    if attack > EPS:
        env *= smoother((times - event['start']) / attack)
    if release > EPS:
        env *= smoother((event['end'] - times) / release)

    mask = (times >= event['start']) & (times < event['end'])
    ph = event.get('phase', 0.0) if phase is None else phase
    return mask * amp * env * np.cos(2 * np.pi * cycles + ph)


def make_events(rows, path):
    """Build render events from tracked notes; zero addition does not terminate a note."""
    groups = track_notes(rows)
    events = []
    rejected = []

    for group in groups:
        start = float(group[0]['time'])
        end = float(group[-1]['time'])
        if end - start < CONFIG['min_event_seconds'] - 1e-8:
            rejected.append(dict(start=start, end=end, reason='short_tracked_note'))
            continue

        freq = np.array([_row_target(r) for r in group], dtype=np.float64)
        if np.any(~np.isfinite(freq)):
            rejected.append(dict(start=start, end=end, reason='target_unavailable'))
            continue
        if cents(float(np.max(freq)), float(np.min(freq))) > CONFIG['max_event_span_cents']:
            rejected.append(dict(start=start, end=end, reason='unstable_target_trajectory'))
            continue

        amplitudes = np.array([max(0.0, float(r.get('amplitude', 0.0)))
                               for r in group], dtype=np.float64)
        if not np.any(amplitudes > 0):
            rejected.append(dict(start=start, end=end, reason='tracked_but_no_addition_required'))
            continue

        tt = np.array([float(r['time']) for r in group], dtype=np.float64)
        cycles = np.r_[0.0, np.cumsum((freq[1:] + freq[:-1]) * 0.5 * np.diff(tt))]
        duration = end - start
        fade = min(CONFIG['fade_seconds'], duration * CONFIG['adaptive_fade_fraction'])
        event = dict(
            start=start,
            end=end,
            times=tt.tolist(),
            frequencies=freq.tolist(),
            amplitudes=amplitudes.tolist(),
            integral_cycles=cycles.tolist(),
            median_f0_hz=float(np.median([float(r['f0_hz']) for r in group])),
            median_sub_hz=float(np.median(freq)),
            active_addition_seconds=float(np.count_nonzero(amplitudes > 0) *
                                          CONFIG['hop_seconds']),
            tracking_corrections=int(sum(bool(r.get('tracking_correction')) for r in group)),
            attack_seconds=float(fade),
            release_seconds=float(fade),
            phase=0.0,
        )

        data, origin = read_analysis(path, start, min(end, start + 2.0))
        t = origin + np.arange(len(data)) / CONFIG['analysis_sr']
        keep = (t >= start) & (t < end)
        data = data[keep]
        t = t[keep]
        if not len(t):
            continue

        best = None
        for candidate_phase in np.arange(8) * np.pi / 4:
            y = event_wave(event, t, float(candidate_phase))
            corr = float(np.sum(y * np.mean(data, axis=1)))
            peak = float(np.max(np.abs(data + y[:, None])))
            cost = (corr < -1e-8, peak, -corr, float(candidate_phase))
            if best is None or cost < best[0]:
                best = (cost, float(candidate_phase))
        event['phase'] = best[1]
        events.append(event)

    return events, rejected


def layer_chunk(events, start_frame, frames, sr, scale=1.0):
    t = (start_frame + np.arange(frames, dtype=np.float64)) / sr
    out = np.zeros(frames, dtype=np.float64)
    if frames:
        for event in events:
            if event['start'] > t[-1] or event['end'] <= t[0]:
                continue
            mask = (t >= event['start']) & (t < event['end'])
            out[mask] += event_wave(event, t[mask]) * scale
    return out


from contextlib import contextmanager


@contextmanager
def _patched_base_runtime():
    # The existing isolated lab owns persistence, validation, matching and codec
    # handling. Patch only its lab-level globals for the duration of a v0.2 call,
    # then restore them so v0.1.1 tests/callers remain independent in-process.
    names = ('VERSION', 'CONFIG', '__file__', 'sub_frequency', 'analyze_frame',
             'collect_frames', 'event_wave', 'make_events', 'layer_chunk')
    saved = {name: getattr(_v011, name) for name in names}
    try:
        _v011.VERSION = VERSION
        _v011.CONFIG = CONFIG
        _v011.__file__ = __file__
        _v011.sub_frequency = select_generation_target
        _v011.analyze_frame = analyze_frame
        _v011.collect_frames = collect_frames
        _v011.event_wave = event_wave
        _v011.make_events = make_events
        _v011.layer_chunk = layer_chunk
        yield
    finally:
        for name, value in saved.items():
            setattr(_v011, name, value)


def render(path, job, events, progress, scale, gain=1.0, label='candidate',
           interrupt_after=None):
    with _patched_base_runtime():
        return _v011.render(
            path, job, events, progress, scale, gain=gain, label=label,
            interrupt_after=interrupt_after)


def run_job(source, root, write_mp3=True, expected_hash=None, interrupt_after=None):
    with _patched_base_runtime():
        return _v011.run_job(
            source, root, write_mp3=write_mp3,
            expected_hash=expected_hash, interrupt_after=interrupt_after)


def main():
    with _patched_base_runtime():
        return _v011.main()


def __getattr__(name):
    # Delegate unchanged utility functions/constants without duplicating the
    # established isolated lab implementation.
    return getattr(_v011, name)


if __name__ == '__main__':
    main()
