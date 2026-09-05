"""Minimal single-process file GUI. No process launcher, OS control or network.

This is a developer integration candidate. Cancellation is cooperative: native
model compilation cannot be interrupted from this window. Do not use this
candidate for a target-NPU acceptance requiring a hard time limit.
"""
from __future__ import annotations
from pathlib import Path
import argparse
import json
import math
import queue
import sys
import threading
import time
import traceback
import uuid
import tkinter as tk
from tkinter import ttk, filedialog
from desktop.local_io import atomic_text, write_json, report_markdown, public_error
from desktop.model_guard import verify_model

VERSION = '0.4.0-file-gui-dev'


class FileWindow:
    def __init__(self, root, model: Path, output: Path):
        self.root, self.model, self.output = root, model, output
        self.queue = queue.Queue()
        self.thread = None
        self.cancelled = threading.Event()
        self.last = None
        self.closing = False
        self.on_event = None
        root.title('LocalScribe — 同梱GUI開発候補')
        root.geometry('820x550')
        self.audio = tk.StringVar()
        self.device = tk.StringVar(value='CPU')
        self.status = tk.StringVar(value='30秒以内の音声ファイルを選択してください。')
        box = ttk.Frame(root, padding=16)
        box.pack(fill='both', expand=True)
        ttk.Label(box, text='LocalScribe — ファイル文字起こし', font=('Yu Gothic UI', 16)).pack(anchor='w')
        ttk.Label(box, text='開発候補：ライブ入力なし。NPU未検証。中止は安全な区切りまで待機します。').pack(anchor='w', pady=8)
        self.entry = ttk.Entry(box, textvariable=self.audio)
        self.entry.pack(fill='x', pady=8)
        row = ttk.Frame(box)
        row.pack(fill='x')
        self.select = ttk.Button(row, text='音声を選択', command=self.pick)
        self.select.pack(side='left')
        self.combo = ttk.Combobox(row, textvariable=self.device, values=['CPU','NPU','GPU'], width=8, state='readonly')
        self.combo.pack(side='left', padx=8)
        self.start_button = ttk.Button(row, text='開始', command=self.start)
        self.start_button.pack(side='left', padx=8)
        self.cancel_button = ttk.Button(row, text='中止を予約', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='left', padx=8)
        ttk.Label(box, text='保存先：' + str(output), wraplength=760).pack(anchor='w', pady=8)
        self.text = tk.Text(box, wrap='word', height=14)
        self.text.pack(fill='both', expand=True)
        self.text.configure(state='disabled')
        ttk.Label(box, textvariable=self.status, wraplength=760).pack(fill='x', pady=8)
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(50, self.poll)

    def pick(self):
        path = filedialog.askopenfilename(filetypes=[('音声', '*.wav *.flac')])
        if path:
            self.audio.set(path)

    def start(self):
        if self.thread:
            return
        try:
            audio = Path(self.audio.get()).resolve(strict=True)
            if not audio.is_file():
                raise ValueError('音声ファイルを選択してください。')
            self.output.mkdir(parents=True, exist_ok=True)
            directory = self.output / (time.strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:8])
            directory.mkdir()
            # Prove output is writable before native model work.
            atomic_text(directory / 'result.md', '# 処理中\n')
        except Exception as exc:
            self.status.set('開始できません：' + str(exc))
            return
        self.cancelled.clear()
        self.last = None
        device = self.device.get()
        self.start_button.configure(state='disabled')
        self.select.configure(state='disabled')
        self.combo.configure(state='disabled')
        self.cancel_button.configure(state='normal')
        self.thread = threading.Thread(target=self.work, args=(audio, directory, device), daemon=False)
        self.thread.start()

    def work(self, audio, directory, device):
        state = dict(version=VERSION, outcome='running', phase='audio_read', requested_device=device,
                     live_tested=False, npu_components_verified=False)
        text = ''
        def phase(name):
            state['phase'] = name
            self.queue.put(('phase', name, directory))
            if self.cancelled.is_set():
                raise InterruptedError('Cancelled at a safe boundary')
        try:
            phase('audio_read')
            import numpy as np
            import soundfile as sf
            from scipy.signal import resample_poly
            info = sf.info(str(audio))
            if not 0.1 <= info.duration <= 30 or info.channels not in (1,2):
                raise ValueError('AUDIO_SCOPE: 0.1 to 30 seconds, mono or stereo')
            samples, rate = sf.read(str(audio), dtype='float32', always_2d=True)
            samples = samples.mean(axis=1)
            if not np.isfinite(samples).all() or np.max(np.abs(samples)) > 1.01:
                raise ValueError('AUDIO_INVALID')
            if np.max(np.abs(samples)) < 0.0001:
                raise ValueError('AUDIO_SILENCE')
            d = math.gcd(int(rate), 16000)
            if rate != 16000:
                samples = resample_poly(samples, 16000//d, rate//d)
            state['audio_seconds'] = len(samples)/16000
            phase('model_verify')
            verify_model(self.model)
            phase('model_load')
            from core.whisper_engine import WhisperEngine
            t = time.perf_counter()
            engine = WhisperEngine(self.model, device)
            state['model_load_seconds'] = time.perf_counter() - t
            phase('transcribe')
            result = engine.transcribe(samples.tolist(), 'ja')
            state['inference_seconds'] = result.inference_seconds
            phase('transcript_save')
            text = '# 文字起こし\n\n> 自動認識・人手未確認。\n\n' + result.text + '\n'
            atomic_text(directory / 'transcript.md', text)
            if (directory / 'transcript.md').read_text(encoding='utf-8') != text:
                raise OSError('TRANSCRIPT_READBACK_MISMATCH')
            state.update(outcome='success', phase='complete')
        except InterruptedError:
            state.update(outcome='cancelled')
        except Exception as exc:
            state.update(outcome='failed', error_type=type(exc).__name__,
                         error=public_error(exc, [audio, directory, self.model]))
            try:
                atomic_text(directory / '_private_error.txt', traceback.format_exc())
            except OSError:
                state['private_error_save_failed'] = True
        for action in (lambda: write_json(directory / 'state.json', state),
                       lambda: atomic_text(directory / 'result.md', report_markdown(state))):
            try:
                action()
            except OSError:
                state['evidence_save_failed'] = True
        self.queue.put(('done', state, directory, text))

    def cancel(self):
        self.cancelled.set()
        self.status.set('中止を予約しました。現在のモデル処理が戻り次第、結果を保全して停止します。')

    def close(self):
        if self.thread:
            self.closing = True
            self.cancel()
        else:
            self.root.destroy()

    def poll(self):
        try:
            while True:
                event = self.queue.get_nowait()
                if event[0] == 'phase':
                    if not self.cancelled.is_set():
                        self.status.set('処理中：' + event[1])
                else:
                    self.thread.join()
                    self.thread = None
                    state, directory, text = event[1:]
                    self.last = state
                    label = {'success':'完了', 'failed':'失敗', 'cancelled':'中止'}[state['outcome']]
                    self.status.set(label + '：' + str(directory))
                    self.text.configure(state='normal')
                    self.text.delete('1.0','end')
                    self.text.insert('1.0', text if state['outcome']=='success' else label + '\n' + state.get('error',''))
                    self.text.configure(state='disabled')
                    self.start_button.configure(state='normal')
                    self.select.configure(state='normal')
                    self.combo.configure(state='readonly')
                    self.cancel_button.configure(state='disabled')
                if self.on_event:
                    self.on_event(event)
                if self.closing and self.thread is None:
                    self.root.destroy()
                    return
        except queue.Empty:
            pass
        self.root.after(50, self.poll)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exercise', type=Path, help='Developer-only public-fixture exercise')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    base = Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    root = tk.Tk()
    gui = FileWindow(root, base/'models', args.output or Path.home()/'Documents'/'LocalScribe')
    if args.exercise:
        if not args.evidence:
            raise ValueError('An explicit developer evidence directory is required')
        from desktop.exercise import exercise
        exercise(gui, args.exercise, args.evidence)
    root.mainloop()
    if args.exercise:
        result = json.loads((args.evidence/'ui-result.json').read_text(encoding='utf-8'))
        return 0 if result['outcome']=='passed' else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
