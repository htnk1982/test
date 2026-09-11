"""Physical same-fundamental bridge with conservative v50 source permission.

The audible oscillator is still fit/reconfirmed on the prepared original 2mix.
No separator audio enters output. The fallback can only rescue context/role
ambiguity for an already-present weak f0; it cannot create an octave or a
missing fundamental, and it applies source-shape/drum/vocal/pitch vetoes first.
"""
from __future__ import annotations
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import distance_transform_edt
import event_groove_v37 as event_core
import same_f0_permission_v50 as permission
from physical_add_bridge_v46 import SameFundamentalAdd,MAX_ADD_PEAK,_read_event,_components
from integration_contract_v40 import digest

VERSION='physical-add-bridge-lab-0.2.0'


def source_shape(path,start_seconds,end_seconds):
    path=Path(path)
    with sf.SoundFile(path) as f:
        sr=f.samplerate;a=round(float(start_seconds)*sr);b=round(float(end_seconds)*sr)
        if f.channels!=2 or a<0 or b>f.frames or a>=b:raise ValueError('Invalid source event geometry')
        f.seek(a);x=f.read(b-a,dtype='float64',always_2d=True)
    if len(x)<round(.10*sr) or not np.isfinite(x).all():raise ValueError('Invalid source event')
    mono=x[:,int(np.argmax(np.mean(x*x,axis=0)))];mono=mono-mono.mean();w=signal.windows.tukey(len(mono),alpha=.2);freq=np.fft.rfftfreq(len(mono),1/sr);z=np.fft.rfft(mono*w)
    values={}
    for lo,hi,name in ((25,120,'low'),(120,300,'body'),(300,450,'focus'),(450,700,'upper_focus')):
        q=(freq>=lo)&(freq<hi);values[name]=float(np.sum(abs(z[q])**2))
    total=max(sum(values.values()),1e-24);values['low_body_fraction']=float((values['low']+values['body'])/total);values['focus_upper_fraction']=float((values['focus']+values['upper_focus'])/total)
    return values


def confirm(context,event,arrays,meta,source_proof,cfg=event_core.Config(),fallback_cfg=permission.Config()):
    snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path);cfg.validate();fallback_cfg.validate()
    shape=source_shape(context.source_path,event['start'],event['end'])
    decision=permission.permit(event,arrays,meta,snapshot.source.file_sha256,source_proof,shape,fallback_cfg)
    record=dict(version=VERSION,source_decision=decision,source_sha256=snapshot.source.file_sha256,physical_sha256=snapshot.physical.file_sha256,snapshot_sha256=snapshot.token,
        source_shape=shape,source_proof=source_proof,stem_samples_in_output=False,new_octave_allowed=False,subjective_quality='NOT_EVALUATED')
    if not decision['allowed']:
        return None,dict(record,status=decision['reason_codes'][0] if decision['reason_codes'] else 'ABSTAIN_SOURCE_PERMISSION')
    f0=float(event['source_f0_hz']);target=float(event['target_hz'])
    if abs(1200*math.log2(f0/target))>cfg.pitch_tolerance_cents:return None,dict(record,status='DENY_NEW_OCTAVE')
    sr0=snapshot.source.samplerate;sr=snapshot.physical.samplerate;a0=round(float(event['start'])*sr0);b0=round(float(event['end'])*sr0);a=snapshot.clock.nearest(a0);b=snapshot.clock.nearest(b0)
    if b<=a:return None,dict(record,status='ABSTAIN_COLLAPSED_PHYSICAL_EVENT')
    x=_read_event(context.physical_path,a,b);t,fund,amps,phase=_components(x,sr,f0)
    if len(amps)<2:return None,dict(record,status='ABSTAIN_INSUFFICIENT_PHYSICAL_HARMONICS')
    upper=float(max(amps[1:]));rms=float(np.sqrt(np.mean(x*x)));target_amp=min(cfg.desired_partial_ratio*upper,rms*.5)
    if amps[0]<max(upper*.015,1e-6):return None,dict(record,status='ABSTAIN_MISSING_FUNDAMENTAL_REPAIR_UNIMPLEMENTED',physical_fundamental=float(amps[0]),target_amplitude=target_amp)
    if amps[0]>=target_amp:return None,dict(record,status='KEEP_ALREADY_SUFFICIENT',physical_fundamental=float(amps[0]),target_amplitude=target_amp)
    ot=np.asarray(arrays['time'],float);power=np.asarray(arrays['low_power'],float)+np.asarray(arrays['body_power'],float)
    indices=tuple(int(v) for v in decision.get('envelope_role_indices',[2]));env_power=np.zeros(len(ot),float)
    for idx in indices:env_power+=power[:,:,idx].min(axis=0)
    env=np.sqrt(np.maximum(env_power,0));env/=max(float(env.max()),1e-24)
    source_seconds=float(event['start'])+t;env=np.interp(source_seconds,ot,env,left=0,right=0)
    supported=np.interp(source_seconds,decision['render_support_times'],decision['render_support_mask'],left=0,right=0)>.999
    fade=min(.06,len(x)/sr/4);dist=distance_transform_edt(supported)/sr;edge=np.minimum(np.clip(t/fade,0,1),np.clip((len(x)/sr-t-1/sr)/fade,0,1));edge=edge*edge*(3-2*edge);env*=np.clip(dist/max(fade,1/sr),0,1)*edge
    if env.max()<=0:return None,dict(record,status='ABSTAIN_NO_SUPPORTED_PHYSICAL_ENVELOPE')
    u=env*np.cos(2*np.pi*target*t+phase);p0=float(np.mean(fund*fund));pu=float(np.mean(u*u));cross=float(np.mean(fund*u));wanted=target_amp**2/2
    amount=max(0.,(-cross+math.sqrt(max(0.,cross*cross+pu*(wanted-p0))))/max(pu,1e-24));cap=cfg.max_added_rms_fraction*rms/math.sqrt(max(pu,1e-24));amount=min(amount,cap,MAX_ADD_PEAK)
    if amount<=1e-7:return None,dict(record,status='KEEP_NEGLIGIBLE_PHYSICAL_DEFICIT')
    y=x+np.repeat((amount*u)[:,None],2,axis=1)
    if np.max(np.abs(y))>cfg.max_input_peak:return None,dict(record,status='ABSTAIN_PHYSICAL_PEAK')
    frames=np.linspace(a0,b0,min(301,max(3,round((b0-a0)/sr0/.01)+1))).round().astype(int);frames=np.unique(frames);et=(frames-a0)/sr0;values=np.interp(et,t,env,left=0,right=0);values[0]=0;values[-1]=0
    if not np.any(values>0):return None,dict(record,status='ABSTAIN_EMPTY_COMPACT_ENVELOPE')
    evidence=dict(record,status='PHYSICALLY_CONFIRMED_SAME_FUNDAMENTAL',physical_start_frame=a,physical_stop_frame=b,source_start_frame=a0,source_stop_frame=b0,
        physical_fundamental=float(amps[0]),physical_upper_max=upper,target_amplitude=target_amp,addition_amplitude=float(amount),added_rms_fraction=float(np.sqrt(np.mean((amount*u)**2))/max(rms,1e-24)),
        envelope_role_indices=list(indices),quantity_calibration='ENGINEERING_BUDGET_NOT_PERSONAL_TASTE')
    h=digest(evidence);proposal=SameFundamentalAdd('same_f0_'+h[:24],target,tuple(int(v) for v in frames),tuple(float(v) for v in values),float(amount),float(phase),h,snapshot.physical.file_sha256)
    proposal.validate(snapshot);snapshot.verify(context.source_path,context.physical_path);return proposal,evidence
