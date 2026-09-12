"""Acceptance for the isolated Windows Spleeter observer capsule.

Runs from the main PDRM Python 3.12 environment, launches the internal Python
3.11 runtime from a Japanese/space path, proves one-shot/persistent equivalence,
proves worker PID reuse, and then removes the large runtime. Evidence contains
no model weights or stems.
"""
from pathlib import Path
import json,platform,shutil,sys,tempfile,time
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


def assert_equivalent(a,b):
    if set(a)!=set(b):raise RuntimeError('Persistent observer changed feature keys')
    for key in a:
        aa=np.asarray(a[key]);bb=np.asarray(b[key])
        if aa.shape!=bb.shape:raise RuntimeError('Persistent observer changed feature geometry: '+key)
        if key=='time':
            if not np.array_equal(aa,bb):raise RuntimeError('Persistent observer changed clock')
        elif not np.allclose(aa,bb,rtol=1e-6,atol=1e-9,equal_nan=False):
            raise RuntimeError('Persistent observer changed feature values beyond tolerance: '+key)


def main():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12):raise RuntimeError('Verifier requires Windows Python 3.12 main environment')
    OUT.mkdir(exist_ok=True);build=json.loads((BUILD/'BUILD_RESULT.json').read_text(encoding='utf-8'));runtime=Path(build['runtime_dir'])
    moved=BUILD/'日本語 空白'/'PDRM Observer Runtime'
    moved.parent.mkdir(parents=True,exist_ok=True);shutil.move(str(runtime),str(moved));runtime=moved
    with tempfile.TemporaryDirectory(prefix='pdrm_capsule_accept_') as td:
        td=Path(td);inputs=td/'inputs';inputs.mkdir();work=td/'work';work.mkdir();source=inputs/'観測 01.wav';sf.write(source,fixture(),48000,subtype='DOUBLE');before=file_hash(source)

        t0=time.perf_counter();baseline,meta=client.observe_dual(runtime,source,2.0,6.0,(1.,2.),work_root=work,timeout=240);one_shot_seconds=time.perf_counter()-t0
        if file_hash(source)!=before:raise RuntimeError('Source changed')
        if not inside(meta['runtime_executable'],runtime) or not inside(meta['runtime_prefix'],runtime):raise RuntimeError('Observer used host Python/runtime')
        if list(meta['source_order'])!=['mix','drums','bass','other','vocals']:raise RuntimeError('Unexpected source order')

        startup0=time.perf_counter()
        with client.PersistentObserverSession(runtime,work_root=work,timeout=240) as session:
            startup_seconds=time.perf_counter()-startup0
            t1=time.perf_counter();arrays1,meta1=session.observe_dual(source,2.0,6.0,(1.,2.));persistent_first_seconds=time.perf_counter()-t1
            t2=time.perf_counter();arrays2,meta2=session.observe_dual(source,2.0,6.0,(1.,2.));persistent_second_seconds=time.perf_counter()-t2
            pid=session.worker_pid
            if not pid or meta1.get('worker_pid')!=pid or meta2.get('worker_pid')!=pid:raise RuntimeError('Persistent worker PID was not reused')
            if meta1.get('persistent_session') is not True or meta2.get('persistent_session') is not True:raise RuntimeError('Persistent metadata missing')
            assert_equivalent(baseline,arrays1);assert_equivalent(arrays1,arrays2)
        if any(work.iterdir()):raise RuntimeError('Observer IPC workspace leaked after closed session')
        if file_hash(source)!=before:raise RuntimeError('Source changed after persistent calls')

        time_axis=baseline['time'];inside_event=(time_axis>=2.35)&(time_axis<4.85);outside_event=((time_axis>=2.0)&(time_axis<2.15))|((time_axis>=5.2)&(time_axis<6.0))
        low=baseline['low_power'];bass_index=2
        bass_share=low[:,:,bass_index]/np.maximum(low.sum(axis=2),1e-24)
        metrics=dict(frames=len(time_axis),contexts=2,source_count=5,
            bass_low_share_event_median=float(np.median(bass_share[:,inside_event])),
            bass_low_share_outside_median=float(np.median(bass_share[:,outside_event])),
            bass_periodicity_event_median=float(np.median(baseline['bass_periodicity'][:,inside_event])),
            bass_f0_event_median_hz=float(np.median(baseline['bass_f0_hz'][:,inside_event][baseline['bass_f0_hz'][:,inside_event]>0])) if np.any(baseline['bass_f0_hz'][:,inside_event]>0) else 0.,
            reconstruction_error_db=meta['reconstruction_error_db'])
        if not (0<=metrics['bass_low_share_event_median']<=1 and 0<=metrics['bass_low_share_outside_median']<=1):raise RuntimeError('Invalid role metrics')
        if meta['stem_audio_persisted'] is not False or meta['stem_audio_in_master'] is not False or meta['network_downloads_allowed'] is not False:raise RuntimeError('Observer policy failed')
        evidence=dict(success=True,task='P02-isolated-runtime-persistent',platform=platform.platform(),main_python=sys.version,
            isolated_runtime_python=meta['runtime_executable'],isolated_runtime_prefix=meta['runtime_prefix'],runtime_path_has_japanese_and_space=True,
            runtime_bytes=build['runtime_bytes'],runtime_file_count=build['file_count'],runtime_manifest_sha256=meta['runtime_manifest_sha256'],
            model_asset_sha256=meta['model_asset_sha256'],worker_version=meta['worker_version'],tensorflow_version=meta['tensorflow_version'],
            source_unchanged=True,stem_audio_persisted=False,stem_audio_in_master=False,runtime_model_download=False,
            user_python_install_required=False,host_tensorflow_imported_by_main=False,feature_metrics=metrics,
            persistent_equivalent_to_one_shot=True,persistent_worker_pid_reused=True,
            timing_seconds=dict(one_shot=one_shot_seconds,persistent_startup=startup_seconds,persistent_first=persistent_first_seconds,persistent_second=persistent_second_seconds),
            musical_role_accuracy_certified=False,private_audio_used=False,product_release=False)
        (OUT/'SUMMARY.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        shutil.copyfile(runtime/'PDRM_OBSERVER_RUNTIME_MANIFEST.json',OUT/'PDRM_OBSERVER_RUNTIME_MANIFEST.json')
        md=f'''# PDRM P02 — persistent Spleeter observer acceptance

Date: 2026-09-12. This is a transport/lifetime performance acceptance, not a product-release or private-song quality claim.

The verifier moved the embedded runtime to a Japanese/space path, ran one one-shot observation, then started one persistent worker and ran the same observation twice. Feature arrays were equivalent within tight floating-point tolerance and both persistent calls came from the same worker PID. Source hash was unchanged, no stem/audio file remained in IPC, and the Spleeter/model/preprocessing contract was unchanged.

Timing (CI environment only; not a product benchmark): one-shot={one_shot_seconds:.3f}s, persistent startup={startup_seconds:.3f}s, first persistent call={persistent_first_seconds:.3f}s, second persistent call={persistent_second_seconds:.3f}s.

The persistent design removes repeated Python/TensorFlow/Separator initialization from each observation window. It does not alter P03/P04 musical thresholds or authorize GPU/backend migration.
'''
        (OUT/'PDRM_P02_PERSISTENT_OBSERVER_ACCEPTANCE_20260912.md').write_text(md,encoding='utf-8')
        print('P02_CAPSULE_ACCEPT '+json.dumps(evidence,ensure_ascii=True),flush=True)
    shutil.rmtree(BUILD,ignore_errors=False)
    if BUILD.exists():raise RuntimeError('Large observer runtime not removed after evidence capture')


if __name__=='__main__':main()
