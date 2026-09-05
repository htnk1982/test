"""Portable Windows entry; changes resource discovery only, never DSP rules."""
from __future__ import annotations
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sys
import time
import traceback

APP_VERSION = '2.1.1-exe'
MODULES = ('processed_finish', 'distribution_finish', 'distribution_peak',
           'accepted_finish', 'note_sub_lab', 'note_sub_lab_v02',
           'hf_temporal_contrast_lab')


class Tee:
    def __init__(self, terminal, log):
        self.terminal, self.log = terminal, log
    def write(self, value):
        if self.terminal is not None:
            self.terminal.write(value)
        self.log.write(value); self.log.flush()
        return len(value)
    def flush(self):
        if self.terminal is not None:
            self.terminal.flush()
        self.log.flush()
    def isatty(self):
        return False


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def bootstrap():
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).parent)).resolve()
    manifest = json.loads((root / 'BUNDLE_MANIFEST.json').read_text(encoding='utf-8'))
    for name, expected in manifest['resources'].items():
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file() or sha(path) != expected:
            raise RuntimeError('同梱ファイルが不足または変更されています。ZIPを別フォルダへ展開し直してください: ' + name)
    ff = root / 'native' / 'ffmpeg.exe'
    if not ff.is_file():
        raise RuntimeError('同梱FFmpegが見つかりません。EXEだけを取り出さずフォルダ全体を使用してください。')
    os.environ['IMAGEIO_FFMPEG_EXE'] = str(ff)
    os.environ['PATH'] = str(ff.parent) + os.pathsep + os.environ.get('PATH', '')
    os.environ['NoDefaultCurrentDirectoryInExePath'] = '1'
    import note_sub_lab as io
    # Pin only resource discovery; never replace the audio-processing functions.
    io.ffmpeg_path = lambda: str(ff)
    import processed_finish as app
    app.engine.legacy.verify_dsp()
    app.engine.peak.check_ffmpeg(str(ff))
    return app, manifest


def validate_magic(paths):
    for value in paths:
        p = Path(value)
        if not p.is_file():
            raise ValueError('音源が見つかりません: ' + str(p))
        with p.open('rb') as f:
            head = f.read(12)
        ext = p.suffix.lower()
        valid = (ext == '.flac' and head[:4] == b'fLaC') or (
            ext == '.wav' and head[:4] in (b'RIFF', b'RF64', b'RIFX') and head[8:12] == b'WAVE')
        if not valid:
            raise ValueError('WAV/FLACの形式ヘッダーが一致しません: ' + p.name)


def run(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    pause = '--no-pause' not in args
    args = [a for a in args if a != '--no-pause']
    no_open = '--no-open' in args
    args = [a for a in args if a != '--no-open']
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    logs = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'exe_logs'
    logs.mkdir(parents=True, exist_ok=True)
    logpath = logs / (time.strftime('%Y%m%d_%H%M%S') + '_' + str(os.getpid()) + '.log')
    original_out, original_err = sys.stdout, sys.stderr
    result = 1
    with logpath.open('w', encoding='utf-8') as log:
        sys.stdout, sys.stderr = Tee(original_out, log), Tee(original_err, log)
        try:
            print('PDRM 配信用仕上げ ' + APP_VERSION, flush=True)
            print('元のWAV/FLAC → 同じフォルダのprocessedへ同名WAV・MP3。原音は変更しません。', flush=True)
            app, manifest = bootstrap()
            if args[:1] == ['--bundle-check']:
                if len(args) != 2:
                    raise ValueError('--bundle-check requires a JSON output path')
                import tkinter as tk
                import importlib.metadata as md
                window = tk.Tk(); window.withdraw(); window.update(); window.destroy()
                record = dict(status='PASS', frozen=bool(getattr(sys, 'frozen', False)),
                              python=sys.version, executable=sys.executable,
                              ffmpeg=app.io.ffmpeg_path(), manifest=manifest,
                              versions={n: md.version(n) for n in ('numpy','scipy','soundfile','pyloudnorm')},
                              tkinter='created_and_destroyed')
                Path(args[1]).write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding='utf-8')
                return 0
            sources = app.choose_sources(args)
            if not sources:
                print('中止しました。原音は変更していません。')
                return 0
            validate_magic(sources)
            app.choose_sources = lambda ignored: sources
            if no_open and os.name == 'nt':
                app.os.startfile = lambda *a, **k: None
            result = app.main([str(p) for p in sources])
            print('完了しました。' if result == 0 else '保存できなかった音源があります。上の表示を確認してください。', flush=True)
        except KeyboardInterrupt:
            print('中断しました。再実行では元音源を選んでください。'); result = 130
        except Exception:
            traceback.print_exc(); result = 1
        finally:
            print('実行ログ:', logpath, flush=True)
            sys.stdout, sys.stderr = original_out, original_err
    if pause and sys.stdin is not None and sys.stdin.isatty():
        try:
            input('Enterキーで閉じます。')
        except (EOFError, KeyboardInterrupt):
            pass
    return result


if __name__ == '__main__':
    multiprocessing.freeze_support()
    raise SystemExit(run())
