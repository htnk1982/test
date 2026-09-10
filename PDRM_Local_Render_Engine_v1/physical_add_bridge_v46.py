"""Bridge source-side same-fundamental permission to the prepared 2mix.

No octave creation. No stem samples enter output. Observer evidence only permits
an event; phase, existing fundamental, harmonics, headroom and addition amount
are remeasured on the actual HE/AUTO prepared stereo mix. Engineering quantity
limits are not a personal-taste calibration and remain a P03/P05 dependency.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import distance_transform_edt
import event_groove_v37 as event_core
from integration_contract_v40 import digest

VERSION='physical-add-bridge-lab-0.1.0'
MAX_ADD_PEAK=.08

@dataclass(frozen=True)
class SameFundamentalAdd:
    proposal_id:str
    target_hz:float
    source_frames:tuple[int,...]
    envelope:tuple[float,...]
    amplitude:float
    phase_radians:float
    evidence_sha256:str
    physical_confirmation_sha256:str
    reason:str='SOURCE_ROLE_PITCH_AND_PHYSICAL_DEFICIT'
    def validate(self,snapshot):
        if not isinstance(self.proposal_id,str) or not self.proposal_id:raise ValueError('Named addition required')
        if isinstance(self.target_hz,bool) or not isinstance(self.target_hz,(int,float)) or not math.isfinite(self.target_hz) or not 30<=self.target_hz<=70:raise ValueError('Addition outside sub scope')
        if not 2<=len(self.source_frames)==len(self.envelope)<=1001:raise ValueError('Invalid envelope geometry')
        if any(type(v) is not int for v in self.source_frames) or any(b<=a for a,b in zip(self.source_frames,self.source_frames[1:])):raise ValueError('Source frame clock required')
        if self.source_frames[0]<0 or self.source_frames[-1]>snapshot.source.frames:raise ValueError('Addition outside source')
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=1 for v in self.envelope):raise ValueError('Invalid envelope')
        if self.envelope[0]!=0 or self.envelope[-1]!=0 or not any(v>0 for v in self.envelope):raise ValueError('Addition requires tapered nonzero support')
        if isinstance(self.amplitude,bool) or not isinstance(self.amplitude,(int,float)) or not math.isfinite(self.amplitude) or not 0<self.amplitude<=MAX_ADD_PEAK:raise ValueError('Addition amplitude exceeds engineering budget')
        if not math.isfinite(self.phase_radians):raise ValueError('Invalid phase')
        if len(self.evidence_sha256)!=64 or self.physical_confirmation_sha256!=snapshot.physical.file_sha256:raise ValueError('Evidence/physical confirmation mismatch')
        mapped=[snapshot.clock.nearest(v) for v in self.source_frames]
        if any(b<=a for a,b in zip(mapped,mapped[1:])):raise ValueError('Mapped envelope collapses')
        return self


def _read_event(path,start,stop):
    with sf.SoundFile(path) as f:
        if f.channels!=2 or start<0 or stop>f.frames or start>=stop:raise ValueError('Invalid physical event geometry')
        f.seek(start);x=f.read(stop-start,dtype='float64',always_2d=True)
    if len(x)!=stop-start or not np.isfinite(x).all():raise ValueError('Invalid physical event')
    return x


def _components(x,sr,f0):
    t=np.arange(len(x))/sr;mono=x.mean(axis=1);w=signal.windows.tukey(len(x),alpha=.2)
    cols=[v for h in range(1,7) if h*f0<min(sr/2-50,900) for v in (np.cos(2*np.pi*f0*h*t),np.sin(2*np.pi*f0*h*t))]
    design=np.column_stack(cols);coef=np.linalg.lstsq(design*w[:,None],mono*w,rcond=None)[0]
    amps=np.hypot(coef[::2],coef[1::2]);phase=math.atan2(-coef[1],coef[0])
    return t,design[:,:2]@coef[:2],amps,phase


def confirm(context,event,arrays,meta,cfg=event_core.Config()):
    """Return proposal-or-None plus explicit decision evidence."""
    snapshot=context.snapshot;snapshot.verify(context.source_path,context.physical_path);cfg.validate()
    decision=event_core.permit(event,arrays,meta,snapshot.source.file_sha256,cfg)
    record=dict(version=VERSION,source_decision=decision,source_sha256=snapshot.source.file_sha256,
        physical_sha256=snapshot.physical.file_sha256,snapshot_sha256=snapshot.token,
        stem_samples_in_output=False,new_octave_allowed=False,subjective_quality='NOT_EVALUATED')
    if not decision['allowed']:
        return None,dict(record,status=decision['reason_codes'][0] if decision['reason_codes'] else 'ABSTAIN_SOURCE_PERMISSION')
    # Permit() already checks f0 ~= target; repeat at this bridge boundary.
    f0=float(event['source_f0_hz']);target=float(event['target_hz'])
    if abs(1200*math.log2(f0/target))>cfg.pitch_tolerance_cents:return None,dict(record,status='DENY_NEW_OCTAVE')
    sr0=snapshot.source.samplerate;sr=snapshot.physical.samplerate
    a0=round(float(event['start'])*sr0);b0=round(float(event['end'])*sr0)
    a=snapshot.clock.nearest(a0);b=snapshot.clock.nearest(b0)
    if b<=a:return None,dict(record,status='ABSTAIN_COLLAPSED_PHYSICAL_EVENT')
    x=_read_event(context.physical_path,a,b);t,fund,amps,phase=_components(x,sr,f0)
    if len(amps)<2:return None,dict(record,status='ABSTAIN_INSUFFICIENT_PHYSICAL_HARMONICS')
    upper=float(max(amps[1:]));rms=float(np.sqrt(np.mean(x*x)));target_amp=min(cfg.desired_partial_ratio*upper,rms*.5)
    if amps[0]<max(upper*.015,1e-6):
        return None,dict(record,status='ABSTAIN_MISSING_FUNDAMENTAL_REPAIR_UNIMPLEMENTED',physical_fundamental=float(amps[0]),target_amplitude=target_amp)
    if amps[0]>=target_amp:
        return None,dict(record,status='KEEP_ALREADY_SUFFICIENT',physical_fundamental=float(amps[0]),target_amplitude=target_amp)
    ot=np.asarray(arrays['time'],float);power=np.asarray(arrays['low_power'])+np.asarray(arrays['body_power'])
    env=np.sqrt(np.maximum(power[:,:,2].min(axis=0),0));env/=max(float(env.max()),1e-24)
    source_seconds=float(event['start'])+t
    env=np.interp(source_seconds,ot,env,left=0,right=0)
    supported=np.interp(source_seconds,decision['render_support_times'],decision['render_support_mask'],left=0,right=0)>.999
    fade=min(.06,len(x)/sr/4);dist=distance_transform_edt(supported)/sr
    edge=np.minimum(np.clip(t/fade,0,1),np.clip((len(x)/sr-t-1/sr)/fade,0,1));edge=edge*edge*(3-2*edge)
    env*=np.clip(dist/max(fade,1/sr),0,1)*edge
    if env.max()<=0:return None,dict(record,status='ABSTAIN_NO_SUPPORTED_PHYSICAL_ENVELOPE')
    u=env*np.cos(2*np.pi*target*t+phase);p0=float(np.mean(fund*fund));pu=float(np.mean(u*u));cross=float(np.mean(fund*u));wanted=target_amp**2/2
    amount=max(0.,(-cross+math.sqrt(max(0.,cross*cross+pu*(wanted-p0))))/max(pu,1e-24))
    cap=cfg.max_added_rms_fraction*rms/math.sqrt(max(pu,1e-24));amount=min(amount,cap,MAX_ADD_PEAK)
    if amount<=1e-7:return None,dict(record,status='KEEP_NEGLIGIBLE_PHYSICAL_DEFICIT')
    y=x+np.repeat((amount*u)[:,None],2,axis=1)
    if np.max(np.abs(y))>cfg.max_input_peak:return None,dict(record,status='ABSTAIN_PHYSICAL_PEAK')
    # Compact source-clock envelope; renderer never needs stem waveforms.
    frames=np.linspace(a0,b0,min(301,max(3,round((b0-a0)/sr0/.01)+1))).round().astype(int)
    frames=np.unique(frames)
    et=(frames-a0)/sr0
    values=np.interp(et,t,env,left=0,right=0);values[0]=0;values[-1]=0
    if not np.any(values>0):return None,dict(record,status='ABSTAIN_EMPTY_COMPACT_ENVELOPE')
    evidence=dict(record,status='PHYSICALLY_CONFIRMED_SAME_FUNDAMENTAL',physical_start_frame=a,physical_stop_frame=b,
        source_start_frame=a0,source_stop_frame=b0,physical_fundamental=float(amps[0]),physical_upper_max=upper,
        target_amplitude=target_amp,addition_amplitude=float(amount),added_rms_fraction=float(np.sqrt(np.mean((amount*u)**2))/max(rms,1e-24)),
        quantity_calibration='ENGINEERING_BUDGET_NOT_PERSONAL_TASTE')
    h=digest(evidence)
    proposal=SameFundamentalAdd('same_f0_'+h[:24],target,tuple(int(v) for v in frames),tuple(float(v) for v in values),float(amount),float(phase),h,snapshot.physical.file_sha256)
    proposal.validate(snapshot);snapshot.verify(context.source_path,context.physical_path)
    return proposal,evidence
