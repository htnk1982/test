"""Small pre-render target dialog. Audio starts only after validated confirmation."""
from __future__ import annotations
from pathlib import Path
import json
import tkinter as tk
from tkinter import ttk
from target_settings import Targets, load_settings, save_settings


class TargetDialog:
    def __init__(self, root, initial=None, warning='', *, settings_file=None):
        self.root = root
        self.settings_file = settings_file
        self.result = None
        self.variables = {}
        self.root.title('PDRM — WAV / MP3 出力設定')
        self.root.resizable(False, False)
        self.root.protocol('WM_DELETE_WINDOW', self.cancel)
        outer = ttk.Frame(root, padding=20)
        outer.grid(sticky='nsew')
        ttk.Label(outer, text='配信用の音量・ピーク上限', font=('Yu Gothic UI', 15, 'bold')).grid(
            row=0, column=0, columnspan=3, sticky='w', pady=(0,12))
        ttk.Label(outer, text='音作りは固定。WAVとMP3の書き出し条件を個別に指定します。').grid(
            row=1, column=0, columnspan=3, sticky='w', pady=(0,18))
        for col, label in enumerate(('出力', '全曲ラウドネス (LUFS-I)', 'True Peak上限 (dBTP)')):
            ttk.Label(outer, text=label).grid(row=2, column=col, sticky='w', padx=(0,14), pady=(0,7))
        initial = initial or Targets()
        for row, (label, prefix) in enumerate((('WAV / 24-bit', 'wav'), ('MP3 / 320kbps', 'mp3')), 3):
            ttk.Label(outer, text=label).grid(row=row, column=0, sticky='w', padx=(0,18), pady=8)
            for col, suffix in ((1,'lufs'),(2,'tp')):
                key = prefix+'_'+suffix
                var = tk.StringVar(root, value=f'{getattr(initial,key):g}')
                self.variables[key] = var
                lower,upper=(-30,-8) if suffix=='lufs' else (-12,-1)
                control = ttk.Spinbox(outer, textvariable=var, from_=lower, to=upper,
                                      increment=.1, format='%.1f', width=16)
                control.grid(row=row,column=col,sticky='w',padx=(0,14),pady=8,ipady=3)
                if key=='wav_lufs': self.first = control
        ttk.Label(outer, text='指定範囲：LUFS −30〜−8 ／ TP上限 −12〜−1 dBTP').grid(
            row=5,column=0,columnspan=3,sticky='w',pady=(8,4))
        ttk.Label(outer, text='TPは上限です。MP3の指定条件によっては、MP3側だけ追加ピーク処理を行います。',
                  wraplength=535).grid(row=6,column=0,columnspan=3,sticky='w',pady=(0,12))
        self.replace = tk.BooleanVar(root, value=False)
        ttk.Checkbutton(outer,text='既存のPDRM出力を退避して、同じ名前で作り直す',
                        variable=self.replace).grid(row=7,column=0,columnspan=3,sticky='w')
        ttk.Label(outer,text='手動で編集したファイルは置換しません。元音源は常に保持します。',
                  wraplength=535).grid(row=8,column=0,columnspan=3,sticky='w',pady=(4,10))
        self.error = tk.StringVar(root, value=warning)
        ttk.Label(outer,textvariable=self.error,wraplength=535,foreground='#a12b2b').grid(
            row=9,column=0,columnspan=3,sticky='w',pady=(0,12))
        buttons=ttk.Frame(outer);buttons.grid(row=10,column=0,columnspan=3,sticky='ew')
        buttons.columnconfigure(1,weight=1)
        ttk.Button(buttons,text='初期値に戻す',command=self.reset).grid(row=0,column=0)
        ttk.Button(buttons,text='キャンセル',command=self.cancel).grid(row=0,column=2,padx=(20,8))
        ttk.Button(buttons,text='この設定で開始',command=self.submit).grid(row=0,column=3)
        ttk.Label(outer,text='設定を次回も記憶します。保存先：元フォルダ / processed / 元の名前.wav・mp3').grid(
            row=11,column=0,columnspan=3,sticky='w',pady=(14,0))
        root.bind('<Escape>',lambda event:self.cancel())
        root.bind('<Return>',lambda event:self.submit())
        root.update_idletasks()
        w,h=root.winfo_reqwidth(),root.winfo_reqheight()
        root.geometry(f'{w}x{h}+{max(0,(root.winfo_screenwidth()-w)//2)}+{max(0,(root.winfo_screenheight()-h)//2)}')
        self.first.focus_set()

    def collect(self):
        return Targets.from_fields({k:v.get() for k,v in self.variables.items()})

    def reset(self):
        for key,value in Targets().to_dict().items(): self.variables[key].set(f'{value:g}')
        self.error.set('')

    def submit(self):
        try:
            targets=self.collect()
            save_settings(targets,self.settings_file)
        except (ValueError,OSError) as exc:
            self.error.set(str(exc));return
        self.result=(targets,bool(self.replace.get()))
        self.root.destroy()

    def cancel(self):
        self.result=None
        self.root.destroy()


def choose_targets():
    targets,warning=load_settings()
    root=tk.Tk()
    dialog=TargetDialog(root,targets,warning)
    root.mainloop()
    return dialog.result


def self_check(destination):
    """Exercise actual Tk variables, validation, submit, persistence and cancel."""
    dest=Path(destination); settings=dest.with_suffix('.settings.json')
    root=tk.Tk();dialog=TargetDialog(root,settings_file=settings)
    root.update()
    expected=dict(wav_lufs=-15.5,wav_tp=-2.5,mp3_lufs=-16.5,mp3_tp=-3.5)
    for key,value in expected.items(): dialog.variables[key].set(str(value))
    assert dialog.collect().to_dict()==expected
    dialog.variables['wav_lufs'].set('NaN');dialog.submit()
    assert dialog.result is None and dialog.error.get() and not settings.exists()
    dialog.variables['wav_lufs'].set('-15.5');dialog.replace.set(True);dialog.submit()
    assert dialog.result[0].to_dict()==expected and dialog.result[1]
    loaded,warning=load_settings(settings);assert not warning and loaded.to_dict()==expected
    before=settings.read_bytes()
    root=tk.Tk();dialog=TargetDialog(root,loaded,settings_file=settings)
    root.update();dialog.reset();assert dialog.collect()==Targets();dialog.cancel()
    assert dialog.result is None and settings.read_bytes()==before
    dest.write_text(json.dumps(dict(status='PASS',targets=expected,
        checks=['4 editable fields','invalid entry blocked','submit and remember','reset','cancel preserves settings']),indent=2),encoding='utf-8')
    settings.unlink(missing_ok=True)
    return 0
