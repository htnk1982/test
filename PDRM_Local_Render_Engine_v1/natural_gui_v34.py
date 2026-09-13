"""v3.4 GUI: output targets only; peak method remains automatic."""
from __future__ import annotations
from pathlib import Path
import json,tkinter as tk
from tkinter import ttk
from target_settings import (
    Targets,load_settings,save_settings,settings_path,
    LUFS_MIN,LUFS_MAX,LUFS_STEP,TP_MIN,TP_MAX,
)

class TargetDialog:
    def __init__(self,root,initial=None,warning='',*,settings_file=None):
        self.root=root;self.settings_file=settings_file or settings_path().parent.parent/'gui_oppo_v34'/'settings.json';self.result=None;self.variables={}
        root.title('PDRM AUTO v3.4 — WAV / MP3 出力設定');root.resizable(False,False);root.protocol('WM_DELETE_WINDOW',self.cancel)
        outer=ttk.Frame(root,padding=20);outer.grid(sticky='nsew')
        ttk.Label(outer,text='自動安全判定・出力条件',font=('Yu Gothic UI',15,'bold')).grid(row=0,column=0,columnspan=3,sticky='w',pady=(0,10))
        ttk.Label(outer,text='Gain-only → OPPO → 必要時のみリミッター。長文脈OPPOは変更可能領域だけを高速計算します。',wraplength=570).grid(row=1,column=0,columnspan=3,sticky='w',pady=(0,16))
        for c,label in enumerate(('出力','全曲ラウドネス (LUFS-I)','True Peak上限 (dBTP)')):ttk.Label(outer,text=label).grid(row=2,column=c,sticky='w',padx=(0,14),pady=(0,7))
        initial=initial or Targets()
        for row,(label,prefix) in enumerate((('WAV / 24-bit','wav'),('MP3 / 320kbps','mp3')),3):
            ttk.Label(outer,text=label).grid(row=row,column=0,sticky='w',padx=(0,18),pady=8)
            for col,suffix in ((1,'lufs'),(2,'tp')):
                key=prefix+'_'+suffix;var=tk.StringVar(root,value=f'{getattr(initial,key):g}');self.variables[key]=var
                if suffix=='lufs':lo,hi,step=LUFS_MIN,LUFS_MAX,LUFS_STEP
                else:lo,hi,step=TP_MIN,TP_MAX,.1
                ctl=ttk.Spinbox(outer,textvariable=var,from_=lo,to=hi,increment=step,format='%.1f',width=16);ctl.grid(row=row,column=col,sticky='w',padx=(0,14),pady=8,ipady=3)
                if key=='wav_lufs':self.first=ctl
        ttk.Label(outer,text='難しいピーク処理中は OPPO_CONTEXT_SOLVE_###MS と反復進捗を表示します。',wraplength=570).grid(row=5,column=0,columnspan=3,sticky='w',pady=(10,3))
        ttk.Label(outer,text='破損・I/O異常・ソース変更・非有限値・キャンセル等ではリミッターへ逃げず、その曲を停止します。',wraplength=570).grid(row=6,column=0,columnspan=3,sticky='w',pady=(0,10))
        self.replace=tk.BooleanVar(root,value=False);ttk.Checkbutton(outer,text='既存のPDRM出力を退避して、同じ名前で作り直す',variable=self.replace).grid(row=7,column=0,columnspan=3,sticky='w')
        ttk.Label(outer,text='手動編集ファイルと元音源は自動置換しません。').grid(row=8,column=0,columnspan=3,sticky='w',pady=(4,10))
        self.error=tk.StringVar(root,value=warning);ttk.Label(outer,textvariable=self.error,wraplength=570,foreground='#a12b2b').grid(row=9,column=0,columnspan=3,sticky='w',pady=(0,10))
        buttons=ttk.Frame(outer);buttons.grid(row=10,column=0,columnspan=3,sticky='ew');buttons.columnconfigure(1,weight=1)
        ttk.Button(buttons,text='初期値に戻す',command=self.reset).grid(row=0,column=0);ttk.Button(buttons,text='キャンセル',command=self.cancel).grid(row=0,column=2,padx=(20,8));ttk.Button(buttons,text='この設定で開始',command=self.submit).grid(row=0,column=3)
        ttk.Label(outer,text='LUFS −30〜−8（0.5 dB刻み） / TP上限 −12〜−0.5 dBTP。設定は次回も記憶します。').grid(row=11,column=0,columnspan=3,sticky='w',pady=(12,0))
        root.bind('<Escape>',lambda e:self.cancel());root.bind('<Return>',lambda e:self.submit());root.update_idletasks();w,h=root.winfo_reqwidth(),root.winfo_reqheight();root.geometry(f'{w}x{h}+{max(0,(root.winfo_screenwidth()-w)//2)}+{max(0,(root.winfo_screenheight()-h)//2)}');self.first.focus_set()
    def collect(self):return Targets.from_fields({k:v.get() for k,v in self.variables.items()})
    def reset(self):
        for k,v in Targets().to_dict().items():self.variables[k].set(f'{v:g}')
        self.error.set('')
    def submit(self):
        try:t=self.collect();save_settings(t,self.settings_file)
        except (ValueError,OSError) as exc:self.error.set(str(exc));return
        self.result=(t,bool(self.replace.get()),'auto_safe');self.root.destroy()
    def cancel(self):self.result=None;self.root.destroy()

def choose_targets():
    config=settings_path().parent.parent/'gui_oppo_v34'/'settings.json';t,w=load_settings(config);root=tk.Tk();d=TargetDialog(root,t,w,settings_file=config);root.mainloop();return d.result

def self_check(destination):
    dest=Path(destination);settings=dest.with_suffix('.settings.json');root=tk.Tk();d=TargetDialog(root,settings_file=settings);root.update();expected=dict(wav_lufs=-15.5,wav_tp=-0.5,mp3_lufs=-16.5,mp3_tp=-3.5)
    for k,v in expected.items():d.variables[k].set(str(v))
    assert d.collect().to_dict()==expected
    d.variables['wav_lufs'].set('-15.2');d.submit();assert d.result is None and '0.5' in d.error.get() and not settings.exists()
    d.variables['wav_lufs'].set('-15.5');d.variables['wav_tp'].set('-0.4');d.submit();assert d.result is None and d.error.get() and not settings.exists()
    d.variables['wav_tp'].set('-0.5');d.replace.set(True);d.submit();assert d.result[0].to_dict()==expected and d.result[1] and d.result[2]=='auto_safe'
    loaded,w=load_settings(settings);assert not w and loaded.to_dict()==expected
    dest.write_text(json.dumps(dict(status='PASS',targets=expected,automatic_policy='GAIN_ONLY_OPPO_LIMITER',execution='SPARSE_EXACT_CONTEXT',checks=['4 target fields','LUFS 0.5 dB grid','TP max -0.5 dBTP','no manual peak-mode selection','invalid blocked','settings remembered']),indent=2),encoding='utf-8');settings.unlink(missing_ok=True);return 0
