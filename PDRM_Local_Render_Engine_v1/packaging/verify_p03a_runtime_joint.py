"""Windows acceptance: real isolated Spleeter -> automatic joint planner -> WAV/MP3.

No private audio. The main Python 3.12 process never imports TensorFlow/Spleeter.
Event times are discovered by source_events_v41; the verifier does not pass them.
Every accepted same-f0 addition must have passed v50's original-source vetoes;
legacy strict or grouped fallback is acceptable, but this fixture is expected to
exercise the grouped fallback if Spleeter reproduces the observed ambiguity.
"""
from pathlib import Path
import json,platform,shutil,sys,tempfile
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import automatic_joint_v50 as planner50
from spleeter_observer_adapter_v48 import SpleeterRuntimeObserver
import integrated_finish_v40 as finish
from integration_contract_v40 import capture,file_hash
from target_settings import Targets

CAPSULE=ROOT/'P02_CAPSULE_WORK'/'PDRM_OBSERVER_RUNTIME'
OUT=ROOT/'P03A_RUNTIME_EVIDENCE'


def gate(t,a,b,fade=.06):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)


def weak_song(sr=48000,seconds=8.,scale=1.):
    t=np.arange(round(sr*seconds))/sr;g=gate(t,2.15,5.0)
    bass=scale*g*(.004*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    bed=.035*np.sin(2*np.pi*1700*t)+.022*np.sin(2*np.pi*2300*t)
    return np.column_stack((bass+bed,bass+.92*bed))


def reference(sr=48000,seconds=8.,phase=0.,level=.11):
    t=np.arange(round(sr*seconds))/sr;low=np.zeros_like(t)
    for a,b,f in ((.8,1.2,55.),(2.0,2.5,73.4),(3.5,4.15,110.),(5.3,5.7,55.)):
        g=gate(t,a,b);low+=level*g*(np.sin(2*np.pi*f*t+phase)+.45*np.sin(4*np.pi*f*t)+.2*np.sin(6*np.pi*f*t))
    bed=.045*np.sin(2*np.pi*1600*t+phase)+.025*np.sin(2*np.pi*2400*t)
    return np.column_stack((low+bed,low+.94*bed))


def main():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12):raise RuntimeError('Windows Python 3.12 main environment required')
    OUT.mkdir(exist_ok=True)
    if 'tensorflow' in sys.modules or 'spleeter' in sys.modules:raise RuntimeError('Main process already contaminated by observer dependencies')
    with tempfile.TemporaryDirectory(prefix='pdrm_p03a_runtime_') as td:
        root=Path(td);refs=root/'refs';inputs=root/'inputs';refs.mkdir();inputs.mkdir();specs=[]
        for i in range(4):
            p=refs/f'ref{i}.wav';sf.write(p,reference(phase=.19*i,level=.105+.004*i),48000,subtype='DOUBLE');specs.append(dict(path=p,role='bass',quality='positive'))
        bundle=planner50.make_calibration(specs);source=inputs/'自動判断 弱い基音.wav';sf.write(source,weak_song(),48000,subtype='DOUBLE');before=capture(source)
        observer=SpleeterRuntimeObserver(CAPSULE,work_root=root/'observer-ipc',timeout=300);planner=planner50.AutomaticJointPlanner(bundle,observer)
        report,folder=finish.run_lab(source,root/'work',planner,targets=Targets(),enable_lab=True,render_backend='joint-v46')
        if capture(source)!=before:raise RuntimeError('Original source changed')
        if 'tensorflow' in sys.modules or 'spleeter' in sys.modules:raise RuntimeError('TensorFlow/Spleeter leaked into main process')
        pr=report['planner_report'];low=report['lowend_report']
        if pr['manual_event_times_used'] is not False or pr['observer_provider']!='spleeter_runtime48':raise RuntimeError('Automatic/runtime provenance failed')
        if pr['automatically_discovered_events']<1 or pr['tonal_same_f0_candidates']<1:raise RuntimeError('Source-driven event/pitch discovery failed: '+json.dumps(pr['source_same_f0_refinements']))
        accepted=[r for r in pr.get('v50_same_f0_records',[]) if r.get('planner_resolution')=='V50_ADD_ACCEPTED']
        if pr.get('v50_accepted',0)<1 or not accepted or low['same_fundamental_additions']<1:raise RuntimeError('Real observer did not drive v50 same-f0 repair: '+json.dumps(dict(v50=pr.get('v50_same_f0_records'),relative_low=pr['relative_low'])))
        decision=accepted[0]['evidence']['source_decision'];path=decision['permission_path']
        if path not in ('LEGACY_STRICT_WITH_SOURCE_VETO','EXISTING_WEAK_F0_FALLBACK'):raise RuntimeError('Wrong v50 permission path '+str(path))
        if accepted[0]['evidence']['source_shape']['focus_upper_fraction']>.05 or accepted[0]['evidence']['source_proof']['fundamental_to_upper_ratio']>.15:raise RuntimeError('v50 source-shape/weakness budget exceeded')
        if report['old_note_sub_called'] is not False or report['sub_synthesis']!='SAME_FUNDAMENTAL_ONLY_CONNECTED':raise RuntimeError('Legacy/wrong sub path used')
        if not (folder/'MASTER.wav').is_file() or not (folder/'LISTEN_320kbps.mp3').is_file():raise RuntimeError('Final outputs missing')
        if report['master_metrics']['true_peak_max_dbtp_estimate']>-2 or report['codec_metrics']['true_peak_max_dbtp_estimate']>-2:raise RuntimeError('Final TP target failed')
        if (root/'observer-ipc').exists() and any((root/'observer-ipc').iterdir()):raise RuntimeError('Observer IPC leaked')
        evidence=dict(success=True,task='P03-A-real-observer-full-chain-v50',platform=platform.platform(),main_python=sys.version,source_sha256=before.file_sha256,source_unchanged=True,manual_event_times_used=False,
            automatically_discovered_events=pr['automatically_discovered_events'],tonal_candidates=pr['tonal_same_f0_candidates'],accepted_additions=pr['accepted_additions'],v50_accepted=pr['v50_accepted'],fallback_accepted=pr['fallback_accepted'],
            same_f0_permission_path=path,source_f0_ratio=accepted[0]['evidence']['source_proof']['fundamental_to_upper_ratio'],focus_upper_fraction=accepted[0]['evidence']['source_shape']['focus_upper_fraction'],
            observer_provider=pr['observer_provider'],observer_model_asset_sha256=pr['observer_identity']['model_asset_sha256'],observer_runtime_manifest_sha256=pr['observer_identity']['runtime_manifest_sha256'],
            main_imported_tensorflow=False,main_imported_spleeter=False,stem_audio_in_master=False,old_note_sub_called=False,relative_low=pr['relative_low'],lowend_assessment=report['lowend_assessment'],
            master_route=report['master']['auto_route'],wav_lufs=report['master_metrics']['lufs_i'],wav_tp=report['master_metrics']['true_peak_max_dbtp_estimate'],mp3_lufs=report['codec_metrics']['lufs_i'],mp3_tp=report['codec_metrics']['true_peak_max_dbtp_estimate'],
            master_sha256=file_hash(folder/'MASTER.wav'),mp3_sha256=file_hash(folder/'LISTEN_320kbps.mp3'),private_audio_used=False,subjective_quality='NOT_EVALUATED',product_release=False)
        (OUT/'SUMMARY.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print('P03A_RUNTIME '+json.dumps(evidence,ensure_ascii=True),flush=True)
    shutil.rmtree(ROOT/'P02_CAPSULE_WORK',ignore_errors=False)
    if (ROOT/'P02_CAPSULE_WORK').exists():raise RuntimeError('Large observer runtime retained after acceptance')

if __name__=='__main__':main()
