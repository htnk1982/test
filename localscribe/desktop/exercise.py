"""Explicit developer exercise of real Tk buttons and the real packaged engine.

No OS input injection, process control, networking, audio recording or private
fixtures. This module is entered only with the --exercise command-line option.
"""
from pathlib import Path
import hashlib
import json
import time
import traceback
import unicodedata


def normalize(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if not c.isspace() and not unicodedata.category(c).startswith('P'))


def exercise(gui, fixture: Path, evidence: Path):
    evidence.mkdir(parents=True, exist_ok=True)
    gui.output.mkdir(parents=True, exist_ok=True)
    model = gui.model
    original = hashlib.sha256(fixture.read_bytes()).hexdigest()
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import math
    audio, rate = sf.read(fixture, dtype='float32')
    d = math.gcd(rate, 48000)
    converted = resample_poly(audio, 48000//d, rate//d) * 0.8
    stereo = gui.output / 'public_stereo.wav'
    sf.write(stereo, np.column_stack((converted, converted)), 48000, subtype='PCM_16')
    silence = gui.output / 'synthetic_silence.wav'
    sf.write(silence, np.zeros(16000, dtype='float32'), 16000)
    incomplete = gui.output / 'incomplete_model'
    incomplete.mkdir(exist_ok=True)
    cases = [('normal',fixture,model,'CPU','success'),
             ('stereo_48khz',stereo,model,'CPU','success'),
             ('cooperative_cancel',fixture,model,'CPU','cancelled'),
             ('save_obstruction',fixture,model,'CPU','failed'),
             ('missing_model',fixture,incomplete,'CPU','failed'),
             ('silence',silence,model,'CPU','failed'),
             ('unavailable_npu',fixture,model,'NPU','failed'),
             ('recovery',fixture,model,'CPU','success')]
    report = dict(outcome='running', checks=[], visible_gui=False, npu_tested=False,
                  live_tested=False, hard_timeout_tested=False, native_compile_cancel_supported=False,
                  operating_system_input_injection=False, button_invocation='Tk Button.invoke in actual event loop')
    index = -1
    saved = []
    ticks = 0
    last_tick = time.monotonic()
    max_gap = 0.0
    def persist():
        (evidence/'ui-result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    def fail(exc):
        report.update(outcome='failed', error=str(exc)[:4000], traceback=traceback.format_exc()[-8000:])
        persist()
        gui.on_event = None
        gui.close()
    def next_case():
        nonlocal index
        index += 1
        if index == len(cases):
            try:
                if hashlib.sha256(fixture.read_bytes()).hexdigest() != original:
                    raise AssertionError('Original fixture changed')
                for path, sha in saved:
                    if hashlib.sha256(path.read_bytes()).hexdigest() != sha:
                        raise AssertionError('Accepted transcript changed')
                report.update(outcome='passed', input_preserved=True, accepted_outputs_preserved=True,
                              event_loop_ticks=ticks, maximum_event_loop_gap_seconds=round(max_gap,3))
                persist()
                gui.on_event = None
                gui.close()
            except Exception as exc:
                fail(exc)
            return
        name,audio,model_path,device,expected = cases[index]
        gui.model = model_path
        gui.device.set(device)
        gui.audio.set(str(audio))
        if str(gui.start_button.cget('state')) == 'disabled':
            fail(AssertionError('Start remained disabled between jobs'))
            return
        gui.start_button.invoke()
        if gui.thread is None:
            fail(AssertionError('Real Start callback did not start a job'))
    def event(event):
        try:
            name,audio,model_path,device,expected = cases[index]
            if event[0] == 'phase':
                if name == 'cooperative_cancel' and event[1] == 'transcribe':
                    gui.cancel_button.invoke()
                if name == 'save_obstruction' and event[1] == 'transcribe':
                    (event[2]/'transcript.md').mkdir()
                return
            state,directory,text = event[1:]
            if state['outcome'] != expected:
                raise AssertionError(name + ': ' + json.dumps(state,ensure_ascii=False))
            if expected == 'success':
                target = directory/'transcript.md'
                body = target.read_text(encoding='utf-8')
                reference = normalize('水をマレーシアから買わなくてはならないのです。')
                if reference not in normalize(body):
                    raise AssertionError('Known Japanese fixture mismatch')
                if gui.text.get('1.0','end').strip() != body.strip():
                    raise AssertionError('Visible text does not match saved Markdown')
                saved.append((target,hashlib.sha256(target.read_bytes()).hexdigest()))
            if name == 'cooperative_cancel' and (directory/'transcript.md').exists():
                raise AssertionError('Cancelled result was exported as accepted transcript')
            if name == 'save_obstruction' and state['phase'] != 'transcript_save':
                raise AssertionError('First save failure was misclassified')
            if name == 'missing_model' and state['phase'] != 'model_verify':
                raise AssertionError('Incomplete model reached native code')
            if name == 'silence' and state['phase'] != 'audio_read':
                raise AssertionError('Silence reached inference')
            if name == 'unavailable_npu' and 'unavailable' not in state.get('error',''):
                raise AssertionError('Unavailable device failure was not explicit')
            report['checks'].append(dict(name=name, outcome=state['outcome'], phase=state['phase'],
                                         inference_seconds=state.get('inference_seconds')))
            persist()
            gui.root.after(100,next_case)
        except Exception as exc:
            fail(exc)
    def heartbeat():
        nonlocal ticks,last_tick,max_gap
        now=time.monotonic()
        max_gap=max(max_gap,now-last_tick)
        last_tick=now
        ticks += 1
        gui.root.after(50,heartbeat)
    def begin():
        try:
            report['visible_gui'] = bool(gui.root.winfo_viewable())
            if not report['visible_gui']:
                raise AssertionError('Actual GUI was not mapped on Windows')
            gui.on_event=event
            next_case()
        except Exception as exc:
            fail(exc)
    persist()
    gui.root.after(50,heartbeat)
    gui.root.after(500,begin)
