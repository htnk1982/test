"""Boundary39 LAB: compare component decay within a supported source event.

Not a universal resonance detector or a calibrated perceptual score. Event and
component association are hypotheses supplied by the observation layer. No
separated audio is rendered. Production HE/HFTC/OPPO and defaults are untouched.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import hashlib
import json
import math
from pathlib import Path
from typing import Any
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import distance_transform_edt
import spectral_persistence_lab as spectral
import relative_spectral_v38 as prior

VERSION = 'event-decay-lab-0.1.0'
PHENOMENON = 'relative_component_decay'
ROLES = ('drums', 'bass', 'other', 'vocals')
EPS = 1e-24


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()


def file_hash(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(2**20), b''):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class Config:
    grid_seconds: float = .02
    minimum_event_seconds: float = .8
    maximum_event_seconds: float = 8.
    minimum_joint_rise_db: float = 2.
    companion_withdrawal_db: float = 3.
    minimum_excess_db: float = 1.
    reference_margin_db: float = .5
    maximum_cut_db: float = 1.5
    minimum_run_seconds: float = .12
    smoothing_seconds: float = .12
    post_anchor_guard_seconds: float = .08
    boundary_fade_seconds: float = .12
    maximum_peer_disagreement_db: float = 4.

    def validate(self) -> Config:
        for key, val in asdict(self).items():
            if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
                raise ValueError('Non-finite configuration: ' + key)
        if self.grid_seconds != .02:
            raise ValueError('Feature grid is exactly 20 milliseconds')
        if not .6 <= self.minimum_event_seconds < self.maximum_event_seconds <= 8:
            raise ValueError('Event duration budget')
        if not 0 < self.maximum_cut_db <= 1.5:
            raise ValueError('Spectral branch maximum is 1.5 dB')
        if not .5 <= self.minimum_excess_db <= 3 or not 0 <= self.reference_margin_db <= 2:
            raise ValueError('Invalid reference/excess margin')
        if not .06 <= self.minimum_run_seconds <= .5 or not .06 <= self.smoothing_seconds <= .3:
            raise ValueError('Time constants are seconds, not milliseconds')
        if not .04 <= self.post_anchor_guard_seconds <= .3 or not .06 <= self.boundary_fade_seconds <= .3:
            raise ValueError('Invalid event boundary guard')
        if not 1 <= self.minimum_joint_rise_db <= 12 or not 1 <= self.companion_withdrawal_db <= 12:
            raise ValueError('Invalid event evidence budget')
        if not 1 <= self.maximum_peer_disagreement_db <= 12:
            raise ValueError('Invalid peer agreement budget')
        return self


@dataclass(frozen=True)
class Event:
    start_seconds: float
    anchor_start_seconds: float
    anchor_end_seconds: float
    end_seconds: float
    target_band: int
    companion_bands: tuple[int, ...]
    role: str
    family: str

    def validate(self, cfg: Config = Config()) -> Event:
        cfg.validate()
        times = (self.start_seconds, self.anchor_start_seconds,
                 self.anchor_end_seconds, self.end_seconds)
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in times):
            raise ValueError('Invalid event clock')
        if not .20 <= times[0] < times[1] < times[2] < times[3]:
            raise ValueError('Event must include source pre-onset and anchor context')
        if not cfg.minimum_event_seconds <= times[3] - times[0] <= cfg.maximum_event_seconds:
            raise ValueError('Event range is outside finite LAB budget')
        if times[2] - times[1] < .08 or times[3] - times[2] < .3:
            raise ValueError('Insufficient anchor or tail')
        if type(self.target_band) is not int or not 0 <= self.target_band < 20:
            raise ValueError('Invalid target band')
        peers = self.companion_bands
        if not 2 <= len(peers) <= 4 or len(set(peers)) != len(peers):
            raise ValueError('At least two distinct source components required')
        if any(type(v) is not int or not 0 <= v < 20 or v == self.target_band for v in peers):
            raise ValueError('Invalid companion component')
        if self.role not in ROLES or not isinstance(self.family, str) or not self.family.strip():
            raise ValueError('Unknown role/family')
        return self

    def key(self) -> dict:
        # Relative spectral geometry, NOT track/artist identity or absolute note.
        return dict(role=self.role, family=self.family,
            companion_offsets=sorted(v - self.target_band for v in self.companion_bands))


def review_applicability(label: dict, event: Event) -> str:
    """A role-level comment is not a full-track, every-band quality label."""
    if label.get('quality') in (None, '', '-', 'unreviewed'):
        return 'UNREVIEWED'
    if label.get('role') != event.role:
        return 'OUTSIDE_ROLE'
    if label.get('phenomenon') != PHENOMENON:
        return 'OUTSIDE_PHENOMENON'
    interval = label.get('time_range_seconds')
    if interval is None:
        return 'WEAK_TRACK_ROLE_LABEL'
    if len(interval) != 2 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in interval):
        raise ValueError('Invalid review interval')
    if not interval[0] <= event.start_seconds < event.end_seconds <= interval[1]:
        return 'OUTSIDE_REVIEW_INTERVAL'
    return 'LOCAL_' + str(label['quality']).upper()


def relation(features: dict, event: Event, cfg: Config = Config()) -> dict:
    cfg.validate(); event.validate(cfg); spectral.validate_features(features)
    t = np.asarray(features['time'], dtype=float)
    d = np.asarray(features['db'], dtype=float)
    if t[0] > event.start_seconds - .18 or t[-1] + cfg.grid_seconds < event.end_seconds:
        raise ValueError('Features do not cover full event and pre-onset')
    ids = (event.target_band,) + tuple(event.companion_bands)
    anchor = (t >= event.anchor_start_seconds) & (t < event.anchor_end_seconds)
    before = (t >= event.start_seconds - .18) & (t < event.start_seconds - .08)
    core = (t >= event.start_seconds) & (t < event.end_seconds)
    if anchor.sum() < 3 or before.sum() < 3 or core.sum() < 25:
        raise ValueError('Insufficient independent time samples')
    base = np.median(d[anchor][:, ids], axis=0)
    rise = base - np.median(d[before][:, ids], axis=0)
    drops = d[:, ids] - base[None, :]
    peer_drop = np.median(drops[:, 1:], axis=1)
    disagreement = np.ptp(drops[:, 1:], axis=1)
    rel = drops[:, 0] - peer_drop
    return dict(time=t, relative_decay_db=rel, companion_change_db=peer_drop,
        peer_disagreement_db=disagreement, joint_rise_db=rise.tolist(),
        joint_onset_supported=bool(np.all(rise >= cfg.minimum_joint_rise_db)),
        core=core, event=asdict(event), event_key=event.key())


def calibrate(examples: list[dict], cfg: Config = Config()) -> dict:
    """Calibrate only local, explicitly reviewed positive component relations.

    This API intentionally rejects old bass-positive WHOLE-MIX spectral labels.
    A production catalogue must supply local event evidence; no fabricated labels.
    """
    cfg.validate()
    if len(examples) < 4:
        raise ValueError('At least four independent positive source groups required')
    groups = [e['group_id'] for e in examples]
    if any(not isinstance(v, str) or not v for v in groups) or len(set(groups)) != len(groups):
        raise ValueError('Repeated source groups are not independent references')
    phase = np.linspace(0, 1, 101)
    traces = []; key = None
    for ex in examples:
        event = ex['event']; event.validate(cfg)
        if review_applicability(ex['label'], event) != 'LOCAL_POSITIVE':
            raise ValueError('Calibration requires local role/phenomenon positive labels')
        if key is None: key = event.key()
        if event.key() != key:
            raise ValueError('Incomparable event family or role')
        r = relation(ex['features'], event, cfg)
        if not r['joint_onset_supported']:
            raise ValueError('Reference has no common source onset evidence')
        sel = r['core']; et = r['time'][sel]
        u = (et - event.start_seconds) / (event.end_seconds - event.start_seconds)
        traces.append(np.interp(phase, u, r['relative_decay_db'][sel]))
    caps = np.max(np.stack(traces), axis=0) + cfg.reference_margin_db
    atlas = dict(schema=1, version=VERSION, config=asdict(cfg), event_key=key,
        phase=phase.tolist(), cap_db=caps.tolist(), reference_groups=groups,
        label_scope='local-role-phenomenon',
        scope='Empirical relative-decay envelope; not a taste model')
    atlas['sha256'] = digest(atlas)
    return atlas


def validate_atlas(atlas: dict, cfg: Config = Config()) -> None:
    a = dict(atlas); h = a.pop('sha256', None)
    if digest(a) != h or atlas.get('schema') != 1 or atlas.get('version') != VERSION or atlas.get('config') != asdict(cfg):
        raise ValueError('Atlas identity/config mismatch')
    phase = np.asarray(atlas['phase']); caps = np.asarray(atlas['cap_db'])
    if phase.shape != (101,) or caps.shape != (101,) or not np.isfinite(caps).all() or not np.allclose(phase, np.linspace(0, 1, 101)):
        raise ValueError('Invalid relative-decay envelope')


def separator_support(arrays: dict, meta: dict, source_sha256: str,
                      event: Event, cfg: Config = Config()) -> dict:
    """Use verified v38 observer. Same-role is necessary, not proof of same note."""
    event.validate(cfg)
    ev = prior.observer_evidence(arrays, meta, source_sha256)
    wanted = ROLES.index(event.role); ids = (event.target_band,) + event.companion_bands
    reliable = np.all(ev['reliable'][:, ids] & (ev['winner'][:, ids] == wanted), axis=1)
    return dict(provider='verified_observer_v38', source_sha256=source_sha256,
        event_key=event.key(), time=ev['time'], supported=reliable,
        association_claim='Same estimated role plus source co-onset; not proven note identity')


def validate_support(support: dict | None, t: np.ndarray, event: Event,
                     source_sha256: str, allow_test_evidence: bool = False) -> np.ndarray:
    if support is None:
        return np.zeros(len(t), dtype=bool)
    if support.get('source_sha256') != source_sha256 or support.get('event_key') != event.key():
        raise ValueError('Observation/source/event mismatch')
    provider = support.get('provider')
    if provider == 'synthetic_oracle' and not allow_test_evidence:
        raise ValueError('Synthetic oracle cannot be used as production observation')
    if provider not in ('verified_observer_v38', 'synthetic_oracle'):
        raise ValueError('Unknown evidence provider')
    ot = np.asarray(support['time'], dtype=float); ok = np.asarray(support['supported'])
    if len(ot) < 2 or ot.shape != ok.shape or ok.dtype != np.bool_ or not np.isfinite(ot).all() or not np.allclose(np.diff(ot), .02, atol=1e-8):
        raise ValueError('Invalid evidence clock/support')
    return np.interp(t, ot, ok.astype(float), left=0, right=0) > .999


def _long_runs(mask: np.ndarray, required: int) -> np.ndarray:
    transitions = np.diff(np.r_[False, mask, False].astype(int))
    out = np.zeros(len(mask), dtype=bool)
    for a, b in zip(np.flatnonzero(transitions == 1), np.flatnonzero(transitions == -1)):
        if b - a >= required: out[a:b] = True
    return out


def plan(features: dict, event: Event, atlas: dict, source_sha256: str,
         support: dict | None, cfg: Config = Config(), *, allow_test_evidence: bool = False) -> dict:
    cfg.validate(); validate_atlas(atlas, cfg)
    if not isinstance(source_sha256, str) or len(source_sha256) != 64:
        raise ValueError('Exact source SHA-256 is required')
    r = relation(features, event, cfg); t = r['time']
    permission = validate_support(support, t, event, source_sha256, allow_test_evidence)
    depths = np.zeros((len(t), 20), dtype=float)
    record = dict(schema=1, version=VERSION, config=asdict(cfg), event=asdict(event),
        time=t, fc=np.asarray(features['fc']), depth_db=depths,
        source_sha256=source_sha256, atlas_sha256=atlas['sha256'],
        evidence_provider=None if support is None else support['provider'],
        healthy_audio_claim=False, subjective_quality='NOT_EVALUATED')
    if event.key() != atlas['event_key']:
        return dict(record, status='ABSTAIN_UNCALIBRATED_ROLE_OR_FAMILY')
    if event.role == 'vocals':
        return dict(record, status='ABSTAIN_VOCAL_BRANCH')
    if not r['joint_onset_supported']:
        return dict(record, status='ABSTAIN_NO_COMMON_ONSET')
    u = (t - event.start_seconds) / (event.end_seconds - event.start_seconds)
    cap = np.interp(u, atlas['phase'], atlas['cap_db'])
    excess = r['relative_decay_db'] - cap
    withdrawal = r['companion_change_db'] <= -cfg.companion_withdrawal_db
    peers_agree = r['peer_disagreement_db'] <= cfg.maximum_peer_disagreement_db
    tail = (t >= event.anchor_end_seconds + cfg.post_anchor_guard_seconds) & (t < event.end_seconds)
    audible = np.asarray(features['full_db']) > -55
    evidence = r['core'] & tail & withdrawal & peers_agree & audible
    candidate = evidence & (excess >= cfg.minimum_excess_db)
    qualified = _long_runs(candidate, math.ceil(cfg.minimum_run_seconds / cfg.grid_seconds))
    record.update(relative_decay_db=r['relative_decay_db'], cap_db=cap, excess_db=excess,
        companion_change_db=r['companion_change_db'],
        candidate_seconds=float(np.count_nonzero(qualified) * cfg.grid_seconds),
        supported_candidate_seconds=float(np.count_nonzero(qualified & permission) * cfg.grid_seconds))
    if not np.any(qualified):
        return dict(record, status='KEEP_NO_EXCESS_RELATIVE_TAIL')
    if not np.any(qualified & permission):
        return dict(record, status='ABSTAIN_LOCAL_ROLE_SUPPORT')
    raw = np.minimum(cfg.maximum_cut_db, np.maximum(excess, 0)) * qualified * permission
    n = max(3, round(cfg.smoothing_seconds / cfg.grid_seconds) | 1)
    w = signal.windows.hann(n, sym=True); w /= w.sum()
    smooth = np.convolve(np.pad(raw, (n // 2, n // 2), mode='edge'), w, mode='valid')
    safe = permission & tail & r['core'] & peers_agree
    dist = distance_transform_edt(np.r_[False, safe, False])[1:-1] * cfg.grid_seconds
    smooth *= np.clip(dist / cfg.boundary_fade_seconds, 0, 1)
    depths[:, event.target_band] = np.clip(smooth, 0, cfg.maximum_cut_db)
    return dict(record, status='RELATIVE_TAIL_CANDIDATE' if depths.any() else 'ABSTAIN_NO_RENDER_SUPPORT')


def render_array(x: np.ndarray, sr: int, p: dict, strength: float = 1., cfg: Config = Config()) -> np.ndarray:
    cfg.validate(); x = np.asarray(x, dtype=float)
    if sr not in (32000, 44100, 48000, 88200, 96000) or x.ndim != 2 or x.shape[1] != 2 or len(x) < sr * .5 or not np.isfinite(x).all():
        raise ValueError('Invalid source audio')
    if p.get('version') != VERSION or p.get('config') != asdict(cfg):
        raise ValueError('Plan version/config mismatch')
    if not math.isfinite(strength) or not 0 <= strength <= 1:
        raise ValueError('Invalid render strength')
    e = dict(p['event']); e['companion_bands'] = tuple(e['companion_bands']); event = Event(**e).validate(cfg)
    if event.end_seconds > len(x) / sr + 1e-9:
        raise ValueError('Plan outside audio duration')
    dep = np.asarray(p['depth_db']); time = np.asarray(p['time']); fc = np.asarray(p['fc'])
    if dep.shape != (len(time), 20) or fc.shape != (20,) or not np.isfinite(dep).all() or dep.min() < 0 or dep.max() > cfg.maximum_cut_db + 1e-9:
        raise ValueError('Invalid spectral plan')
    if not np.isfinite(time).all() or not np.allclose(np.diff(time), .02, atol=1e-8) or not np.allclose(fc, spectral.centers()):
        raise ValueError('Invalid plan time/frequency units')
    # This branch is a single event-component operation. No undeclared extras.
    other = np.delete(dep, event.target_band, axis=1)
    if np.any(other): raise ValueError('Plan changes undeclared components')
    if strength == 0 or not dep.any(): return x.copy()
    y = spectral.render(x, sr, p, strength, spectral.Config(max_cut_db=cfg.maximum_cut_db))
    # Spectral overlap-add has temporal support. Explicit smooth differential
    # localization protects the original event head and all outside-event audio.
    t = np.arange(len(x)) / sr
    start = event.anchor_end_seconds + cfg.post_anchor_guard_seconds
    left = np.clip((t - start) / cfg.boundary_fade_seconds, 0, 1)
    right = np.clip((event.end_seconds - t) / cfg.boundary_fade_seconds, 0, 1)
    gate = (left * left * (3 - 2 * left)) * (right * right * (3 - 2 * right))
    delta = (y - x) * gate[:, None]
    delta[np.all(x == 0, axis=1)] = 0
    out = x + delta
    if not np.isfinite(out).all(): raise RuntimeError('Non-finite renderer output')
    return out


def render_verified(source: str | Path, p: dict, strength: float = 1., cfg: Config = Config()) -> tuple[np.ndarray, int]:
    source = Path(source); before = file_hash(source)
    if before != p.get('source_sha256'): raise ValueError('Plan belongs to another source')
    x, sr = sf.read(source, dtype='float64', always_2d=True)
    y = render_array(x, sr, p, strength, cfg)
    if file_hash(source) != before: raise RuntimeError('Source changed during render')
    return y, sr
