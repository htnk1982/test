"""One explicitly selected local WAV/FLAC to JSON. No network, installer, recording or subprocess.
The desktop host owns outputs and worker lifetime.
"""
from __future__ import annotations
import json
import math
import sys
import time
from pathlib import Path
from desktop.model_guard import verify_model
from desktop.local_io import public_error


def emit(kind: str, **fields):
    print('LSJSON:' + json.dumps(dict(event=kind, **fields), ensure_ascii=True), flush=True)


def main():
    phase = 'request'
    paths = [Path.home()]
    try:
        request = json.loads(sys.stdin.read(32769))
        if not isinstance(request, dict):
            raise ValueError('Invalid request')
        case = request.get('case', 'normal')
        if case in ('native_wait', 'early_exit'):
            if request.get('developer_exercise') is not True:
                raise ValueError('Developer exercise not enabled')
            emit('phase', phase='native_wait')
            if case == 'early_exit':
                return 7
            import ctypes
            ctypes.windll.kernel32.Sleep(30000)
            return 8
        if case != 'normal':
            raise ValueError('Unknown operation')
        audio = Path(request['audio']).resolve(strict=True)
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
        model = base / 'models'
        paths += [audio, model, base]
        if audio.suffix.lower() not in ('.wav', '.flac') or not audio.is_file():
            raise ValueError('WAV or FLAC input is required')
        device = request['device']
        if device not in ('CPU', 'NPU', 'GPU'):
            raise ValueError('Explicit device required')
        phase = 'audio_read'
        emit('phase', phase=phase)
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        info = sf.info(audio)
        if not 0.1 <= info.duration <= 30 or info.channels not in (1, 2) or not 8000 <= info.samplerate <= 192000:
            raise ValueError('AUDIO_SCOPE: 0.1..30 s, 8..192 kHz, mono/stereo')
        samples, rate = sf.read(audio, dtype='float32', always_2d=True)
        if not np.isfinite(samples).all() or np.max(np.abs(samples)) > 1.01:
            raise ValueError('Invalid audio amplitude')
        samples = samples.mean(axis=1)
        if np.max(np.abs(samples)) < 0.0001:
            raise ValueError('AUDIO_SILENCE')
        divisor = math.gcd(int(rate), 16000)
        if rate != 16000:
            samples = resample_poly(samples, 16000 // divisor, int(rate) // divisor)
        phase = 'model_verify'
        emit('phase', phase=phase)
        verify_model(model)
        phase = 'model_load'
        emit('phase', phase=phase)
        from core.whisper_engine import WhisperEngine
        t0 = time.perf_counter()
        engine = WhisperEngine(model, device)
        load_seconds = time.perf_counter() - t0
        times, texts = [], []
        for index in range(2):
            phase = 'transcribe_' + str(index + 1)
            emit('phase', phase=phase)
            result = engine.transcribe(samples.tolist(), 'ja')
            if len(result.text) > 16000:
                raise ValueError('Transcript exceeds bounded protocol')
            times.append(result.inference_seconds)
            texts.append(result.text)
        emit('result', outcome='success', phase='complete', requested_device=device,
             text=texts[-1], model_load_seconds=load_seconds, inference_seconds=times,
             audio_seconds=len(samples)/16000, repeated_text_equal=texts[0] == texts[1],
             npu_components_verified=False, version='0.5.0-bounded-file-candidate')
        return 0
    except Exception as exc:
        emit('result', outcome='failed', phase=phase, error_type=type(exc).__name__,
             error=public_error(exc, paths), npu_components_verified=False)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
