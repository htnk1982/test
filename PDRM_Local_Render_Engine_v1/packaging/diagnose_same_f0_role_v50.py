"""Diagnose real Spleeter evidence for same-fundamental fallback design.

Generated fixtures only. Fixed event windows are acceptable here because this is
observer characterization, not the product event finder. No stem audio is saved.
"""
from pathlib import Path
import json,math,shutil,sys,tempfile
import numpy as np
import soundfile as sf
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from spleeter_observer_adapter_v48 import SpleeterRuntimeObserver
import automatic_joint_v48 as v48
from integration_contract_v40 import capture

CAPSULE=ROOT/'P02_CAPSULE_WORK'/'PDRM_OBSERVER_RUNTIME';OUT=ROOT/'P03A_ROLE_DIAGNOSTIC'

def gate(t,a,b,fade=.06):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)

def fixture(kind,sr=48000,seconds=8.):
    t=np.arange(round(sr*seconds))/sr;g=gate(t,2.15,5.0);bed=.02*np.sin(2*np.pi*1700*t)+.012*np.sin(2*np.pi*2300*t)
    if kind=='weak_bass':x=g*(.004*np.cos(2*np.pi*55*t)+.080*np.cos(2*np.pi*110*t)+.040*np.cos(2*np.pi*165*t))
    elif kind=='kick':
        p=(t-.08)%0.5;x=.20*np.sin(2*np.pi*58*t)*np.exp(-38*p)
    elif kind=='deep_voice55':
        amps=(.018,.052,.047,.038,.030,.025,.020,.016)
        x=g*sum(a*np.sin(2*np.pi*55*(i+1)*t+.17*i) for i,a in enumerate(amps))*(1+.22*np.sin(2*np.pi*4.6*t))
    else:raise ValueError(kind)
    return np.column_stack((x+bed,x+.88*bed))

def shares(arr,key,mask):
    p=np.asarray(arr[key],float);r=p[:,:,1:]/np.maximum(p[:,:,1:].sum(axis=2,keepdims=True),1e-24);names=('drums','bass','other','vocals');out={}
    for ci in range(2):out['context'+str(ci+1)]={n:{'q20':float(np.percentile(r[ci,mask,j],20)),'q50':float(np.percentile(r[ci,mask,j],50))} for j,n in enumerate(names)}
    grouped=np.stack((r[:,:,0],r[:,:,1]+r[:,:,2],r[:,:,3]),axis=2);d=np.sum(abs(grouped[0]-grouped[1]),axis=1)/2
    out['grouped_dnbov_disagreement_p95']=float(np.percentile(d[mask],95));out['grouped_instrument_q20']=float(np.percentile(grouped[:,:,1].min(axis=0)[mask],20));return out

def source_spectral(path,a=2.15,b=5.0):
    with sf.SoundFile(path) as f:
        sr=f.samplerate;f.seek(round(a*sr));x=f.read(round((b-a)*sr),dtype='float64',always_2d=True)
    mono=x[:,np.argmax(np.mean(x*x,axis=0))];mono-=mono.mean();w=np.hanning(len(mono));freqs=np.fft.rfftfreq(len(mono),1/sr);z=np.fft.rfft(mono*w);vals={}
    for lo,hi,name in ((25,120,'low'),(120,300,'body'),(300,450,'focus'),(450,700,'upper_focus')):
        sel=(freqs>=lo)&(freqs<hi);vals[name]=float(np.sum(abs(z[sel])**2))
    total=max(sum(vals.values()),1e-24);vals['low_body_fraction']=float((vals['low']+vals['body'])/total);vals['focus_upper_fraction']=float((vals['focus']+vals['upper_focus'])/total);return vals

def main():
    if sys.platform!='win32':raise RuntimeError('Windows diagnostic required')
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pdrm_role_diag_') as td:
        root=Path(td);inputs=root/'inputs';inputs.mkdir();work=root/'observer_work';work.mkdir();obs=SpleeterRuntimeObserver(CAPSULE,work_root=work,timeout=300);records={}
        for kind in ('weak_bass','kick','deep_voice55'):
            p=inputs/(kind+'.wav');sf.write(p,fixture(kind),48000,subtype='DOUBLE');ident=capture(p);arr,meta=obs.observe(p,2.0,6.0);t=np.asarray(arr['time']);mask=(t>=2.25)&(t<4.9)
            proof=v48._present_fundamental(p,dict(start_frame=round(2.15*48000),stop_frame=round(5.0*48000),start_seconds=2.15,end_seconds=5.0,pitch_status='PERIODIC_CANDIDATE',pitch_hz=55.0))
            records[kind]=dict(low_shares=shares(arr,'low_power',mask),body_shares=shares(arr,'body_power',mask),focus_shares=shares(arr,'focus_power',mask),source_spectral=source_spectral(p),physical_same_f0_proof=proof,
                bass_pitch_context1_median=float(np.median(arr['bass_f0_hz'][0,mask])),bass_pitch_context2_median=float(np.median(arr['bass_f0_hz'][1,mask])),bass_periodicity_min_q20=float(np.percentile(arr['bass_periodicity'][:,mask].min(axis=0),20)),source_sha256=ident.file_sha256)
        if any(work.iterdir()):raise RuntimeError('Observer work leaked')
        result=dict(success=True,records=records,scope='REAL_SPLEETER_FEATURE_DIAGNOSTIC;_GENERATED_COUNTEREXAMPLES;_NO_PRIVATE_AUDIO',stem_audio_saved=False)
        (OUT/'SUMMARY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print('P03A_ROLE_DIAG '+json.dumps(result,ensure_ascii=True),flush=True)
    shutil.rmtree(ROOT/'P02_CAPSULE_WORK',ignore_errors=False)
if __name__=='__main__':main()
