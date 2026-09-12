"""P01 private-audio calibration entry.

Engineering calibration tool only. Private source/reference audio stays on the
user's machine. The executable contains the accepted P03-A planner; Spleeter is
a sibling isolated runtime and stem audio is never exported or mixed to output.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse, hashlib, json, os, shutil, sys, time, zipfile

import numpy as np
import soundfile as sf

import automatic_joint_v50 as planner50
from spleeter_observer_adapter_v48 import SpleeterRuntimeObserver
import integrated_finish_v40 as finish
from integration_contract_v40 import capture, file_hash
from target_settings import Targets

VERSION = "p01-private-calibration-0.1.1"
ACCEPTED_P03A_COMMIT = "50a4592e45b3f810e905041c25cff1c3e35b2a88"
AUDIO_EXTS = {".wav", ".flac", ".mp3", ".aif", ".aiff"}


def bundle_root():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def runtime_root():
    return bundle_root() / "PDRM_OBSERVER_RUNTIME"


def _safe_extract_zip(archive: Path, dest: Path):
    with zipfile.ZipFile(archive) as z:
        root = dest.resolve()
        for info in z.infolist():
            candidate = (dest / info.filename).resolve()
            if root != candidate and root not in candidate.parents:
                raise ValueError("Unsafe reference ZIP path")
        z.extractall(dest)


def _reference_files(reference: Path, temp: Path):
    reference = Path(reference).resolve(strict=True)
    if reference.is_file():
        if reference.suffix.lower() != ".zip":
            raise ValueError("Reference must be a directory or ZIP")
        extracted = temp / "references"
        extracted.mkdir()
        _safe_extract_zip(reference, extracted)
        root = extracted
    elif reference.is_dir():
        root = reference
    else:
        raise ValueError("Reference path is not a file/directory")
    files = sorted(
        (p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO_EXTS),
        key=lambda p: p.as_posix().casefold(),
    )
    if len(files) < 4:
        raise ValueError("At least four independent reference audio files are required")
    return files


def _hash_manifest(paths):
    return [
        dict(name=p.name, sha256=file_hash(p), bytes=p.stat().st_size)
        for p in paths
    ]


def _copy_verified(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        raise FileExistsError("Refusing to overwrite existing result: " + str(dst))
    shutil.copy2(src, dst)
    if file_hash(src) != file_hash(dst):
        dst.unlink(missing_ok=True)
        raise RuntimeError("Copied result hash mismatch")


def calibrate(source, reference, output, *, targets=None):
    source = Path(source).resolve(strict=True)
    reference = Path(reference).resolve(strict=True)
    output = Path(output).resolve()
    if source.suffix.lower() not in {".wav", ".flac"}:
        raise ValueError("Private source must be WAV or FLAC")
    if output == source.parent or source.parent in output.parents:
        raise ValueError("Output must be outside the original source folder")
    output.mkdir(parents=True, exist_ok=True)
    original = capture(source)
    runtime = runtime_root()
    if not runtime.is_dir():
        raise RuntimeError("Bundled PDRM_OBSERVER_RUNTIME is missing")

    work_base = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PDRM_P01_PRIVATE_WORK"
    work_base.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="p01_refs_") as ref_td, TemporaryDirectory(prefix="p01_job_", dir=work_base) as job_td:
        refs = _reference_files(reference, Path(ref_td))
        specs = [dict(path=p, role="bass", quality="positive") for p in refs]
        calibration = planner50.make_calibration(specs)
        observer_work = Path(job_td) / "observer_ipc"
        observer = SpleeterRuntimeObserver(runtime, work_root=observer_work, timeout=600)
        planner = planner50.AutomaticJointPlanner(calibration, observer)
        report, folder = finish.run_lab(
            source, Path(job_td) / "render", planner,
            targets=(targets or Targets()), write_mp3=True,
            enable_lab=True, render_backend="joint-v46"
        )
        original.verify(source)

        stamp = original.file_sha256[:12]
        final = output / f"PDRM_P01_{source.stem}_{stamp}"
        if final.exists():
            raise FileExistsError("Result folder already exists: " + str(final))
        final.mkdir()

        for name in ("MASTER.wav", "LISTEN_320kbps.mp3", "RUN_REPORT.json", "PROOF.json", "完了.md"):
            p = folder / name
            if p.exists():
                _copy_verified(p, final / name)

        manifest = dict(
            schema=1, version=VERSION, accepted_p03a_commit=ACCEPTED_P03A_COMMIT,
            source=dict(
                name=source.name, file_sha256=original.file_sha256,
                pcm_sha256=original.pcm_sha256, samplerate=original.samplerate,
                frames=original.frames, channels=original.channels,
            ),
            reference_source=dict(
                kind="zip" if reference.is_file() else "directory",
                name=reference.name,
                archive_sha256=file_hash(reference) if reference.is_file() else None,
            ),
            references=_hash_manifest(refs),
            calibration_sha256=calibration["sha256"],
            planner_identity=planner.identity(),
            planner_report=report.get("planner_report"),
            lowend_assessment=report.get("lowend_assessment"),
            requested_targets=report.get("requested_targets"),
            master_metrics=report.get("master_metrics"),
            codec_metrics=report.get("codec_metrics"),
            outputs={p.name: file_hash(p) for p in final.iterdir() if p.is_file()},
            source_unchanged=True,
            private_audio_uploaded=False,
            stem_audio_exported=False,
            stem_audio_in_master=False,
            subjective_quality="REQUIRES_LOCAL_LISTENING_REVIEW",
            product_release=False,
        )
        (final / "CALIBRATION_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        (final / "REVIEW.md").write_text(
            "# PDRM P01 実曲レビュー\n\n"
            "これは製品版の合格判定ではなく、P03の量・発動タイミング校正用です。\n\n"
            "## 聴く順序\n"
            "1. 元音源\n2. `MASTER.wav`\n3. `LISTEN_320kbps.mp3`\n\n"
            "## 記録すること\n"
            "- 低域が増減すべきでない場所で動いていないか\n"
            "- 低域の芯・重さが改善したか、過剰か、不足か\n"
            "- 中高域、アタック、奥行きを壊していないか\n"
            "- 最も違和感のある時刻を最大3か所だけ記録\n\n"
            "判断不能なら無理に採点せず `ABSTAIN` とする。\n",
            encoding="utf-8",
        )
        manifest["outputs"] = {p.name: file_hash(p) for p in final.iterdir() if p.is_file() and p.name != "CALIBRATION_MANIFEST.json"}
        (final / "CALIBRATION_MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        return final, manifest


def _gate(t, a, b, fade=.06):
    g=((t>=a)&(t<b)).astype(float)
    e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1))
    return g*e*e*(3-2*e)


def _fixture_reference(sr=48000, seconds=7., phase=0., level=.11):
    t=np.arange(round(sr*seconds))/sr
    low=np.zeros_like(t)
    for a,b,f in ((.8,1.2,55.),(2.0,2.5,73.4),(3.5,4.15,110.),(5.3,5.7,55.)):
        g=_gate(t,a,b);low+=level*g*(np.sin(2*np.pi*f*t+phase)+.45*np.sin(4*np.pi*f*t)+.2*np.sin(6*np.pi*f*t))
    bed=.045*np.sin(2*np.pi*1600*t+phase)+.025*np.sin(2*np.pi*2400*t)
    return np.column_stack((low+bed,low+.94*bed))


def _fixture_source(sr=48000, seconds=7.):
    t=np.arange(round(sr*seconds))/sr;g=_gate(t,2.15,5.0)
    bass=g*(.004*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    bed=.035*np.sin(2*np.pi*1700*t)+.022*np.sin(2*np.pi*2300*t)
    return np.column_stack((bass+bed,bass+.92*bed))


def self_test(dest):
    dest=Path(dest).resolve()
    dest.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="p01_selftest_source_") as source_td, TemporaryDirectory(prefix="p01_selftest_output_") as output_td:
        root=Path(source_td);refs=root/"refs";refs.mkdir()
        for i in range(4):
            sf.write(refs/f"ref{i}.wav", _fixture_reference(phase=.19*i,level=.105+.004*i), 48000, subtype="DOUBLE")
        reference_zip=root/"reference.zip"
        with zipfile.ZipFile(reference_zip,"w",compression=zipfile.ZIP_DEFLATED) as z:
            for p in sorted(refs.glob("*.wav")):z.write(p,arcname="reference/"+p.name)
        source=root/"private-like source.wav"
        sf.write(source,_fixture_source(),48000,subtype="DOUBLE")
        final,manifest=calibrate(source,reference_zip,Path(output_td))
        if not (final/"MASTER.wav").is_file() or not (final/"LISTEN_320kbps.mp3").is_file():
            raise RuntimeError("Self-test final audio missing")
        summary=dict(
            success=True, version=VERSION, accepted_p03a_commit=ACCEPTED_P03A_COMMIT,
            frozen=bool(getattr(sys,"frozen",False)),
            source_unchanged=manifest["source_unchanged"],
            reference_zip_exercised=True,
            accepted_additions=(manifest.get("planner_report") or {}).get("accepted_additions"),
            observer_provider=((manifest.get("planner_identity") or {}).get("observer") or {}).get("provider"),
            stem_audio_in_master=False, private_audio=False, product_release=False,
        )
        (dest/"P01_BUNDLE_SELFTEST.json").write_text(json.dumps(summary,indent=2,allow_nan=False),encoding="utf-8")
        return summary


def gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root=tk.Tk();root.withdraw()
    source=filedialog.askopenfilename(title="P01: 実曲WAV/FLACを選択",filetypes=[("Audio","*.wav *.flac")])
    if not source:return 2
    reference=filedialog.askopenfilename(title="P01: reference.zipを選択",filetypes=[("ZIP","*.zip")])
    if not reference:
        reference=filedialog.askdirectory(title="P01: 参照音源フォルダを選択")
    if not reference:return 2
    output=filedialog.askdirectory(title="P01: 結果保存先（元音源フォルダ以外）を選択")
    if not output:return 2
    try:
        final,_=calibrate(source,reference,output)
    except Exception as e:
        messagebox.showerror("PDRM P01", f"処理に失敗しました。\n\n{type(e).__name__}: {e}")
        return 1
    messagebox.showinfo("PDRM P01", "完了しました。\n\n"+str(final))
    return 0


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--source");ap.add_argument("--reference");ap.add_argument("--output")
    ap.add_argument("--self-test", action="store_true");ap.add_argument("--self-test-output")
    args=ap.parse_args()
    if args.self_test:
        if not args.self_test_output:raise SystemExit("--self-test-output required")
        print(json.dumps(self_test(args.self_test_output),ensure_ascii=True),flush=True);return
    if args.source or args.reference or args.output:
        if not all((args.source,args.reference,args.output)):raise SystemExit("--source --reference --output are all required")
        final,_=calibrate(args.source,args.reference,args.output);print(str(final),flush=True);return
    raise SystemExit(gui())


if __name__=="__main__":
    main()
