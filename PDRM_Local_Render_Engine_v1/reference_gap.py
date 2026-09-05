"""Read-only C/reference descriptive comparison. No mastering or quality scoring.

Uses 30-second analysis blocks, each analytically anchored to -14 LUFS.
This is NOT per-track platform normalization and NOT a track-segmenter.
All audio stays local. No audio is written. Existing DSP/runtime are not imported.
"""
from __future__ import annotations

from pathlib import Path
from contextlib import contextmanager
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
import tempfile
import threading
import time
import traceback
import warnings

import numpy as np
import soundfile as sf
import pyloudnorm as pyln
from scipy import signal
from scipy.ndimage import maximum_filter1d, uniform_filter1d

VERSION = "reference-gap-1.0"
KNOWN_WINNER_SHA256 = "ee2df798b8a3096bba078968c0db9e953769a42924f717de02f9107936e4e7d1"
BANDS = ((20,60),(60,110),(110,250),(250,500),(500,1200),(1200,4000),
         (4000,8000),(8000,12000),(12000,16000),(16000,20000))
EPS = 1e-24
CONFIG = {"block_seconds":30.0,"minimum_block_seconds":10.0,"analysis_anchor_lufs":-14.0,
          "spectrogram_window_seconds":0.080,"spectrogram_hop_seconds":0.020,
          "active_range_db":40.0,"band_presence_floor_below_fullband_db":60.0,
          "occupancy_below_band_p90_db":6.0,"bands_hz":BANDS}


def json_bytes(obj):
    return json.dumps(obj,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(",",":")).encode("utf-8")


def object_hash(obj):
    return hashlib.sha256(json_bytes(obj)).hexdigest()


def sha256_file(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as f:
        for b in iter(lambda:f.read(4*1024*1024),b""):
            h.update(b)
    return h.hexdigest()


def atomic_json(path, obj):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=".gap_",suffix=".tmp",dir=str(path.parent))
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(json_bytes(obj)); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


@contextmanager
def exclusive_lock(path):
    f=Path(path).open("a+b")
    try:
        if os.fstat(f.fileno()).st_size==0:
            f.write(b"0"); f.flush()
        f.seek(0)
        if os.name=="nt":
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError as e:
        f.close()
        raise RuntimeError("This comparison is already running. Do not start a second copy.") from e
    try:
        yield
    finally:
        f.close()  # OS releases lock even after hard termination; keep lock inode.


class Progress:
    def __init__(self,path=None):
        self.path=path; self.stage="START"; self.done=0; self.total=0
        self.started=time.monotonic(); self.last_step=self.started
        self.stop=threading.Event(); self.error=None
        self.thread=threading.Thread(target=self._loop,daemon=True)
    def set(self,stage,done=0,total=0):
        self.stage=stage; self.done=done; self.total=total; self.last_step=time.monotonic()
    def _loop(self):
        while not self.stop.wait(2.0):
            data={"stage":self.stage,"done":self.done,"total":self.total,
                  "elapsed_seconds":round(time.monotonic()-self.started,1),
                  "seconds_since_step":round(time.monotonic()-self.last_step,1)}
            try:
                if self.path: atomic_json(self.path,data)
                print(f"[{data['stage']}] {self.done}/{self.total} elapsed={data['elapsed_seconds']}s step_age={data['seconds_since_step']}s",flush=True)
            except Exception as exc:
                self.error=repr(exc); return
    def __enter__(self): self.thread.start(); return self
    def __exit__(self,*args): self.stop.set(); self.thread.join(timeout=5)


def dbpower(x):
    return 10.0*np.log10(np.maximum(x,EPS))


def estimate_tp(x,sr):
    peak=0.0; width=int(sr*2); pad=128
    for start in range(0,len(x),width):
        end=min(len(x),start+width); a=max(0,start-pad); b=min(len(x),end+pad)
        up=signal.resample_poly(x[a:b],4,1,axis=0,window=("kaiser",8.6))
        core=up[(start-a)*4:(end-a)*4]
        peak=max(peak,float(np.max(np.abs(core))))
    return float(20*np.log10(max(peak,1e-12)))


def block_metrics(audio,sr):
    """All levels before anchor are measured; anchor is an analytical constant gain.

    Spectral energy is the mean of separate L/R powers, never power of (L+R)/2.
    Time-window metrics use sample-rate-derived durations, not 44-sample ms bins.
    Empty/silent bands have null relative-occupancy features, not invented density.
    """
    x=np.asarray(audio,dtype=np.float64)
    if x.ndim!=2 or x.shape[1]!=2: raise ValueError("Stereo input is required")
    if int(sr)<44100: raise ValueError("Use a 44.1 kHz or higher source")
    if len(x)<int(sr*0.5): raise ValueError("Analysis block too short")
    if not np.all(np.isfinite(x)): raise ValueError("Non-finite audio sample")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore",RuntimeWarning)
        lufs=float(pyln.Meter(sr).integrated_loudness(x))
    if not math.isfinite(lufs) or lufs < -60:
        return {"included":False,"reason":"silence_or_below_minus60_lufs","features":{}}
    anchor=float(CONFIG["analysis_anchor_lufs"]-lufs)
    tp=estimate_tp(x,sr)
    feat={"block_plr_tp_db":tp-lufs,"tp_at_analysis_anchor_dbtp_estimate":tp+anchor}
    power=np.mean(x*x,axis=1)
    peaks=np.max(np.abs(x),axis=1)
    hop=max(1,int(round(sr*0.01)))
    for milliseconds in (100,400):
        win=max(2,int(round(sr*milliseconds/1000.0)))
        select=slice(win//2,len(x)-win//2,hop)
        p=uniform_filter1d(power,size=win,mode="constant")[select]
        pk=maximum_filter1d(peaks,size=win,mode="constant")[select]
        active=p>max(float(np.max(p))*1e-4,EPS)
        cr=20*np.log10((pk[active]+1e-12)/np.sqrt(p[active]+EPS))
        for q in (50,95): feat[f"crest_{milliseconds}ms_p{q}_db"]=float(np.percentile(cr,q))
    win3=int(round(sr*3)); hop3=int(round(sr))
    if len(x)>=win3:
        p3=uniform_filter1d(power,size=win3,mode="constant")[win3//2:len(x)-win3//2+1:hop3]
        lev3=dbpower(p3)
        feat["rms3s_p90_minus_p50_db"]=float(np.percentile(lev3,90)-np.percentile(lev3,50))
    pm=float(np.mean(((x[:,0]+x[:,1])*0.5)**2))
    ps=float(np.mean(((x[:,0]-x[:,1])*0.5)**2))
    feat["ms_power_ratio_db"]=float(dbpower(pm)-dbpower(ps))
    nper=int(round(sr*CONFIG["spectrogram_window_seconds"]))
    nper=min(nper,len(x)); step=max(1,int(round(sr*CONFIG["spectrogram_hop_seconds"])))
    psd=None
    for ch in range(2):
        freqs,t,part=signal.spectrogram(x[:,ch],fs=sr,window="hann",nperseg=nper,
            noverlap=nper-step,detrend=False,scaling="density",mode="psd")
        psd=part*0.5 if psd is None else psd+part*0.5
    df=float(freqs[1]-freqs[0]); dt=step/sr
    total=np.sum(psd[(freqs>=20)&(freqs<20000)],axis=0)*df
    total_mean=float(np.mean(total))
    for low,high in BANDS:
        tag=f"{low}_{high}Hz"
        bp=np.sum(psd[(freqs>=low)&(freqs<high)],axis=0)*df
        bm=float(np.mean(bp))
        feat[f"band/{tag}/rms_dbfs_at_anchor"]=float(dbpower(bm)+anchor)
        feat[f"band/{tag}/power_share"]=float(bm/max(total_mean,EPS))
        for ms in (100,400):
            nw=max(1,int(round((ms/1000)/dt))); edge=nw//2+1
            if len(bp)<=2*edge: continue
            sm=uniform_filter1d(bp,size=nw,mode="constant")[edge:-edge]
            tot=uniform_filter1d(total,size=nw,mode="constant")[edge:-edge]
            active=tot>max(float(np.max(tot))*1e-4,EPS)
            val=dbpower(sm[active]); prefix=f"band/{tag}/{ms}ms"
            p90=float(np.percentile(val,90))
            for q in (10,50,90):
                feat[f"{prefix}/p{q}_dbfs_at_anchor"]=float(np.percentile(val,q)+anchor)
            if bm < max(total_mean*1e-6,EPS):
                feat[f"{prefix}/occupancy_6db_below_p90"]=None
                feat[f"{prefix}/p90_minus_p10_db"]=None
            else:
                feat[f"{prefix}/occupancy_6db_below_p90"]=float(np.mean(val>=p90-6.0))
                feat[f"{prefix}/p90_minus_p10_db"]=p90-float(np.percentile(val,10))
    return {"included":True,"measured_lufs":lufs,"analysis_gain_db":anchor,"features":feat}


def validate_winner(manifest_path,expected_hash=KNOWN_WINNER_SHA256):
    path=Path(manifest_path).resolve()
    if path.is_dir(): path=path/"manifest.json"
    job=path.parent; manifest=load_json(path)
    if manifest.get("experiment_id")!="PDRM-v0.6-Round9-HarmonicLoudness-exp1":
        raise ValueError("Not the accepted Round 9 experiment manifest")
    mapping=load_json(job/"LAB_INTERNAL"/"blind_mapping.json")
    if mapping.get("C")!="HarmonicElasticity": raise ValueError("This job's C is not HarmonicElasticity")
    winner=job/"RENDERS"/"HarmonicElasticity.wav"
    actual=sha256_file(winner)
    state=load_json(job/"state.json")
    if state.get("candidates",{}).get("HarmonicElasticity",{}).get("sha256")!=actual:
        raise ValueError("Winner file differs from its render checkpoint")
    if actual!=expected_hash: raise ValueError("This WAV is not the C verified in the submitted AUDIT_REPORT.json")
    return winner,actual


def analyze_file(path,role,file_hash,job,progress,block_seconds=30.0,minimum_seconds=10.0,interrupt_after=None):
    info=sf.info(path)
    if info.channels!=2 or info.samplerate<44100: raise ValueError("Stereo 44.1 kHz+ required")
    if info.duration<minimum_seconds: raise ValueError("File shorter than minimum analysis block")
    chunk=int(round(block_seconds*info.samplerate)); count=math.ceil(info.frames/chunk)
    rows=[]; computed=0; reused=0
    with sf.SoundFile(path) as f:
        for i in range(count):
            start=i*chunk; frames=min(chunk,info.frames-start); duration=frames/info.samplerate
            progress.set(role,i,count)
            if duration<minimum_seconds:
                rows.append({"index":i,"start_seconds":start/info.samplerate,"duration_seconds":duration,
                             "included":False,"reason":"short_tail","features":{}})
                continue
            cache=job/"blocks"/f"{role}_{i:05d}.json"
            record=None
            if cache.exists():
                try:
                    saved=load_json(cache)
                    if saved.get("file_sha256")==file_hash and saved.get("payload_sha256")==object_hash(saved["payload"]):
                        record=saved["payload"]
                except (OSError,ValueError,KeyError,TypeError): pass
            if record is None:
                f.seek(start); audio=f.read(frames,dtype="float64",always_2d=True)
                record={"index":i,"start_seconds":start/info.samplerate,"duration_seconds":duration,
                        **block_metrics(audio,info.samplerate)}
                atomic_json(cache,{"file_sha256":file_hash,"payload_sha256":object_hash(record),"payload":record})
                computed+=1
            else: reused+=1
            rows.append(record)
            if interrupt_after is not None and computed>=interrupt_after:
                raise RuntimeError("Injected interruption after committed measurement block")
    if not any(r["included"] for r in rows): raise ValueError("No usable non-silent blocks")
    return {"samplerate":info.samplerate,"channels":info.channels,"duration_seconds":info.duration,
            "rows":rows,"computed_blocks":computed,"reused_blocks":reused}


def summarize(rows):
    active=[r["features"] for r in rows if r["included"]]
    keys=sorted(set().union(*(r.keys() for r in active)))
    result={}
    for key in keys:
        vals=[float(r[key]) for r in active if r.get(key) is not None and math.isfinite(r[key])]
        if vals: result[key]={"p10":float(np.percentile(vals,10)),"p50":float(np.median(vals)),
                              "p90":float(np.percentile(vals,90)),"n":len(vals)}
    return result


def comparison_table(c,ref):
    out={}
    for key in sorted(c.keys() & ref.keys()):
        a,b=c[key],ref[key]; v=a["p50"]
        relation="below_reference_p10" if v<b["p10"] else "above_reference_p90" if v>b["p90"] else "inside_reference_p10_p90"
        out[key]={"C_block_median":v,"reference_block_p10":b["p10"],"reference_block_median":b["p50"],
                  "reference_block_p90":b["p90"],"C_minus_reference_median":v-b["p50"],"descriptive_relation":relation}
    return out


def write_markdown(path,report):
    lines=["# PDRM C / Reference 同一定義比較", "", "状態: MEASURED_NOT_QUALITY_APPROVAL", "",
        "音声は読み取りのみ。C・本番DSP・runtimeは変更していません。", "",
        "## 読み方", "30秒ブロックを個別に−14 LUFSへ分析上だけ揃えています。再生音声は生成しません。",
        "これは曲単位のSpotify正規化の再現でも、旧13曲のcore cohortの再計測でもありません。",
        "連続参照録音全体を固定時間窓として扱います。曲境界未確認、最後の補助曲も含まれ得ます。",
        "10秒未満の末尾と−60 LUFS未満のブロックは除外。曲の切替をまたぐ窓は自動除外していません。",
        "参照の10〜90百分位から外れることは、欠陥・不合格・EQ指示ではありません。",
        "指標の単位はキーに記載。power_share/occupancyは0〜1の比率。他はdB/LUです。", "",
        "## ブロック間の比較", "| 指標 | C中央値 | 参照P10 | 参照中央値 | 参照P90 | C−参照中央値 |",
        "|---|---:|---:|---:|---:|---:|"]
    for key,v in report["comparison"].items():
        lines.append(f"| {key} | {v['C_block_median']:.4f} | {v['reference_block_p10']:.4f} | {v['reference_block_median']:.4f} | {v['reference_block_p90']:.4f} | {v['C_minus_reference_median']:.4f} |")
    lines += ["", "## 限界", "聴き疲れ・艶・主観的大きさ・ボーカルの位置を直接測定していません。",
              "PLRは全曲値でなくブロック値です。旧crestの計算実装とは同一ではないため、旧閾値を流用しません。",
              "編曲・楽器編成・曲構成と処理の寄与はこの観察だけでは分離できません。",
              "音色の異なる曲の差を自動で加工要求へ変換しません。追加の試聴を自動要求しません。", ""]
    Path(path).write_text("\n".join(lines),encoding="utf-8")


def run_comparison(manifest_path,reference_path,output_root,expected_winner_hash=KNOWN_WINNER_SHA256,
                   block_seconds=30.0,minimum_seconds=10.0,interrupt_after=None):
    reference=Path(reference_path).resolve()
    if reference.suffix.lower() not in (".wav",".flac",".aif",".aiff"):
        raise ValueError("Use the existing reference WAV/FLAC/AIFF; no new MP3 generation")
    if block_seconds<minimum_seconds or minimum_seconds<0.5: raise ValueError("Invalid block durations")
    with Progress() as progress:
        progress.set("VERIFY_C_AND_HASH_REFERENCE")
        winner,chash=validate_winner(manifest_path,expected_winner_hash)
        if winner.resolve()==reference: raise ValueError("Reference is the winner itself")
        rhash=sha256_file(reference)
        versions={k:importlib.metadata.version(k) for k in ("numpy","scipy","soundfile","pyloudnorm")}
        identity={"version":VERSION,"tool_sha256":sha256_file(Path(__file__)),"C_sha256":chash,
                  "reference_sha256":rhash,"config":CONFIG,"block_seconds":block_seconds,
                  "minimum_seconds":minimum_seconds,"versions":versions}
        job=Path(output_root).resolve()/object_hash(identity)[:20]
        source_job=Path(manifest_path).resolve()
        source_job=source_job if source_job.is_dir() else source_job.parent
        if job.is_relative_to(source_job) or job==source_job:
            raise ValueError("Comparison output must be outside the original Round 9 job")
        job.mkdir(parents=True,exist_ok=True)
        with exclusive_lock(job/"RUN.lock"):
            progress.path=job/"progress.json"
            atomic_json(job/"manifest.json",identity)
            try:
                c=analyze_file(winner,"C",chash,job,progress,block_seconds,minimum_seconds,interrupt_after)
                r=analyze_file(reference,"REFERENCE",rhash,job,progress,block_seconds,minimum_seconds,interrupt_after)
                cs=summarize(c["rows"]); rs=summarize(r["rows"])
                progress.set("VERIFY_INPUTS_UNCHANGED")
                if sha256_file(winner)!=chash or sha256_file(reference)!=rhash:
                    raise RuntimeError("Source changed during analysis; discard this comparison")
                report={"status":"MEASURED_NOT_QUALITY_APPROVAL","identity":identity,
                        "source_names":{"C":winner.name,"reference":reference.name},
                        "cohort":"fixed_time_blocks_not_tracks_not_old_13_track_cohort",
                        "analysis_normalization":"each_block_analytically_anchored_to_minus14_lufs_not_platform_playback",
                        "C":c,"reference":r,"C_summary":cs,"reference_summary":rs,
                        "comparison":comparison_table(cs,rs),"source_unchanged":True,
                        "audio_written":False,"production_core_modified":False,"listening_request":"NONE",
                        "inference_limits":["Not a fatigue, gloss or subjective loudness meter.",
                          "Block distributions are time-weighted proxies, not independent tracks or causal evidence.",
                          "Automatic track boundaries are not inferred; some windows can cross transitions.",
                          "Legacy core-track exclusions and old hard_max thresholds are NOT applied.",
                          "Per-block gain anchoring removes level differences for analysis; it is not track normalization.",
                          "True peak is a 4x FIR estimate, not a certified meter.",
                          "No rankings, EQ recommendations or processing decisions are produced."]}
                atomic_json(job/"REFERENCE_GAP_REPORT.json",report)
                write_markdown(job/"REFERENCE_GAP_REPORT.md",report)
                progress.set("COMPLETE",1,1)
                print("COMPLETE:",job/"REFERENCE_GAP_REPORT.json",flush=True)
                return report
            except BaseException:
                atomic_json(job/"ERROR.json",{"stage":progress.stage,"error":traceback.format_exc(),
                    "advice":"Do not repeatedly retry. Keep committed block JSONs and this error report."})
                raise


def choose_files(job,reference):
    if job and reference: return Path(job),Path(reference)
    import tkinter as tk
    from tkinter import filedialog
    root=tk.Tk(); root.withdraw()
    try:
        if not job:
            job=filedialog.askopenfilename(title="Select manifest.json from the listened Round9 job",
                    filetypes=[("Round9 manifest","manifest.json")],initialdir=str(Path(__file__).parent/"Round9_Output"))
        if not job: raise SystemExit("Cancelled")
        if not reference:
            reference=filedialog.askopenfilename(title="Select ConfidenceBoost.wav (existing reference)",
                    filetypes=[("Lossless audio","*.wav *.flac *.aif *.aiff")])
        if not reference: raise SystemExit("Cancelled")
        return Path(job),Path(reference)
    finally: root.destroy()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job",type=Path); parser.add_argument("--reference",type=Path)
    base=Path(os.environ.get("LOCALAPPDATA",str(Path.home()/".local/share")))
    parser.add_argument("--output-root",type=Path,default=base/"PDRM_Local_Render_Engine_v1"/"reference_gap")
    args=parser.parse_args()
    job,ref=choose_files(args.job,args.reference)
    run_comparison(job,ref,args.output_root)


if __name__=="__main__":
    main()
