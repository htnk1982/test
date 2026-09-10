"""P02 deployability probe for the official Spleeter v1.4.0 4stems asset.

This CI research job downloads only public official assets, validates the release
checksum, runs local inference on generated audio, records exact files/versions,
and deletes weights. It does NOT choose Spleeter by musical quality or publish
weights/a product. No user audio or review data is used.
"""
from pathlib import Path
import hashlib,json,os,tarfile,tempfile,urllib.request,platform,sys,time
import numpy as np
import soundfile as sf
from scipy import signal

RELEASE='v1.4.0'
BASE=f'https://github.com/deezer/spleeter/releases/download/{RELEASE}'
ASSET='4stems.tar.gz'
OUT=Path(__file__).resolve().parents[1]/'P02_SPLEETER_EVIDENCE'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def download(url,path):
    with urllib.request.urlopen(url,timeout=60) as r,Path(path).open('wb') as f:
        while True:
            b=r.read(2**20)
            if not b:break
            f.write(b)


def safe_extract(archive,dest):
    dest=Path(dest).resolve()
    with tarfile.open(archive,'r:gz') as t:
        members=t.getmembers()
        for m in members:
            target=(dest/m.name).resolve()
            if dest not in target.parents and target!=dest:raise RuntimeError('Archive path escape')
            if m.issym() or m.islnk():raise RuntimeError('Archive links refused')
        t.extractall(dest,members=members)


def low_power(x,sr,lo,hi):
    z=signal.sosfiltfilt(signal.butter(4,[lo,hi],btype='bandpass',fs=sr,output='sos'),x,axis=0)
    return float(np.mean(z*z))


def main():
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='spleeter45_') as td:
        root=Path(td);index=root/'checksum.json';archive=root/ASSET
        download(BASE+'/checksum.json',index);download(BASE+'/'+ASSET,archive)
        checks=json.loads(index.read_text(encoding='utf-8'));expected=checks.get('4stems')
        actual=sha(archive)
        if not isinstance(expected,str) or actual!=expected:raise RuntimeError(f'Official archive checksum mismatch expected={expected} actual={actual}')
        model_root=root/'models';model=model_root/'4stems';model.mkdir(parents=True);safe_extract(archive,model);(model/'.probe').write_text('OK',encoding='utf-8')
        model_files={str(p.relative_to(model)):sha(p) for p in sorted(model.rglob('*')) if p.is_file() and p.name!='.probe'}
        if not model_files:raise RuntimeError('No extracted model files')
        os.environ['MODEL_PATH']=str(model_root)
        # Import after MODEL_PATH has been fixed so provider cannot silently use a
        # user cache. Network is not needed by Separator once .probe+weights exist.
        import tensorflow as tf
        import spleeter
        from spleeter.separator import Separator
        sr=44100;seconds=5.;t=np.arange(round(sr*seconds))/sr
        bass=.10*np.sin(2*np.pi*55*t)+.04*np.sin(2*np.pi*110*t)
        kick=.18*np.sin(2*np.pi*(75-35*np.minimum(t%0.5,.12)/.12)*t)*(np.exp(-28*(t%0.5)))
        vocal=.05*np.sin(2*np.pi*220*t)*(1+.25*np.sin(2*np.pi*3*t))
        other=.035*np.sin(2*np.pi*880*t)+.02*np.sin(2*np.pi*1760*t)
        mix=np.column_stack((bass+kick+vocal+other,bass+kick+.9*vocal+.8*other)).astype(np.float32)
        before=mix.copy();separator=Separator('spleeter:4stems',multiprocess=False)
        started=time.monotonic();stems=separator.separate(mix,'generated-fixture');elapsed=time.monotonic()-started
        if set(stems)!={'vocals','drums','bass','other'}:raise RuntimeError('Unexpected source set '+repr(stems.keys()))
        shape={k:list(np.asarray(v).shape) for k,v in stems.items()}
        if any(np.asarray(v).shape!=mix.shape or not np.isfinite(v).all() for v in stems.values()):raise RuntimeError('Invalid separation output')
        np.testing.assert_array_equal(mix,before)
        # Analysis-only evidence. Do not save stems. These energy ratios are not
        # probabilities and this simple fixture is NOT a source-separation score.
        powers={band:{k:low_power(v,sr,*rng) for k,v in stems.items()} for band,rng in {'low':(25,120),'body':(120,300),'focus':(300,700)}.items()}
        stem_bytes=sum(np.asarray(v).nbytes for v in stems.values());del stems,separator
        import importlib.metadata as im
        record=dict(success=True,release=RELEASE,asset=ASSET,archive_sha256=actual,checksum_index_sha256=sha(index),
            official_asset_url=BASE+'/'+ASSET,official_checksum_url=BASE+'/checksum.json',model_files=model_files,
            model_file_count=len(model_files),versions={n:im.version(n) for n in ('spleeter','tensorflow','numpy','scipy','soundfile')},
            platform=platform.platform(),python=sys.version,stem_order=['vocals','drums','bass','other'],sample_rate=sr,
            output_shapes=shape,inference_seconds=elapsed,analysis_band_powers=powers,source_input_unchanged=True,
            separated_audio_persisted=False,estimated_stem_bytes_released=stem_bytes,user_audio_used=False,
            musical_role_accuracy_certified=False,product_release=False,
            license_evidence='Spleeter JOSS paper source states source code and pretrained models are MIT; exact legal/product review remains release documentation.')
        (OUT/'SUMMARY.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        md=f'''# PDRM P02 — Spleeter公式4stems assetの実取得・推論確認\n\n日付: 2026-09-10。Issue #8。環境: {record['platform']}。\n\n公式Spleeter v1.4.0 releaseの`4stems.tar.gz`と`checksum.json`を取得し、release indexに記載されたSHA-256とarchive実測SHA-256を一致確認した。archiveを一時領域へ展開し、固定MODEL_PATHとprobeでローカル推論を実行した。\n\n出力sourceはvocals/drums/bass/otherの4本、44.1kHz・入力と同じframe/channel形状、有限値。分離音をファイルへ保存せず、帯域energyの観測後に配列を解放した。入力は生成fixtureであり、本人音源やレビューは使っていない。\n\narchive SHA256: `{actual}`。model file hashesはSUMMARY.jsonへ全件保存。Spleeter/TensorFlow/Python版も固定記録。\n\nこの成功はasset/依存/ローカル推論の技術確認。bass onset/rest/vocal protectionでHDEMUCSより良い、本人の曲へ適する、Windows製品EXEへ組込み済み、という意味ではない。次のP02タスクはWindows推論の確認と、別process/frozen runtime化。\n'''
        (OUT/'PDRM_P02_Spleeter公式asset実推論_20260910.md').write_text(md,encoding='utf-8')
        print('P02_SPLEETER '+json.dumps(record,ensure_ascii=True),flush=True)
if __name__=='__main__':main()
