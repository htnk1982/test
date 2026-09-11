"""Acceptance for the isolated Windows Spleeter observer capsule.

Runs from the main PDRM Python 3.12 environment, launches the internal Python
3.11 runtime from a Japanese/space path, observes generated stereo audio, and
then removes the large runtime. Evidence contains no model weights or stems.
"""
from pathlib import Path
import json,platform,shutil,sys,tempfile
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import observer_runtime_client_v47 as client
from integration_contract_v40 import file_hash

BUILD=ROOT/'P02_CAPSULE_WORK'
OUT=ROOT/'P02_CAPSULE_EVIDENCE'


def inside(child,parent):
    try:Path(child).resolve().relative_to(Path(parent).resolve());return True
    except ValueError:return False


def fixture(sr=48000,seconds=8.):
    t=np.arange(round(sr*seconds))/sr
    bass_gate=((t>=2.2)&(t<5.0)).astype(float);edge=np.minimum(np.clip((t-2.2)/.08,0,1),np.clip((5.0-t)/.10,0,1));edge=edge*edge*(3-2*edge)*bass_gate
    bass=edge*(.10*np.sin(2*np.pi*55*t)+.045*np.sin(2*np.pi*110*t))
    phase=t%0.5;kick=.22*np.sin(2*np.pi*58*t)*np.exp(-34*phase)
    vocal=.05*np.sin(2*np.pi*220*t)*(1+.2*np.sin(2*np.pi*3.2*t))
    other=.025*np.sin(2*np.pi*880*t)+.015*np.sin(2*np.pi*1760*t)
    return np.column_stack((bass+kick+vocal+other,bass+kick+.9*vocal+.8*other)).astype('float64')


def main():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12):raise RuntimeError('Verifier requires Windows Python 3.12 main environment')
    OUT.mkdir(exist_ok=True);build=json.loads((BUILD/'BUILD_RESULT.json').read_text(encoding='utf-8'));runtime=Path(build['runtime_dir'])
    moved=BUILD/'日本語 空白'/'PDRM Observer Runtime'
    moved.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(runtime),str(moved));runtime=moved
    with tempfile.TemporaryDirectory(prefix='pdrm_capsule_accept_') as td:
        td=Path(td);inputs=td/'inputs';inputs.mkdir();work=td/'work';source=inputs/'観測 01.wav';sf.write(source,fixture(),48000,subtype='DOUBLE');before=file_hash(source)
        arrays,meta=client.observe_dual(runtime,source,2.0,6.0,(1.,2.),work_root=work,timeout=240)
        if file_hash(source)!=before:raise RuntimeError('Source changed')
        if not inside(meta['runtime_executable'],runtime) or not inside(meta['runtime_prefix'],runtime):raise RuntimeError('Observer used host Python/runtime')
        if list(meta['source_order'])!=['mix','drums','bass','other','vocals']:raise RuntimeError('Unexpected source order')
        if any(work.iterdir()):raise RuntimeError('Observer IPC workspace leaked after call')
        time=arrays['time'];inside_event=(time>=2.35)&(time<4.85);outside_event=((time>=2.0)&(time<2.15))|((time>=5.2)&(time<6.0))
        low=arrays['low_power'];bass_index=2
        bass_share=low[:,:,bass_index]/np.maximum(low.sum(axis=2),1e-24)
        metrics=dict(frames=len(time),contexts=2,source_count=5,
            bass_low_share_event_median=float(np.median(bass_share[:,inside_event])),
            bass_low_share_outside_median=float(np.median(bass_share[:,outside_event])),
            bass_periodicity_event_median=float(np.median(arrays['bass_periodicity'][:,inside_event])),
            bass_f0_event_median_hz=float(np.median(arrays['bass_f0_hz'][:,inside_event][arrays['bass_f0_hz'][:,inside_event]>0])) if np.any(arrays['bass_f0_hz'][:,inside_event]>0) else 0.,
            reconstruction_error_db=meta['reconstruction_error_db'])
        if not (0<=metrics['bass_low_share_event_median']<=1 and 0<=metrics['bass_low_share_outside_median']<=1):raise RuntimeError('Invalid role metrics')
        if meta['stem_audio_persisted'] is not False or meta['stem_audio_in_master'] is not False or meta['network_downloads_allowed'] is not False:raise RuntimeError('Observer policy failed')
        # A second independent call must preserve source and contract geometry.
        arrays2,meta2=client.observe_dual(runtime,source,2.0,6.0,(1.,2.),work_root=work,timeout=240)
        if arrays2['low_power'].shape!=arrays['low_power'].shape or meta2['model_asset_sha256']!=meta['model_asset_sha256'] or file_hash(source)!=before:raise RuntimeError('Repeated observer contract changed')
        model_manifest=json.loads((runtime/'PDRM_OBSERVER_RUNTIME_MANIFEST.json').read_text(encoding='utf-8'))
        evidence=dict(success=True,task='P02-isolated-runtime',platform=platform.platform(),main_python=sys.version,
            isolated_runtime_python=meta['runtime_executable'],isolated_runtime_prefix=meta['runtime_prefix'],runtime_path_has_japanese_and_space=True,
            runtime_bytes=build['runtime_bytes'],runtime_file_count=build['file_count'],runtime_manifest_sha256=meta['runtime_manifest_sha256'],
            model_asset_sha256=meta['model_asset_sha256'],worker_version=meta['worker_version'],tensorflow_version=meta['tensorflow_version'],
            source_unchanged=True,stem_audio_persisted=False,stem_audio_in_master=False,runtime_model_download=False,
            user_python_install_required=False,host_tensorflow_imported_by_main=False,feature_metrics=metrics,
            musical_role_accuracy_certified=False,private_audio_used=False,product_release=False)
        (OUT/'SUMMARY.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        shutil.copyfile(runtime/'PDRM_OBSERVER_RUNTIME_MANIFEST.json',OUT/'PDRM_OBSERVER_RUNTIME_MANIFEST.json')
        md=f'''# PDRM P02 — 隔離Spleeter worker/runtime 実行結果\n\n日付: 2026-09-12。状態: Windows worker runtimeの技術受入。実曲の音楽判断・製品リリースではない。\n\nPython 3.12/Numpy2系のPDRM主プロセスから、別フォルダのCPython {model_manifest['python_version']} + Spleeter {model_manifest['packages']['spleeter']} + TensorFlow {model_manifest['packages']['tensorflow']}をsubprocessとして起動した。利用者側のPython/TensorFlow手動導入は不要。\n\nruntimeをcheckout外相当の日本語・空白を含むパスへ移動してから実行し、workerが返した`sys.executable`/`sys.prefix`がそのruntime配下であることを確認。公式4stems asset hashは`{meta['model_asset_sha256']}`。曲処理時のモデルdownloadは禁止し、分離stemはファイル保存せず、完成音にも混ぜない。\n\n48kHz生成stereo入力を2つの文脈で解析し、mix/drums/bass/other/vocalsの帯域power、bass pitch/periodicityだけをsealed JSONで主プロセスへ返した。入力hashは前後一致。一時IPC領域は終了時空。2回目の独立呼出しでもgeometry/model identityを維持。\n\n生成fixture上の参考値: bass low share event median={metrics['bass_low_share_event_median']:.6f}、outside={metrics['bass_low_share_outside_median']:.6f}、bass periodicity event median={metrics['bass_periodicity_event_median']:.6f}、f0 median={metrics['bass_f0_event_median_hz']:.3f}Hz。これらはSpleeterのPDRM用途への優越性や私有実曲精度を認定するスコアではない。\n\n大容量runtime/modelはCI内で削除し、artifactへ配布しない。P02の次条件はHDEMUCS研究baselineとの役割タスク比較と、採用後の製品manifest/最終EXEへの組込み。\n'''
        (OUT/'PDRM_P02_隔離Runtime実行結果_20260912.md').write_text(md,encoding='utf-8')
        print('P02_CAPSULE_ACCEPT '+json.dumps(evidence,ensure_ascii=True),flush=True)
    shutil.rmtree(BUILD,ignore_errors=False)
    if BUILD.exists():raise RuntimeError('Large observer runtime not removed after evidence capture')

if __name__=='__main__':main()
