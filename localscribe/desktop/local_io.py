"""Local, bounded IO for a single user-selected transcription job."""
from __future__ import annotations
from pathlib import Path
import json
import os
import re
import time
import uuid

VERSION = '0.4.0-candidate'

def atomic_text(path: Path, text: str) -> None:
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(6):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(0.05 * (attempt + 1))
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass

def write_json(path: Path, value: dict) -> None:
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2) + '\n')

def read_json(path: Path) -> dict:
    with Path(path).open(encoding='utf-8') as stream:
        result = json.load(stream)
    if not isinstance(result, dict):
        raise ValueError('Expected a JSON object')
    return result

def public_error(exc: BaseException, paths: list[Path]) -> str:
    text = str(exc)
    for path in sorted(paths + [Path.home()], key=lambda p: len(str(p)), reverse=True):
        text = text.replace(str(path), '[local-path]')
    text = re.sub(r'(?i)[a-z]:[\\/][^\r\n"<>]*', '[local-path]', text)
    text = re.sub(r'https?://[^\s<>]+', '[url]', text)
    return text[:3000]

def report_markdown(state: dict) -> str:
    # Transcript and input filename are intentionally absent.
    keys = ('version', 'outcome', 'phase', 'requested_device', 'model_load_seconds',
            'audio_seconds', 'inference_seconds', 'error_type', 'error', 'exit_code',
            'npu_components_verified', 'live_tested', 'timeout_seconds')
    rows = ['# LocalScribe — 処理結果', '',
            '> ファイル認識候補の結果。ライブ入力・NPU性能の製品合格判定ではありません。', '']
    for key in keys:
        if key in state:
            value = json.dumps(state[key], ensure_ascii=False)
            rows.append('- ' + key + ': `' + value.replace('`', "'") + '`')
    rows += ['', '音声原本は変更していません。認識本文は transcript.md に別保存します。',
             '自動マスクは完全な匿名化を保証しません。共有前に内容を確認してください。', '']
    return '\n'.join(rows)
