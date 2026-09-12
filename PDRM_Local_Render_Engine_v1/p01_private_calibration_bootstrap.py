"""P01 compatibility boundary for the canonical historical MP3 reference set.

The global PDRM integration contract remains lossless-only. This private local
bootstrap converts the one fixed historical reference ZIP from MP3 into temporary
float-WAV files, then delegates to the accepted P03-A calibration runner. Neither
original private reference audio nor decoded WAVs are uploaded or persisted.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse, json, subprocess, sys, zipfile

import soundfile as sf
import p01_private_calibration_entry as core
from integration_contract_v40 import capture, file_hash

VERSION='p01-reference-compat-0.1.0'
EXPECTED_REFERENCE_ZIP_SHA256='82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a'
EXPECTED_REFERENCE_COUNT=24
EXPECTED_REFERENCE_RATE=44100

_LAST_REFERENCE_PROVENANCE=None
_SELFTEST_REFERENCE=False


def _ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def _decode_mp3_to_float_wav(source:Path,dest:Path):
    command=[_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(source),'-map_metadata','-1','-vn','-c:a','pcm_f32le',str(dest)]
    run=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=600)
    if run.returncode or not dest.is_file() or dest.stat().st_size<1024:
        raise RuntimeError('Reference MP3 local decode failed: '+run.stdout[-4000:])
    info=sf.info(dest)
    if info.channels!=2 or info.samplerate!=EXPECTED_REFERENCE_RATE or info.frames<=0:
        raise ValueError('Decoded reference geometry mismatch')
    return capture(dest)


def _reference_files(reference:Path,temp:Path):
    """Return temporary lossless calibration inputs while retaining MP3 provenance."""
    global _LAST_REFERENCE_PROVENANCE
    reference=Path(reference).resolve(strict=True)
    if not reference.is_file() or reference.suffix.lower()!='.zip':
        raise ValueError('P01 requires the canonical reference.zip file')
    archive_sha=file_hash(reference)
    if not _SELFTEST_REFERENCE and archive_sha!=EXPECTED_REFERENCE_ZIP_SHA256:
        raise ValueError('Wrong reference ZIP: select the canonical 24-track reference.zip')
    extracted=temp/'reference_mp3';extracted.mkdir()
    core._safe_extract_zip(reference,extracted)
    originals=sorted((p for p in extracted.rglob('*') if p.is_file() and p.suffix.lower() in core.AUDIO_EXTS),key=lambda p:p.as_posix().casefold())
    if len(originals)!=EXPECTED_REFERENCE_COUNT or any(p.suffix.lower()!='.mp3' for p in originals):
        raise ValueError('Reference ZIP must contain exactly 24 MP3 reference tracks')
    decoded=temp/'decoded_lossless';decoded.mkdir();lossless=[];provenance=[]
    for i,src in enumerate(originals):
        info=sf.info(src)
        if info.channels!=2 or info.samplerate!=EXPECTED_REFERENCE_RATE or info.frames<=0:
            raise ValueError('Reference MP3 geometry mismatch: '+src.name)
        dst=decoded/f'reference_{i:02d}.wav';identity=_decode_mp3_to_float_wav(src,dst)
        provenance.append(dict(index=i,original_name=src.name,original_sha256=file_hash(src),original_bytes=src.stat().st_size,
            original_codec='MP3',decoded_name=dst.name,decoded_file_sha256=identity.file_sha256,decoded_pcm_sha256=identity.pcm_sha256,
            decoded_samplerate=identity.samplerate,decoded_frames=identity.frames,decoded_channels=identity.channels))
        lossless.append(dst)
    _LAST_REFERENCE_PROVENANCE=dict(archive_sha256=archive_sha,canonical_reference=not _SELFTEST_REFERENCE,
        source_codec='MP3',decode_method='LOCAL_TEMP_FFMPEG_PCM_F32LE_WAV',decoded_audio_persisted=False,
        reference_count=len(lossless),items=provenance)
    return lossless


# Patch only the P01 local boundary. The lossless global capture()/calibration
# contract is deliberately unchanged.
core._reference_files=_reference_files


def calibrate(source,reference,output,*,targets=None):
    global _LAST_REFERENCE_PROVENANCE
    _LAST_REFERENCE_PROVENANCE=None
    final,manifest=core.calibrate(source,reference,output,targets=targets)
    if not _LAST_REFERENCE_PROVENANCE:
        raise RuntimeError('Reference provenance was not captured')
    manifest['p01_reference_adapter']=dict(version=VERSION,global_lossless_contract_relaxed=False,**_LAST_REFERENCE_PROVENANCE)
    manifest['reference_source']=dict(manifest['reference_source'],archive_sha256=_LAST_REFERENCE_PROVENANCE['archive_sha256'],
        canonical_reference=_LAST_REFERENCE_PROVENANCE['canonical_reference'],reference_count=_LAST_REFERENCE_PROVENANCE['reference_count'])
    manifest['reference_original_assets']=_LAST_REFERENCE_PROVENANCE['items']
    (final/'CALIBRATION_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return final,manifest


def _failure(output,source,reference,exc):
    p=core._failure_record(output,source,reference,exc)
    try:
        data=json.loads(p.read_text(encoding='utf-8'));data['p01_reference_adapter_version']=VERSION;data['global_lossless_contract_relaxed']=False
        p.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    except Exception:pass
    return p


def self_test(dest):
    """Exercise the actual 24-MP3 ZIP -> temporary lossless -> P03-A path."""
    global _SELFTEST_REFERENCE
    dest=Path(dest).resolve();dest.mkdir(parents=True,exist_ok=True)
    with TemporaryDirectory(prefix='p01_mp3_source_') as source_td,TemporaryDirectory(prefix='p01_mp3_output_') as output_td:
        root=Path(source_td);refs=root/'refs';refs.mkdir();mp3s=[]
        for i in range(EXPECTED_REFERENCE_COUNT):
            wav=refs/f'ref{i:02d}.wav';mp3=refs/f'ref{i:02d}.mp3'
            # Keep every decoded PCM group independent while preserving the same
            # broad musical role used by prior generated acceptance fixtures.
            sf.write(wav,core._fixture_reference(phase=.071*i,level=.100+.0007*i),48000,subtype='DOUBLE')
            # Historical references are 44.1 kHz; encode through an explicit
            # 44.1-kHz intermediate so geometry matches the real archive.
            wav44=refs/f'ref{i:02d}_44.wav'
            command=[_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error','-y','-i',str(wav),'-ar','44100','-c:a','pcm_f32le',str(wav44)]
            r=subprocess.run(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=120)
            if r.returncode:raise RuntimeError('Self-test 44.1k conversion failed')
            core._encode_mp3(wav44,mp3);mp3s.append(mp3);wav.unlink();wav44.unlink()
        archive=root/'reference.zip'
        with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for p in mp3s:z.write(p,arcname='reference/'+p.name)
        source=root/'private-like source.wav';sf.write(source,core._fixture_source(),48000,subtype='DOUBLE')
        _SELFTEST_REFERENCE=True
        try:final,manifest=calibrate(source,archive,Path(output_td))
        finally:_SELFTEST_REFERENCE=False
        adapter=manifest['p01_reference_adapter']
        if adapter['reference_count']!=EXPECTED_REFERENCE_COUNT or adapter['decode_method']!='LOCAL_TEMP_FFMPEG_PCM_F32LE_WAV':
            raise RuntimeError('Reference adapter provenance failed')
        if not (final/'MASTER.wav').is_file() or not (final/'LISTEN_320kbps.mp3').is_file():raise RuntimeError('Final audio missing')
        summary=dict(success=True,adapter_version=VERSION,core_version=core.VERSION,accepted_p03a_commit=core.ACCEPTED_P03A_COMMIT,
            frozen=bool(getattr(sys,'frozen',False)),source_unchanged=manifest['source_unchanged'],reference_zip_exercised=True,
            reference_codec='MP3',reference_count=adapter['reference_count'],reference_decoder_verified=True,
            decode_method=adapter['decode_method'],decoded_audio_persisted=False,global_lossless_contract_relaxed=False,
            accepted_additions=(manifest.get('planner_report') or {}).get('accepted_additions'),
            observer_provider=((manifest.get('planner_identity') or {}).get('observer') or {}).get('provider'),
            stem_audio_in_master=False,private_audio=False,product_release=False)
        (dest/'P01_BUNDLE_SELFTEST.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
        return summary


def gui():
    import tkinter as tk
    from tkinter import filedialog,messagebox
    root=tk.Tk();root.withdraw()
    source=filedialog.askopenfilename(title='P01: まず 11 - Traces のWAVを選択',filetypes=[('Lossless audio','*.wav *.flac')])
    if not source:return 2
    reference=filedialog.askopenfilename(title='P01: canonical reference.zip を選択',filetypes=[('reference.zip','*.zip')])
    if not reference:return 2
    output=filedialog.askdirectory(title='P01: 結果保存先（元音源フォルダ以外）')
    if not output:return 2
    try:final,_=calibrate(source,reference,output)
    except Exception as e:
        try:p=_failure(output,source,reference,e)
        except Exception:p=None
        messagebox.showerror('PDRM P01',f'処理に失敗しました。\n\n{type(e).__name__}: {e}'+(f'\n\nこのファイルだけ戻してください:\n{p}' if p else ''))
        return 1
    messagebox.showinfo('PDRM P01','完了しました。\n\n'+str(final)+'\n\nCALIBRATION_MANIFEST.json をこのチャットへ戻してください。')
    return 0


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--source');ap.add_argument('--reference');ap.add_argument('--output')
    ap.add_argument('--self-test',action='store_true');ap.add_argument('--self-test-output');args=ap.parse_args()
    if args.self_test:
        if not args.self_test_output:raise SystemExit('--self-test-output required')
        print(json.dumps(self_test(args.self_test_output),ensure_ascii=True),flush=True);return
    if args.source or args.reference or args.output:
        if not all((args.source,args.reference,args.output)):raise SystemExit('--source --reference --output are all required')
        try:final,_=calibrate(args.source,args.reference,args.output);print(str(final),flush=True);return
        except Exception as e:
            p=_failure(args.output,args.source,args.reference,e);print(str(p),file=sys.stderr,flush=True);raise
    raise SystemExit(gui())


if __name__=='__main__':main()
