"""Reusable local Whisper engine. No installer, network, recording, or fallback.

CPU disk compilation cache is deliberately disabled: a real Windows reference
reproduced a serialization failure when CACHE_DIR was passed to this model.
NPU support still requires target-hardware acceptance; requesting NPU is not
proof of encoder/decoder execution placement.
"""
from __future__ import annotations
from dataclasses import dataclass
from importlib.metadata import version
import math
from pathlib import Path
import threading
import time
from typing import Sequence

EXPECTED = {'openvino': '2026.1.0', 'openvino-genai': '2026.1.0.0',
            'openvino-tokenizers': '2026.1.0.0'}
LANGUAGES = {'ja': '<|ja|>', 'en': '<|en|>', 'auto': None}


@dataclass(frozen=True)
class Transcript:
    text: str
    inference_seconds: float
    audio_seconds: float
    requested_device: str
    execution_components_verified: bool = False


def validate_audio(samples: Sequence[float], language: str) -> list[float]:
    if language not in LANGUAGES:
        raise ValueError('Language must be ja, en, or auto')
    if isinstance(samples, (str, bytes, bytearray)) or not 160 <= len(samples) <= 480000:
        raise ValueError('Expected 0.01 to 30 seconds of 16000 Hz mono samples')
    if any(isinstance(value, bool) for value in samples):
        raise ValueError('Boolean values are not audio samples')
    audio = [float(value) for value in samples]
    if any(not math.isfinite(value) or abs(value) > 1.01 for value in audio):
        raise ValueError('Samples must be finite and normalized to approximately [-1, 1]')
    return audio


class WhisperEngine:
    def __init__(self, model_dir: Path, device: str = 'NPU', *,
                 npu_cache_dir: Path | None = None):
        if device not in ('CPU', 'GPU', 'NPU'):
            raise ValueError('An explicit CPU, GPU, or NPU device is required')
        if npu_cache_dir is not None and device != 'NPU':
            raise ValueError('Disk compilation cache is permitted only for explicit NPU experiments')
        self.versions = {name: version(name) for name in EXPECTED}
        if self.versions != EXPECTED:
            raise RuntimeError('Runtime versions differ from the tested combination')
        model_dir = Path(model_dir).resolve(strict=True)
        if not model_dir.is_dir():
            raise ValueError('Model directory is required')
        import openvino as ov
        import openvino_genai as genai
        available = list(ov.Core().available_devices)
        if not any(name == device or name.startswith(device + '.') for name in available):
            raise RuntimeError('Requested device is unavailable; no fallback was performed')
        props = {}
        if npu_cache_dir is not None:
            cache = Path(npu_cache_dir).resolve()
            cache.mkdir(parents=True, exist_ok=True)
            props['CACHE_DIR'] = str(cache)
        self.requested_device = device
        self._properties = props.copy()
        self._lock = threading.Lock()
        self._pipeline = genai.WhisperPipeline(str(model_dir), device, **props)

    @property
    def compilation_properties(self) -> dict:
        return self._properties.copy()

    def transcribe(self, samples: Sequence[float], language: str = 'ja') -> Transcript:
        audio = validate_audio(samples, language)
        with self._lock:
            config = self._pipeline.get_generation_config()
            config.task = 'transcribe'
            config.language = LANGUAGES[language]
            config.num_beams = 1
            config.do_sample = False
            config.max_new_tokens = 440
            config.return_timestamps = False
            started = time.perf_counter()
            result = self._pipeline.generate(audio, config)
            elapsed = time.perf_counter() - started
        texts = getattr(result, 'texts', None)
        if not isinstance(texts, (list, tuple)) or not texts:
            raise RuntimeError('Invalid transcription result container')
        if any(not isinstance(item, str) for item in texts):
            raise RuntimeError('Invalid transcription result item')
        text = '\n'.join(texts).strip()
        if not text:
            raise RuntimeError('Empty transcript; this is not a successful speech result')
        return Transcript(text, elapsed, len(audio) / 16000.0, self.requested_device)
