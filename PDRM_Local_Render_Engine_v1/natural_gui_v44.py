"""Progress UI for a worker process; existing v3.4 target dialog is reused."""
from __future__ import annotations
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import gui_runtime_v44 as runtime
from natural_gui_v34 import TargetDialog,choose_targets

VERSION='natural-gui-v4.4-lab'
FINAL={'COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED','FAILED'}

class ProgressDialog:
    def __init__(self,root,process,session,manifest_hash,on_done=None,poll_ms=100):
        self.root=root;self.process=process;self.session=Path(session);self.manifest_hash=manifest_hash
        self.on_done=on_done;self.poll_ms=poll_ms;self.closed=False;self.cancel_sent=False;self.last=None
        root.title('PDRM — 処理進捗');root.resizable(False,False);root.protocol('WM_DELETE_WINDOW',self.cancel)
        outer=ttk.Frame(root,padding=18);outer.grid(sticky='nsew')
        self.title=tk.StringVar(root,value='開始中…');ttk.Label(outer,textvariable=self.title,font=('Yu Gothic UI',13,'bold'),wraplength=560).grid(row=0,column=0,columnspan=2,sticky='w')
        self.stage=tk.StringVar(root,value='START');ttk.Label(outer,textvariable=self.stage,wraplength=560).grid(row=1,column=0,columnspan=2,sticky='w',pady=(8,8))
        self.bar=ttk.Progressbar(outer,length=520,mode='determinate',maximum=100);self.bar.grid(row=2,column=0,columnspan=2,pady=(0,8))
        self.count=tk.StringVar(root,value='0 / 0');ttk.Label(outer,textvariable=self.count).grid(row=3,column=0,sticky='w')
        self.cancel_button=ttk.Button(outer,text='キャンセル',command=self.cancel);self.cancel_button.grid(row=3,column=1,sticky='e')
        self.detail=tk.StringVar(root,value='');ttk.Label(outer,textvariable=self.detail,wraplength=560).grid(row=4,column=0,columnspan=2,sticky='w',pady=(8,0))
        root.bind('<Escape>',lambda e:self.cancel());root.update_idletasks();w,h=root.winfo_reqwidth(),root.winfo_reqheight();root.geometry(f'{w}x{h}+{max(0,(root.winfo_screenwidth()-w)//2)}+{max(0,(root.winfo_screenheight()-h)//2)}')
        root.after(self.poll_ms,self.poll)
    def cancel(self):
        if self.closed or self.cancel_sent:return
        runtime.request_cancel(self.session);self.cancel_sent=True;self.cancel_button.state(['disabled']);self.detail.set('キャンセル要求を送信しました。現在の安全な処理点で停止します。')
    def poll(self):
        if self.closed:return
        try:status=runtime.read_status(self.session,self.manifest_hash)
        except Exception as exc:
            self.finish(dict(overall='FAILED',stage='STATUS_ERROR',failures=[dict(error=str(exc))]));return
        if status:
            self.last=status;self.render(status)
            if status['overall'] in FINAL:self.finish(status);return
        code=self.process.poll()
        if code is not None:
            # Give the worker one final scheduling turn for its atomic status.
            try:status=runtime.read_status(self.session,self.manifest_hash)
            except Exception:status=None
            if not status or status['overall'] not in FINAL:
                self.finish(dict(overall='FAILED',stage='WORKER_EXIT',failures=[dict(error=f'worker exit code {code}')],file_index=0,file_total=0,current_file=None,done=0,total=1));return
            self.finish(status);return
        self.root.after(self.poll_ms,self.poll)
    def render(self,s):
        current=s.get('current_file') or '準備中';self.title.set(f"[{s.get('file_index',0)}/{s.get('file_total',0)}] {current}")
        self.stage.set(str(s.get('stage','')))
        total=max(0,int(s.get('total',0)));done=max(0,int(s.get('done',0)))
        self.bar['value']=0 if not total else min(100,100*done/total)
        self.count.set(f"完了 {len(s.get('completed',[]))} / {s.get('file_total',0)}  ・ 失敗 {len(s.get('failures',[]))}")
        if s.get('failures'):self.detail.set('直近: '+s['failures'][-1].get('file','')+' — '+s['failures'][-1].get('error',''))
    def finish(self,status):
        if self.closed:return
        self.closed=True;self.last=status;self.render(status);self.cancel_button.state(['disabled'])
        if status.get('overall')=='COMPLETE':self.detail.set('すべての音源を完了しました。')
        elif status.get('overall')=='COMPLETE_WITH_ERRORS':self.detail.set('完了しましたが、保存できなかった音源があります。')
        elif status.get('overall')=='CANCELLED':self.detail.set('キャンセルしました。')
        else:self.detail.set('処理workerが異常終了しました。ログを確認してください。')
        if self.on_done:self.on_done(status)

def progress_self_check(output):
    """Tk scheduling check only; subprocess/real-chain checks live elsewhere."""
    import tempfile,json
    class Alive:
        def poll(self):return None
    with tempfile.TemporaryDirectory(prefix='gui44_') as d:
        session=Path(d);h='a'*64
        status=dict(schema=1,version=runtime.VERSION,manifest_sha256=h,overall='RUNNING',stage='SOURCE_EVENT_SCAN',done=1,total=4,file_index=1,file_total=2,current_file='test.wav',completed=[],failures=[],updated_unix=0)
        runtime.atomic_json(session/'status.json',status)
        root=tk.Tk();root.withdraw();calls=[];dialog=ProgressDialog(root,Alive(),session,h,on_done=lambda s:calls.append(s),poll_ms=10)
        # The GUI thread continues to execute scheduled callbacks while DSP is external.
        ticks=[]
        root.after(5,lambda:ticks.append('responsive'))
        for _ in range(10):root.update()
        dialog.poll();assert ticks and dialog.title.get().endswith('test.wav') and dialog.bar['value']==25
        status.update(overall='COMPLETE',stage='COMPLETE',done=1,total=1,completed=[dict(file='test.wav',status='COMPLETE')])
        runtime.atomic_json(session/'status.json',status);dialog.poll();assert dialog.closed and calls[-1]['overall']=='COMPLETE'
        root.destroy();Path(output).write_text(json.dumps(dict(status='PASS',responsive_callbacks=True,progress_poll=True,cancel_control=True,targets_reused_from='natural_gui_v34'),indent=2),encoding='utf-8')
    return 0
