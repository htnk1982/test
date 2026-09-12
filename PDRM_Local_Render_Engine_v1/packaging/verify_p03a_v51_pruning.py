"""Windows acceptance for v51 evidence-preserving observer pruning.

Builds no private audio. The same generated source/reference set is planned once
with accepted v50 and once with v51. Final audible control surfaces must match,
while v51 must execute fewer observer requests. TensorFlow/Spleeter stay inside
the packaged Python 3.11 runtime.
"""
from pathlib import Path
import json,platform,sys,tempfile
import numpy as np
import soundfile as sf

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import automatic_joint_v50 as v50
import automatic_joint_v51 as v51
from spleeter_observer_adapter_v48 import SpleeterRuntimeObserver
from integrated_finish_v40 import PlanningContext
from integration_contract_v40 import capture,RenderSnapshot

CAPSULE=ROOT/'P02_CAPSULE_WORK'/'PDRM_OBSERVER_RUNTIME'
OUT=ROOT/'P51_PRUNING_EVIDENCE'


def gate(t,a,b,fade=.06):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)


def weak_song(sr=48000,seconds=8.):
    t=np.arange(round(sr*seconds))/sr;g=gate(t,2.15,5.0)
    bass=g*(.004*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    bed=.035*np.sin(2*np.pi*1700*t)+.022*np.sin(2*np.pi*2300*t)
    return np.column_stack((bass+bed,bass+.92*bed))


def reference(sr=48000,seconds=8.,phase=0.,level=.11):
    t=np.arange(round(sr*seconds))/sr;low=np.zeros_like(t)
    for a,b,f in ((.8,1.2,55.),(2.0,2.5,73.4),(3.5,4.15,110.),(5.3,5.7,55.)):
        g=gate(t,a,b);low+=level*g*(np.sin(2*np.pi*f*t+phase)+.45*np.sin(4*np.pi*f*t)+.2*np.sin(6*np.pi*f*t))
    bed=.045*np.sin(2*np.pi*1600*t+phase)+.025*np.sin(2*np.pi*2400*t)
    return np.column_stack((low+bed,low+.94*bed))


def assert_audio_semantics_equal(a,b):
    aa=np.asarray(a['reduction_plan']['broad_plan']['low_cut_db'],float);bb=np.asarray(b['reduction_plan']['broad_plan']['low_cut_db'],float)
    if aa.shape!=bb.shape or not np.allclose(aa,bb,rtol=0,atol=1e-10):raise RuntimeError('v50/v51 reduction control differs')
    xa=a['additions'];xb=b['additions']
    if len(xa)!=len(xb):raise RuntimeError('v50/v51 addition count differs')
    for old,new in zip(xa,xb):
        if abs(float(old['target_hz'])-float(new['target_hz']))>1e-9:raise RuntimeError('target_hz differs')
        if list(old['source_frames'])!=list(new['source_frames']):raise RuntimeError('addition frames differ')
        if not np.allclose(old['envelope'],new['envelope'],rtol=0,atol=1e-9):raise RuntimeError('addition envelope differs')
        if abs(float(old['amplitude'])-float(new['amplitude']))>1e-9:raise RuntimeError('addition amplitude differs')
        if abs(float(old['phase_radians'])-float(new['phase_radians']))>1e-9:raise RuntimeError('addition phase differs')


def main():
    if sys.platform!='win32' or sys.version_info[:2]!=(3,12):raise RuntimeError('Windows Python 3.12 required')
    OUT.mkdir(exist_ok=True)
    if 'tensorflow' in sys.modules or 'spleeter' in sys.modules:raise RuntimeError('Main process contaminated before test')
    with tempfile.TemporaryDirectory(prefix='pdrm_v51_') as td:
        root=Path(td);refs=root/'refs';refs.mkdir();specs=[]
        for i in range(4):
            p=refs/f'ref{i}.wav';sf.write(p,reference(phase=.19*i,level=.105+.004*i),48000,subtype='DOUBLE');specs.append(dict(path=p,role='bass',quality='positive'))
        bundle=v51.make_calibration(specs);source=root/'weak source.wav';sf.write(source,weak_song(),48000,subtype='DOUBLE');before=capture(source);snap=RenderSnapshot.bind(before,before,{'accept':'v51-pruning'});ctx=PlanningContext(source,source,snap)

        o50=SpleeterRuntimeObserver(CAPSULE,work_root=root/'ipc50',timeout=300);p50=v50.AutomaticJointPlanner(bundle,o50);plan50=p50.build(ctx);o50.close()
        o51=SpleeterRuntimeObserver(CAPSULE,work_root=root/'ipc51',timeout=300);p51=v51.AutomaticJointPlanner(bundle,o51);plan51=p51.build(ctx);o51.close()
        assert_audio_semantics_equal(plan50,plan51)
        if capture(source)!=before:raise RuntimeError('Source changed')
        if 'tensorflow' in sys.modules or 'spleeter' in sys.modules:raise RuntimeError('Observer dependencies leaked into main process')
        if len(plan51['additions'])<1:raise RuntimeError('Fixture no longer exercises accepted same-f0 addition')
        opt=p51.last_report['observer_optimization']
        if not opt['observer_calls_executed']<opt['theoretical_v50_observer_calls']:raise RuntimeError('v51 did not prune observer calls: '+json.dumps(opt))
        if (root/'ipc50').exists() and any((root/'ipc50').iterdir()):raise RuntimeError('v50 IPC leak')
        if (root/'ipc51').exists() and any((root/'ipc51').iterdir()):raise RuntimeError('v51 IPC leak')
        evidence=dict(success=True,task='P03-v51-observer-pruning-real-spleeter',platform=platform.platform(),source_unchanged=True,
            v50_version=v50.VERSION,v51_version=v51.VERSION,v50_accepted=p50.last_report['accepted_additions'],v51_accepted=p51.last_report['accepted_additions'],
            audio_semantics_equal=True,observer_optimization=opt,main_imported_tensorflow=False,main_imported_spleeter=False,stem_audio_in_master=False,private_audio_used=False,product_release=False)
        (OUT/'SUMMARY.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print('P51_PRUNING '+json.dumps(evidence,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
