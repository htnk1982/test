"""Frozen-binary QA entry. Generates its own synthetic input; not a mastering UI.

No user music, model weights, private atlas or remote requests. This executable
is built/run only for deployment verification and is not the replacement app.
"""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,sys
if not getattr(sys,'frozen',False):
    sys.path.insert(0,str(Path(__file__).resolve().parent/'tests'))
import numpy as np
import soundfile as sf
import integrated_finish_v40 as finish
import lowend_coordinator_v40 as broad
import joint_lowend_v42 as joint
from physical_decay_bridge_v42 import confirm_relative_tail
from integration_contract_v40 import capture,digest,file_hash
from target_settings import Targets
from decay39_fixtures import audio_fixture,audio_atlas,oracle,event


class FixturePlanner:
    def __init__(self,mode):
        self.mode=mode;self.atlas=audio_atlas(sr=48000);self.last_report=None
    def identity(self):
        return dict(planner_id='joint42_qa_'+self.mode,calibration_sha256=self.atlas['sha256'],evidence_scope='engineering_fixture')
    def preflight(self):
        if self.mode not in ('bypass','tail','joint'):raise ValueError('Unknown QA mode')
    def build(self,context,progress=None):
        snap=context.snapshot;sr=snap.source.samplerate;n=snap.source.frames
        cuts=[]
        if self.mode=='joint':
            cuts=[broad.CutProposal('broad_body','lowmid',(0,round(.25*sr),n-round(.25*sr),n),(0.,.75,.75,0.),'EXPLICIT_QA_CURVE')]
        bp=broad.compile_plan(snap,cuts,planner_id='qa-broad',calibration_sha256=self.atlas['sha256'],evidence_scope='engineering_fixture',assessment='CANDIDATE' if cuts else 'KEEP_SUPPORTED')
        narrow=[];detail=None
        if self.mode!='bypass':
            e=event();support=oracle(np.arange(round(n/sr/.02))*.02,e,snap.source.file_sha256)
            p,detail=confirm_relative_tail(context,e,self.atlas,support,allow_test_evidence=True,progress=progress)
            if p is not None:narrow=[p]
        pid=self.identity();assessment='CANDIDATE' if cuts or narrow else 'KEEP_SUPPORTED'
        self.last_report=dict(scope='SYNTHETIC_EVENT_AND_OBSERVER;_NOT_AUTOMATIC_PART_ASSOCIATION',tail_confirmation=detail)
        return joint.compile_plan(snap,bp,narrow,planner_id=pid['planner_id'],calibration_sha256=pid['calibration_sha256'],
            evidence_scope=pid['evidence_scope'],assessment=assessment)


def ratio(path):
    with sf.SoundFile(path) as f:
        sr=f.samplerate;f.seek(round(1.6*sr));x=f.read(round(1.4*sr),dtype='float64',always_2d=True)
    t=np.arange(len(x))/sr;w=np.hanning(len(x));powers=[]
    for hz in (320.,640.):
        z=2*np.sum(x*w[:,None]*np.exp(-2j*np.pi*hz*t)[:,None],axis=0)/w.sum()
        powers.append(float(np.mean(abs(z)**2)))
    return float(10*np.log10(max(powers[0],1e-24)/max(powers[1],1e-24)))


def run_selftest(out,*,include_stress=True):
    out=Path(out)
    if out.exists() and any(out.iterdir()):raise FileExistsError('QA output must be empty')
    out.mkdir(parents=True,exist_ok=True);records=[]
    with TemporaryDirectory(prefix='pdrm_joint42_qa_') as tmp:
        root=Path(tmp);inp=root/'inputs';inp.mkdir()
        # Standalone DSP tests cover 32 kHz too. The existing full mastering
        # chain intentionally supports 44.1/48/88.2/96 kHz; do not relax it.
        clean,bad,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.)
        sf.write(inp/'bad.wav',bad,48000,subtype='DOUBLE');sf.write(inp/'clean.wav',clean,48000,subtype='DOUBLE')
        cases=[('BYPASS','bad.wav','bypass',-12.),('TAIL','bad.wav','tail',-12.),('JOINT','bad.wav','joint',-12.),('CLEAN_KEEP','clean.wav','tail',-12.)]
        if include_stress:cases.append(('JOINT_STRESS','bad.wav','joint',-10.))
        for name,filename,mode,target in cases:
            source=inp/filename;original=capture(source);planner=FixturePlanner(mode)
            targets=Targets(wav_lufs=target,wav_tp=-2.,mp3_lufs=-14.,mp3_tp=-2.)
            r,folder=finish.run_lab(source,root/name,planner,targets=targets,enable_lab=True,render_backend='joint-v42')
            assert capture(source)==original
            assert r['intermediate_audio_removed'] and not list((root/name).glob('.integration40_*'))
            assert abs(r['master_metrics']['lufs_i']-target)<.03
            assert r['master_metrics']['true_peak_max_dbtp_estimate']<=-2
            assert abs(r['codec_metrics']['lufs_i']+14)<.03
            assert r['codec_metrics']['true_peak_max_dbtp_estimate']<=-2
            if name in ('TAIL','JOINT','JOINT_STRESS'):assert r['lowend_report']['narrow_operations']>0
            if name=='CLEAN_KEEP':assert not r['lowend_report']['waveform_changed']
            rec=dict(case=name,backend=r['render_backend'],assessment=r['lowend_assessment'],
                lowend_waveform_changed=r['lowend_report']['waveform_changed'],narrow_operations=r['lowend_report']['narrow_operations'],
                prep_route=r['preparation']['auto_route'],master_route=r['master']['auto_route'],
                codec_routes=[p['auto_report']['auto_route'] for p in r['codec_trials']],
                wav_lufs=r['master_metrics']['lufs_i'],wav_tp=r['master_metrics']['true_peak_max_dbtp_estimate'],
                mp3_lufs=r['codec_metrics']['lufs_i'],mp3_tp=r['codec_metrics']['true_peak_max_dbtp_estimate'],
                master_pcm_sha256=capture(folder/'MASTER.wav').pcm_sha256,
                mp3_sha256=file_hash(folder/'LISTEN_320kbps.mp3'),ffmpeg_sha256=r['identity']['ffmpeg_sha256'],
                target_to_peer_db=ratio(folder/'MASTER.wav'),source_unchanged=True,work_bytes_removed=r['work_bytes_removed'],
                frozen=bool(getattr(sys,'frozen',False)),manual_synthetic_event=True,neural_inference=False,subjective_quality='NOT_EVALUATED')
            records.append(rec);(out/(name+'_REPORT.json')).write_text(json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            print('JOINT42_CASE '+json.dumps(rec),flush=True)
        base=next(r for r in records if r['case']=='BYPASS')['target_to_peer_db']
        tail=next(r for r in records if r['case']=='TAIL')['target_to_peer_db']
        assert tail<base-.03,(base,tail)
    summary=dict(success=True,frozen=bool(getattr(sys,'frozen',False)),cases=records,
        scope='SYNTHETIC_PIPELINE_QA;_NOT_USER_TRACK_ACCEPTANCE',production_exe_changed=False,network_required=False)
    (out/'SUMMARY.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return summary


def main():
    ap=argparse.ArgumentParser(description='Synthetic self-test only. Not a user mastering program.')
    ap.add_argument('--self-test-output',type=Path,required=True);ap.add_argument('--no-stress',action='store_true')
    a=ap.parse_args();run_selftest(a.self_test_output,include_stress=not a.no_stress)

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    main()
