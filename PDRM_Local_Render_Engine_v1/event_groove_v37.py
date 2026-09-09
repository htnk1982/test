"""Same-fundamental event planner connected to dual-context observer evidence.

A period estimate is not permission. Missing fundamental restoration and octave
creation are deliberately not implemented here. Quantity ratios are explicit LAB
budgets, not learned preference probabilities or production mastering approval.
"""
from dataclasses import dataclass,asdict
from pathlib import Path
import math,hashlib
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import distance_transform_edt
VERSION='event-groove-lab-0.1.0'

@dataclass(frozen=True)
class Config:
    min_event_seconds:float=.12
    max_event_seconds:float=3.
    min_role_share:float=.55
    min_supported_fraction:float=.80
    max_context_disagreement:float=.25
    min_periodicity:float=.85
    pitch_tolerance_cents:float=50.
    desired_partial_ratio:float=.4
    max_added_rms_fraction:float=.10
    max_input_peak:float=.98
    def validate(self):
        for k,v in asdict(self).items():
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Invalid config '+k)
        if not 0<self.min_event_seconds<self.max_event_seconds<=5:raise ValueError('Invalid event limits')
        if not .5<=self.min_role_share<=1 or not .5<=self.min_supported_fraction<=1 or not 0<self.min_periodicity<=1:raise ValueError('Invalid evidence budgets')
        if not 0<self.desired_partial_ratio<=.5 or not 0<self.max_added_rms_fraction<=.1:raise ValueError('Invalid addition budget')
        return self

def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()

def _check(arrays,meta,digest):
    if meta.get('source_sha256')!=digest:raise ValueError('Observer belongs to another source')
    if meta.get('version')!='role-observer-0.2.0':raise ValueError('Observer schema mismatch')
    if meta.get('source_order')!=['mix','drums','bass','other','vocals']:raise ValueError('Observer source ordering mismatch')
    t=np.asarray(arrays['time'],float)
    if len(t)<2 or not np.isfinite(t).all() or np.any(np.diff(t)<=0):raise ValueError('Invalid observer clock')
    if not np.allclose(np.diff(t),.01,atol=1e-8):raise ValueError('Observer clock is not seconds at 10ms')
    for k in ('low_power','body_power','focus_power'):
        p=np.asarray(arrays[k]);
        if p.shape!=(2,len(t),5) or not np.isfinite(p).all() or np.any(p<0):raise ValueError('Invalid power curves')
    for k in ('bass_f0_hz','bass_periodicity'):
        p=np.asarray(arrays[k]);
        if p.shape!=(2,len(t)) or not np.isfinite(p).all() or np.any(p<0):raise ValueError('Invalid pitch evidence')
    if meta['start_seconds']>t[0]+.011 or meta['end_seconds']<t[-1]-.011:raise ValueError('Observer metadata/clock disagreement')
    return t

def permit(event,arrays,meta,digest,cfg=Config()):
    cfg.validate()
    a,b,f0,target=(float(event[k]) for k in ('start','end','source_f0_hz','target_hz'))
    if not all(math.isfinite(v) for v in (a,b,f0,target)) or not 0<=a<b or min(f0,target)<=0:raise ValueError('Invalid event')
    out=dict(event=event,version=VERSION,allowed=False,reason_codes=[],probability_claim=False)
    if abs(1200*math.log2(f0/target))>cfg.pitch_tolerance_cents:out['reason_codes'].append('DENY_NEW_OCTAVE')
    if not 30<=target<=70:out['reason_codes'].append('ABSTAIN_TARGET_OUTSIDE_SUB_SCOPE')
    if not cfg.min_event_seconds<=b-a<=cfg.max_event_seconds:out['reason_codes'].append('ABSTAIN_DURATION')
    if arrays is None or meta is None:
        out['reason_codes'].append('ABSTAIN_NO_OBSERVER');return out
    t=_check(arrays,meta,digest)
    if a<meta['start_seconds']+.001 or b>meta['end_seconds']-.001:
        out['reason_codes'].append('ABSTAIN_OUTSIDE_OBSERVATION');return out
    keep=(t>=a)&(t<b)
    if keep.sum()<6:out['reason_codes'].append('ABSTAIN_INSUFFICIENT_FRAMES');return out
    p=np.asarray(arrays['low_power'])+np.asarray(arrays['body_power'])
    shares=p[:,:,1:]/np.maximum(p[:,:,1:].sum(axis=-1,keepdims=True),1e-24)
    bass_share=shares[:,:,1].min(axis=0)
    disagreement=np.sum(abs(shares[0]-shares[1]),axis=-1)/2
    pitch=np.asarray(arrays['bass_f0_hz']);period=np.asarray(arrays['bass_periodicity'])
    cents=np.abs(1200*np.log2(np.maximum(pitch,1e-12)/f0))
    reliable=(bass_share>=cfg.min_role_share)&(disagreement<=cfg.max_context_disagreement)&(cents.max(axis=0)<=cfg.pitch_tolerance_cents)&(period.min(axis=0)>=cfg.min_periodicity)
    # Guard extremely small stem leakage even when its share is locally large.
    energy=p[:,:,2].min(axis=0); peak=max(float(energy.max()),1e-24)
    reliable&=energy>max(peak*1e-4,1e-12)
    fraction=float(np.mean(reliable[keep]))
    out.update(local_bass_share_q20=float(np.percentile(bass_share[keep],20)),
        local_supported_fraction=fraction,local_disagreement_p95=float(np.percentile(disagreement[keep],95)),
        time_start=a,time_end=b,source_sha256=digest)
    if fraction<cfg.min_supported_fraction:out['reason_codes'].append('ABSTAIN_LOCAL_ROLE_OR_PITCH')
    out['allowed']=not out['reason_codes']
    if out['allowed']:
        out['reason_codes']=['ALLOW_SAME_FUNDAMENTAL_CANDIDATE']
        out['render_support_times']=t[keep].tolist()
        out['render_support_mask']=reliable[keep].astype(int).tolist()
    return out

def _components(x,sr,f0):
    t=np.arange(len(x))/sr;mono=x.mean(axis=1)
    design=np.column_stack([v for h in range(1,7) for v in (np.cos(2*np.pi*f0*h*t),np.sin(2*np.pi*f0*h*t))])
    w=signal.windows.tukey(len(x),alpha=.2)
    coeff=np.linalg.lstsq(design*w[:,None],mono*w,rcond=None)[0]
    amps=np.hypot(coeff[::2],coeff[1::2])
    return t,design[:,:2]@coeff[:2],amps,math.atan2(-coeff[1],coeff[0])

def process_event(source,event,arrays,meta,cfg=Config()):
    """Read immutable source; return a *difference only*, with native sample span.

    An absent/uncertain event never produces an oscillator. Returned sample data
    are synthesized from the original-mix fit, not copied from estimated stems.
    """
    source=Path(source);digest=file_hash(source)
    decision=permit(event,arrays,meta,digest,cfg)
    info=sf.info(source);a=round(float(event['start'])*info.samplerate);b=round(float(event['end'])*info.samplerate)
    if info.channels!=2 or a<0 or b>info.frames or a>=b:raise ValueError('Event/source geometry mismatch')
    with sf.SoundFile(source) as f:f.seek(a);x=f.read(b-a,dtype='float64',always_2d=True)
    if not np.isfinite(x).all():raise ValueError('Nonfinite source')
    if not decision['allowed']:
        return np.zeros((b-a,2)),dict(decision,action='NO_ADDITION',start_frame=a,end_frame=b)
    t,x0,amps,phase=_components(x,info.samplerate,float(event['source_f0_hz']))
    upper=float(max(amps[1:]));rms=float(np.sqrt(np.mean(x*x)))
    target_amp=min(cfg.desired_partial_ratio*upper,rms*.5)
    # No missing-fundamental generation by this module: require actual same note.
    if amps[0]<max(upper*.015,1e-6):
        return np.zeros_like(x),dict(decision,action='NO_ADDITION',reason_codes=['ABSTAIN_MISSING_FUNDAMENTAL_REPAIR_UNIMPLEMENTED'],start_frame=a,end_frame=b)
    if amps[0]>=target_amp:
        return np.zeros_like(x),dict(decision,action='NO_ADDITION',reason_codes=['KEEP_ALREADY_SUFFICIENT'],start_frame=a,end_frame=b)
    ot=arrays['time'];power=arrays['low_power']+arrays['body_power'];en=np.sqrt(np.maximum(power[:,:,2].min(axis=0),0))
    env=np.interp(event['start']+t,ot,en,left=0,right=0);env/=max(float(env.max()),1e-24)
    dur=len(x)/info.samplerate;fade=min(.060,dur/4)
    edge=np.minimum(np.clip(t/fade,0,1),np.clip((dur-t-1/info.samplerate)/fade,0,1));edge=edge*edge*(3-2*edge)
    env*=edge
    supported=np.interp(event['start']+t,decision['render_support_times'],decision['render_support_mask'],left=0,right=0)>.999
    env*=np.clip(distance_transform_edt(supported)/(fade*info.samplerate),0,1)
    u=env*np.cos(2*np.pi*event['target_hz']*t+phase)
    # Explicit mixed-energy equation, including correlation, not amplitude diff.
    p0=float(np.mean(x0*x0));pu=float(np.mean(u*u));cross=float(np.mean(x0*u));wanted=target_amp**2/2
    amount=max(0.,(-cross+math.sqrt(max(0.,cross*cross+pu*(wanted-p0))))/max(pu,1e-24))
    cap=cfg.max_added_rms_fraction*rms/math.sqrt(max(pu,1e-24));amount=min(amount,cap)
    d=np.repeat((amount*u)[:,None],2,axis=1);d[np.all(x==0,axis=1)]=0;y=x+d
    if np.max(abs(y))>cfg.max_input_peak:
        return np.zeros_like(x),dict(decision,action='NO_ADDITION',reason_codes=['ABSTAIN_PHYSICAL_PEAK'],start_frame=a,end_frame=b)
    if file_hash(source)!=digest:raise RuntimeError('Source changed')
    return d,dict(decision,action='SAME_FUNDAMENTAL_CANDIDATE',start_frame=a,end_frame=b,
        amount=amount,added_rms_fraction=float(np.sqrt(np.mean(d*d))/max(rms,1e-24)),
        fundamental_input_amplitude=float(amps[0]),target_amplitude=target_amp,
        quantity_calibration='EXPLICIT_LAB_BUDGET_NOT_REFERENCE_CALIBRATED',
        subjective_quality='NOT_EVALUATED',stem_samples_in_output=False)
