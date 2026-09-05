"""Developer-only Windows CPU engine test; never imports the app installer.

Uses public data and vendor APIs, with no recording, user files, subprocesses,
credential loading, security-setting changes, or automatic fallback.
"""
from __future__ import annotations
import gc
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import sys
import time
import traceback
import unicodedata

MODEL = 'OpenVINO/whisper-large-v3-turbo-int8-ov'
REVISION = '4929ae83ea2d1df59f4b5898a9aab8aa1c29e711'
DATASET = 'japanese-asr/ja_asr.jsut_basic5000'
DATA_REVISION = '278db379fc96167ff2293d7abf9ab86976afcd78'
REFERENCE = '水をマレーシアから買わなくてはならないのです。'
MODEL_FILES = [
    'config.json', 'generation_config.json', 'preprocessor_config.json',
    'openvino_encoder_model.xml', 'openvino_encoder_model.bin',
    'openvino_decoder_model.xml', 'openvino_decoder_model.bin',
    'openvino_tokenizer.xml', 'openvino_tokenizer.bin',
    'openvino_detokenizer.xml', 'openvino_detokenizer.bin',
]


def normalized(text: str) -> str:
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def cer(reference: str, prediction: str) -> float:
    a, b = normalized(reference), normalized(prediction)
    if not a:
        raise ValueError('Empty reference')
    row = list(range(len(b) + 1))
    for i, c in enumerate(a, 1):
        nxt = [i]
        for j, d in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (c != d)))
        row = nxt
    return row[-1] / len(a)


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> int:
    evidence = Path('reference-evidence')
    evidence.mkdir(exist_ok=True)
    work = Path(os.environ['RUNNER_TEMP']) / 'LocalScribe 参照試験'
    work.mkdir(parents=True, exist_ok=True)
    report = {
        'scope': 'reusable_cpu_engine_only_not_application_acceptance',
        'outcome': 'incomplete', 'phase': 'start',
        'platform': platform.system(), 'python': platform.python_version(),
        'commit': os.environ.get('LS_SOURCE_SHA', ''),
        'model': MODEL, 'revision': REVISION,
        'dataset': DATASET, 'dataset_revision': DATA_REVISION,
        'npu_tested': False, 'gui_tested': False, 'live_tested': False,
        'product_release_approved': False,
        'app_installer_used': False, 'user_data_used': False,
        'cer_threshold': 0.35,
        'threshold_scope': 'single_fixture_integration_not_product_accuracy',
    }
    started = time.perf_counter()

    def save(phase: str | None = None) -> None:
        if phase is not None:
            report['phase'] = phase
            print('PHASE:', phase, flush=True)
        report['elapsed_seconds'] = round(time.perf_counter() - started, 3)
        (evidence / 'result.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')

    try:
        save('runtime_import')
        if platform.system() != 'Windows':
            raise RuntimeError('This reference gate must actually run on Windows')
        import numpy as np
        import soundfile as sf
        from scipy.signal import resample_poly
        from huggingface_hub import hf_hub_download
        import openvino as ov
        import openvino_genai as genai
        packages = ['openvino', 'openvino-genai', 'openvino-tokenizers',
                    'openvino-telemetry', 'numpy', 'soundfile', 'scipy', 'huggingface-hub']
        report['packages'] = {p: importlib.metadata.version(p) for p in packages}
        report['runtime_versions'] = {'openvino': str(ov.__version__),
                                      'genai': str(genai.__version__)}
        report['available_devices'] = list(ov.Core().available_devices)
        save('model_download')
        model_dir = work / 'model'
        for name in MODEL_FILES + ['README.md']:
            hf_hub_download(MODEL, name, revision=REVISION, local_dir=model_dir, token=False)
        report['model_sha256'] = {name: digest(model_dir / name) for name in MODEL_FILES}
        card = (model_dir / 'README.md').read_text(encoding='utf-8')
        report['model_compatibility_lines'] = [
            line for line in card.splitlines()
            if 'version' in line.lower() and ('openvino' in line.lower() or 'optimum' in line.lower())
        ][:4]
        minimum = re.search(r'OpenVINO version (\d+\.\d+\.\d+) and higher', card)
        if minimum is None:
            raise RuntimeError('Model compatibility minimum is not explicit')
        actual = tuple(int(x) for x in report['packages']['openvino'].split('.')[:3])
        required = tuple(int(x) for x in minimum.group(1).split('.'))
        report['model_minimum_runtime'] = minimum.group(1)
        report['declared_runtime_compatibility_met'] = actual >= required
        if actual < required:
            raise RuntimeError('Runtime is below the model-declared minimum')
        save('public_fixture_download')
        fixture = Path(hf_hub_download(DATASET, 'sample.flac', repo_type='dataset',
                                      revision=DATA_REVISION, local_dir=work / 'fixture', token=False))
        report['fixture_sha256'] = digest(fixture)
        samples, rate = sf.read(fixture, dtype='float32', always_2d=True)
        if samples.shape[1] not in (1, 2) or not np.isfinite(samples).all():
            raise RuntimeError('Invalid public fixture waveform')
        samples = samples.mean(axis=1)
        divisor = math.gcd(int(rate), 16000)
        if rate != 16000:
            samples = resample_poly(samples, 16000 // divisor, int(rate) // divisor)
        seconds = len(samples) / 16000
        if not 2 <= seconds <= 29 or not np.isfinite(samples).all():
            raise RuntimeError('Invalid public fixture duration or resampling')
        if np.max(np.abs(samples)) <= 0.001 or np.max(np.abs(samples)) > 1.01:
            raise RuntimeError('Invalid public fixture amplitude')
        report['audio_seconds'] = seconds
        report['configuration'] = dict(device='CPU', language='<|ja|>', task='transcribe',
                                        max_new_tokens=440, num_beams=1,
                                        do_sample=False, return_timestamps=False,
                                        cache_dir='disabled_for_cpu')
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from core.whisper_engine import WhisperEngine
        report['engine_source'] = 'localscribe/core/whisper_engine.py'
        report['cpu_disk_cache_policy'] = 'disabled_after_reproduced_serialization_failure'
        report['cache_failure_witness_run'] = 33962981894
        report['cases'] = []
        baseline_text = None
        for mode in ('new_session', 'reconstructed_session'):
            case = {'mode': mode, 'outcome': 'incomplete', 'runs': []}
            report['cases'].append(case)
            save(mode + '_pipeline_construct')
            t0 = time.perf_counter()
            pipeline = WhisperEngine(model_dir, 'CPU')
            if pipeline.compilation_properties:
                raise RuntimeError('CPU disk cache unexpectedly enabled')
            case['model_load_seconds'] = time.perf_counter() - t0
            for index in range(2 if mode == 'new_session' else 1):
                save(mode + '_generate_' + str(index))
                result = pipeline.transcribe(samples.tolist(), 'ja')
                seconds = result.inference_seconds
                text = result.text
                score = cer(REFERENCE, text)
                if baseline_text is None:
                    baseline_text = normalized(text)
                row = {'index': index, 'inference_seconds': seconds, 'cer': score,
                       'recognized_characters': len(text),
                       'matches_baseline_normalized': normalized(text) == baseline_text}
                case['runs'].append(row)
                save(mode + '_markdown_export_' + str(index))
                # Transcript remains in the ephemeral workspace, never evidence.
                output = work / (mode + '_' + str(index) + '.md')
                output.write_text('# Public Japanese fixture\n\n' + text + '\n', encoding='utf-8')
                row['markdown_roundtrip_verified'] = text in output.read_text(encoding='utf-8')
                row['transcript_sha256'] = digest(output)
                if not row['markdown_roundtrip_verified']:
                    raise RuntimeError('Markdown round-trip mismatch')
                if score > report['cer_threshold']:
                    raise RuntimeError('Public fixture does not meet the fixed integration threshold')
                if not row['matches_baseline_normalized']:
                    raise RuntimeError('Transcript changed between cache or repeated-call conditions')
            case['outcome'] = 'passed'
            negative_checks = []
            for bad_samples, bad_language in (([], 'ja'), ([float('nan')] * 160, 'ja'),
                                              ([2.0] * 160, 'ja'), ([0.0] * 160, 'invalid')):
                try:
                    pipeline.transcribe(bad_samples, bad_language)
                except ValueError:
                    negative_checks.append(True)
                else:
                    raise RuntimeError('Invalid audio/language unexpectedly accepted')
            case['invalid_input_rejected'] = len(negative_checks)
            del pipeline
            gc.collect()
        report['outcome'] = 'cpu_engine_passed_not_application_acceptance'
        save('complete')
        code = 0
    except Exception as exc:
        report['outcome'] = 'failed'
        report['error_type'] = type(exc).__name__
        report['error'] = str(exc)[:8000]
        report['traceback'] = traceback.format_exc()[-12000:]
        save()
        print(report['traceback'], file=sys.stderr, flush=True)
        code = 1
    summary = ('# LocalScribe Windows CPU reference\n\n'
               f"- Outcome: {report['outcome']}\n- Last phase: {report['phase']}\n"
               '- This does not certify the GUI, packaged app, NPU, live audio, or product quality.\n'
               '- No private audio, user files, or transcript content is uploaded.\n')
    (evidence / 'SUMMARY.md').write_text(summary, encoding='utf-8')
    print('RESULT:', json.dumps(report, ensure_ascii=False), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
