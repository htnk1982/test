"""Integration step 1: typed provenance and integer source clocks.

These contracts prevent accidental mixing of jobs; they are not signatures from
an untrusted caller, nor proof of perceptual quality or source-separator accuracy.
No model, song identifier, review text or reference audio is bundled here.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from fractions import Fraction
from pathlib import Path
import hashlib
import json
import math
import numpy as np
import soundfile as sf

VERSION = 'integration-contract-0.1.0'
RATES = (32000, 44100, 48000, 88200, 96000)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
        ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def valid_hash(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError('Expected integer ' + name)
    return value


def file_hash(path) -> str:
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(2**20), b''):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class AudioIdentity:
    file_sha256: str
    pcm_sha256: str
    samplerate: int
    frames: int
    channels: int

    def validate(self):
        if not valid_hash(self.file_sha256) or not valid_hash(self.pcm_sha256):
            raise ValueError('Invalid audio identity hashes')
        integer(self.samplerate, 'samplerate', 1)
        integer(self.frames, 'frames', 1)
        if self.samplerate not in RATES or type(self.channels) is not int or self.channels != 2:
            raise ValueError('Unsupported stereo geometry')
        if not self.samplerate // 2 <= self.frames <= self.samplerate * 1800:
            raise ValueError('Supported length is 0.5 to 1800 seconds')
        return self

    @property
    def token(self):
        self.validate()
        return digest(asdict(self))

    def verify(self, path):
        # Verify both the stored bytes and decoded content; a same-name file is
        # not sufficient. NaN is checked even if the subsequent plan is KEEP.
        if capture(path) != self:
            raise ValueError('Audio identity changed')


def capture(path) -> AudioIdentity:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('A regular audio file is required')
    before = file_hash(path)
    with sf.SoundFile(path) as src:
        if src.format not in ('WAV', 'WAVEX', 'FLAC'):
            raise ValueError('Integration input requires lossless WAV/FLAC')
        geometry = (int(src.samplerate), int(src.frames), int(src.channels))
        # Validate before decoding huge or unsupported files.
        AudioIdentity(before, '0' * 64, *geometry).validate()
        pcm = hashlib.sha256(json.dumps(geometry, separators=(',', ':')).encode())
        read_frames = 0
        for block in src.blocks(blocksize=65536, dtype='float64', always_2d=True):
            if not np.isfinite(block).all():
                raise ValueError('Non-finite input audio')
            read_frames += len(block)
            pcm.update(np.asarray(block, dtype='<f8', order='C').tobytes())
        if read_frames != geometry[1]:
            raise ValueError('Decoded length mismatch')
    if file_hash(path) != before:
        raise RuntimeError('Source changed during identity capture')
    return AudioIdentity(before, pcm.hexdigest(), *geometry).validate()


@dataclass(frozen=True)
class Span:
    start: int
    stop: int

    def validate(self, length):
        integer(length, 'length', 1)
        integer(self.start, 'start')
        integer(self.stop, 'stop', 1)
        if not self.start < self.stop <= length:
            raise ValueError('Invalid half-open source interval')
        return self


@dataclass(frozen=True)
class FrameMap:
    source_rate: int
    source_frames: int
    render_rate: int
    render_frames: int
    # source frame k is located at k*render_rate/source_rate + delay below.
    delay_numerator: int = 0
    delay_denominator: int = 1

    def validate(self):
        for name in ('source_rate', 'source_frames', 'render_rate', 'render_frames', 'delay_denominator'):
            integer(getattr(self, name), name, 1)
        if type(self.delay_numerator) is not int:
            raise ValueError('Delay must be a rational frame count')
        if self.source_rate not in RATES or self.render_rate not in RATES:
            raise ValueError('Unsupported timeline rates')
        expected = Fraction(self.source_frames * self.render_rate, self.source_rate)
        if abs(Fraction(self.render_frames) - expected) > 1:
            raise ValueError('Time stretch / truncation is not an affine SRC map')
        if abs(Fraction(self.delay_numerator, self.delay_denominator)) > self.render_rate:
            raise ValueError('Delay beyond explicit one-second integration budget')
        return self

    def exact(self, frame):
        self.validate(); integer(frame, 'source frame')
        if frame > self.source_frames:
            raise ValueError('Source frame outside declared clock')
        return Fraction(frame * self.render_rate, self.source_rate) + Fraction(self.delay_numerator, self.delay_denominator)

    def span(self, interval: Span) -> Span:
        interval.validate(self.source_frames)
        left, right = self.exact(interval.start), self.exact(interval.stop)
        # Conservative interval coverage. No repeated float accumulation.
        mapped = Span(math.floor(left), math.ceil(right))
        return mapped.validate(self.render_frames)

    def nearest(self, frame):
        value = self.exact(frame)
        # Documented half-up rule for nonnegative physical sample locations.
        if value < 0:
            raise ValueError('Mapped frame falls before physical audio')
        return (value.numerator * 2 + value.denominator) // (2 * value.denominator)


@dataclass(frozen=True)
class RenderSnapshot:
    source: AudioIdentity
    physical: AudioIdentity
    clock: FrameMap
    stage: str
    recipe_sha256: str

    def validate(self):
        self.source.validate(); self.physical.validate(); self.clock.validate()
        if (self.clock.source_rate, self.clock.source_frames) != (self.source.samplerate, self.source.frames):
            raise ValueError('Source clock does not belong to source')
        if (self.clock.render_rate, self.clock.render_frames) != (self.physical.samplerate, self.physical.frames):
            raise ValueError('Physical clock does not belong to snapshot')
        if self.stage != 'HE_AUTO_PREP' or not valid_hash(self.recipe_sha256):
            raise ValueError('Unrecognized prepared stage')
        return self

    @property
    def token(self):
        self.validate(); return digest(asdict(self))

    def verify(self, source_path, physical_path):
        self.validate(); self.source.verify(source_path); self.physical.verify(physical_path)

    @classmethod
    def bind(cls, source, physical, recipe, clock=None):
        # Called by the orchestrator AFTER executing the declared recipe. Hashes
        # do not prove a transform's ancestry by themselves.
        if clock is None:
            if (source.samplerate, source.frames) != (physical.samplerate, physical.frames):
                raise ValueError('Explicit SRC/delay map required for changed geometry')
            clock = FrameMap(source.samplerate, source.frames, physical.samplerate, physical.frames)
        return cls(source, physical, clock, 'HE_AUTO_PREP', digest(recipe)).validate()


@dataclass(frozen=True)
class ObserverWindow:
    core: Span
    read: Span


def observation_windows(spans, *, length, rate, core_seconds=8, halo_seconds=2):
    """Deterministic schedule, NOT onset detection or completed observation.

    Cores cover all proposed spans. Context overlap never grants permission
    outside each core. Close spans merge only when they actually touch/overlap.
    The scheduler cannot mark unscheduled song regions as musically healthy.
    """
    integer(length, 'length', 1); integer(rate, 'rate', 1)
    if rate not in RATES or type(core_seconds) is not int or not 1 <= core_seconds <= 16:
        raise ValueError('Invalid core duration in seconds')
    if type(halo_seconds) is not int or not 1 <= halo_seconds <= 4:
        raise ValueError('Invalid context duration in seconds')
    merged = []
    for span in sorted(spans, key=lambda s: (s.start, s.stop)):
        span.validate(length)
        if merged and span.start <= merged[-1].stop:
            merged[-1] = Span(merged[-1].start, max(merged[-1].stop, span.stop))
        else:
            merged.append(span)
    result = []; width = core_seconds * rate; halo = halo_seconds * rate
    for span in merged:
        for start in range(span.start, span.stop, width):
            stop = min(span.stop, start + width)
            result.append(ObserverWindow(Span(start, stop), Span(max(0, start-halo), min(length, stop+halo))))
    return tuple(result)
