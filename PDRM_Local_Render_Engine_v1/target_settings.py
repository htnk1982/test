"""Validated immutable output targets; no changes to the adopted sound stages."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import json
import math
import os
import tempfile
import unicodedata

@dataclass(frozen=True)
class Targets:
    wav_lufs: float = -12.0
    wav_tp: float = -2.0
    mp3_lufs: float = -14.0
    mp3_tp: float = -2.0

    def validate(self):
        for name, value in asdict(self).items():
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
                raise ValueError(f'{name}: 有限の数値を入力してください。')
            lower, upper = (-30.0, -8.0) if name.endswith('lufs') else (-12.0, -1.0)
            if not lower <= value <= upper:
                label = 'LUFS' if name.endswith('lufs') else 'True Peak上限 (dBTP)'
                raise ValueError(f'{name[:3].upper()} {label}: {lower:g}〜{upper:g}の範囲で指定してください。')
        return self

    def to_dict(self):
        self.validate()
        return {key: float(value) for key, value in asdict(self).items()}

    @classmethod
    def from_fields(cls, fields):
        expected = set(asdict(cls()))
        if set(fields) != expected:
            raise ValueError('WAV/MP3のLUFS・TPの4項目が必要です。')
        values = {}
        for key, value in fields.items():
            if isinstance(value, bool):
                raise ValueError('数値を入力してください。')
            text = unicodedata.normalize('NFKC', str(value)).replace('−', '-').strip()
            try:
                values[key] = float(text)
            except (ValueError, TypeError):
                raise ValueError(f'{key}: 数値を入力してください。') from None
        return cls(**values).validate()


def settings_path():
    base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'.local/share')))
    return base/'PDRM_Local_Render_Engine_v1'/'gui_v2_2'/'settings.json'


def load_settings(path=None):
    path = Path(path) if path is not None else settings_path()
    if not path.exists():
        return Targets(), ''
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('schema') != 1:
            raise ValueError('Unknown settings schema')
        return Targets.from_fields(data['targets']), ''
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return Targets(), '保存設定を読み込めませんでした。初期値を表示しています。'


def save_settings(targets, path=None):
    values = targets.to_dict()
    path = Path(path) if path is not None else settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.settings_', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(dict(schema=1, targets=values), f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
