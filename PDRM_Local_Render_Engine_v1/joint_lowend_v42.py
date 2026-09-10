"""Joint LAB: retain broad FIR audio; add only unmet narrow attenuation.

Every difference is derived from ONE physical snapshot. Framewise transfer
bounds do not prove bounds on the final waveform's STFT. Each narrow operation
has its own time gate. No oscillator, separated audio or production default.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
from pathlib import Path
import json,math,os
import numpy as np
import soundfile as sf
from scipy import signal
import lowend_coordinator_v40 as broad
import lowend_boundary_lab as legacy_renderer
from integration_contract_v40 import capture,digest,integer,valid_hash

VERSION='joint-lowend-lab-0.1.0'
MAX_NARROW_DB=1.5
MAX_COMBINED_DB=2.0
MAX_PROPOSALS=4096
MAX_ACTIVE=16

@dataclass(frozen=True)
class NarrowCut:
    proposal_id:str
    center_hz:float
    source_frames:tuple[int,...]
    depth_db:tuple[float,...]
    reason:str
    evidence_sha256:str
    physical_confirmation_sha256:str

    def validate(self,snapshot):
        if not isinstance(self.proposal_id,str) or not self.proposal_id or not isinstance(self.reason,str) or not self.reason:
            raise ValueError('Named, reasoned operation required')
        if isinstance(self.center_hz,bool) or not isinstance(self.center_hz,(int,float)) or not math.isfinite(self.center_hz) or not 120<=self.center_hz<=600:
            raise ValueError('Narrow repair limited to 120-600 Hz')
        if not valid_hash(self.evidence_sha256) or self.physical_confirmation_sha256!=snapshot.physical.file_sha256:
            raise ValueError('Source evidence and exact physical confirmation required')
        if not 2<=len(self.source_frames)==len(self.depth_db)<=200001:raise ValueError('Invalid control geometry')
        for v in self.source_frames:integer(v,'source control frame')
        if any(b<=a for a,b in zip(self.source_frames,self.source_frames[1:])) or self.source_frames[-1]>snapshot.source.frames:
            raise ValueError('Invalid source timeline')
        if any(isinstance(d,bool) or not isinstance(d,(int,float)) or not math.isfinite(d) or not 0<=d<=MAX_NARROW_DB for d in self.depth_db):
            raise ValueError('Invalid narrow depth')
        if self.depth_db[0]!=0 or self.depth_db[-1]!=0:raise ValueError('Explicit boundary zeros required')
        if not any(self.depth_db):raise ValueError('Zero edit is not a proposal')
        mapped=[snapshot.clock.nearest(v) for v in self.source_frames]
        if mapped[0]<0 or mapped[-1]>snapshot.physical.frames or any(b<=a for a,b in zip(mapped,mapped[1:])):
            raise ValueError('Mapped controls collapse or leave audio')
        return self


def compile_plan(snapshot,broad_plan,narrow_cuts,*,planner_id,calibration_sha256,evidence_scope,assessment,unresolved=()):
    snapshot.validate();broad.validate_plan(broad_plan,snapshot)
    if not isinstance(planner_id,str) or not planner_id or not valid_hash(calibration_sha256):raise ValueError('Planner/calibration required')
    if evidence_scope not in ('engineering_fixture','research_observer') or assessment not in ('CANDIDATE','PARTIAL','KEEP_SUPPORTED','ABSTAIN'):
        raise ValueError('Explicit scope/assessment required')
    if broad_plan['evidence_scope']!=evidence_scope:raise ValueError('Mixed evidence scopes')
    cuts=sorted(tuple(narrow_cuts),key=lambda p:p.proposal_id)
    if len(cuts)>MAX_PROPOSALS or len({p.proposal_id for p in cuts})!=len(cuts):raise ValueError('Duplicate/excessive proposals')
    for cut in cuts:cut.validate(snapshot)
    if not isinstance(unresolved,(list,tuple)) or any(not isinstance(v,str) or not v for v in unresolved):raise ValueError('Explicit unresolved reasons required')
    edges=[]
    for c in cuts:edges.extend([(c.source_frames[0],1),(c.source_frames[-1],-1)])
    active=0
    for _,step in sorted(edges):
        active+=step
        if active>MAX_ACTIVE:raise ValueError('Too many simultaneous narrow operations')
    changed=bool(cuts) or bool(np.any(broad_plan['low_cut_db']) or np.any(broad_plan['lowmid_cut_db']))
    if changed!=(assessment in ('CANDIDATE','PARTIAL')):raise ValueError('Assessment disagrees with edits')
    if not changed and (broad_plan['assessment']=='ABSTAIN' or unresolved) and assessment!='ABSTAIN':raise ValueError('Uncertainty cannot become KEEP')
    if changed and (broad_plan['assessment'] in ('ABSTAIN','PARTIAL') or unresolved) and assessment!='PARTIAL':raise ValueError('Unresolved components require PARTIAL')
    result=dict(schema=1,version=VERSION,snapshot_sha256=snapshot.token,source_sha256=snapshot.source.file_sha256,
        physical_sha256=snapshot.physical.file_sha256,planner_id=planner_id,calibration_sha256=calibration_sha256,
        evidence_scope=evidence_scope,assessment=assessment,broad_plan=broad_plan,narrow_cuts=[asdict(c) for c in cuts],
        unresolved=list(unresolved),combined_mask_ceiling_db=MAX_COMBINED_DB,
        budget_rule='MAX_REQUEST_NOT_ADDITIVE;_ONLY_UNMET_NARROW_RESPONSE',sub_synthesis='NOT_CONNECTED',subjective_quality='NOT_EVALUATED')
    result=json.loads(json.dumps(result,ensure_ascii=False,allow_nan=False));result['sha256']=digest(result)
    return result


def validate_plan(plan,snapshot):
    p=dict(plan);h=p.pop('sha256',None)
    if h!=digest(p) or plan.get('version')!=VERSION or plan.get('schema')!=1:raise ValueError('Joint seal/version mismatch')
    cuts=[]
    for item in plan['narrow_cuts']:
        row=dict(item);row['source_frames']=tuple(row['source_frames']);row['depth_db']=tuple(row['depth_db']);cuts.append(NarrowCut(**row))
    rebuilt=compile_plan(snapshot,plan['broad_plan'],cuts,planner_id=plan['planner_id'],calibration_sha256=plan['calibration_sha256'],
        evidence_scope=plan['evidence_scope'],assessment=plan['assessment'],unresolved=plan['unresolved'])
    if rebuilt!=plan:raise ValueError('Controls disagree with declared operations')
    return plan


def geometry(sr):
    n=round(4096*sr/12000);n+=n%2;hop=round(.02*sr);win=signal.windows.hann(n,sym=False)
    if not signal.check_NOLA(win,n,n-hop):raise RuntimeError('Invalid overlap-add normalization')
    cfg=legacy_renderer.Config();taps=max(1025,round(cfg.filter_seconds*sr)|1)
    a=signal.firwin(taps,140,fs=sr,window=('kaiser',10.5));b=signal.firwin(taps,350,fs=sr,window=('kaiser',10.5))
    f=np.fft.rfftfreq(n,1/sr);phase=np.exp(2j*np.pi*f*(taps-1)/2/sr)
    return n,hop,win,f,(np.fft.rfft(a,n)*phase).real,(np.fft.rfft(b,n)*phase).real


def frame_response(low_db,mid_db,depths,shapes,A,B):
    """Shared requested transfer, not a guarantee about reanalysed audio."""
    h=1+(10**(-low_db/20)-1)*A+(10**(-mid_db/20)-1)*(B-A)
    if not len(depths):return h,np.zeros((0,len(h))),dict(max_joint_db=0.,redundant_bins=0)
    wants=np.asarray(depths)[:,None]*shapes;total=wants.max(axis=0)
    goal=np.where(total>0,np.minimum(h,np.maximum(10**(-total/20),10**(-MAX_COMBINED_DB/20))),h)
    extra=np.minimum(goal-h,0.)
    split=wants/np.maximum(wants.sum(axis=0,keepdims=True),1e-30)*extra[None,:]
    return h,split,dict(max_joint_db=float(-20*np.log10(max(float(goal.min()),1e-15))),
        redundant_bins=int(np.count_nonzero((total>0)&(np.abs(extra)<1e-12))))


def _smoothstep(v):
    v=np.clip(v,0,1);return v*v*(3-2*v)


def _render_block(x,a,start,stop,snapshot,plan,geo):
    sr=snapshot.physical.samplerate;n_total=snapshot.physical.frames
    n,hop,win,f,A,B=geo;half=n//2
    bp=plan['broad_plan'];bt=np.asarray(bp['physical_frames'],float)
    local=dict(time=(bt-a)/sr,low_cut_db=bp['low_cut_db'],lowmid_cut_db=bp['lowmid_cut_db'])
    base=legacy_renderer.render_array(x,sr,local)[start-a:stop-a]
    active=[]
    for item in plan['narrow_cuts']:
        knots=np.array([snapshot.clock.nearest(v) for v in item['source_frames']],dtype=np.int64)
        # Include neighbouring operations that share an STFT frame, even if their
        # sample gate is outside this block. Otherwise block size changes shares.
        if knots[-1]>start-half-hop and knots[0]<stop+half+hop:
            active.append((item,knots,np.asarray(item['depth_db'],float)))
    if len(active)>MAX_ACTIVE:raise RuntimeError('Dense narrow context exceeds bounded renderer capacity')
    if not active:return base,dict(max_joint_db=0.,redundant_bins=0,fft_frames=0,peak_active=0)
    length=stop-start;acc=np.zeros((len(active),length,2));den=np.zeros(length)
    shapes=np.stack([np.maximum(1-np.abs(np.log2(np.maximum(f,1)/row[0]['center_hz']))/(1/6),0) for row in active])
    stats=dict(max_joint_db=0.,redundant_bins=0,fft_frames=0,peak_active=len(active))
    first=math.floor((start-half)/hop)*hop;last=math.ceil((stop+half)/hop)*hop
    for center in range(first,last+1,hop):
        left=center-half;right=left+n;lo=max(left,start);hi=min(right,stop)
        if lo>=hi:continue
        wsl=slice(lo-left,hi-left);outsl=slice(lo-start,hi-start);den[outsl]+=win[wsl]**2
        depths=[float(np.interp(center,k,d,left=0,right=0)) for _,k,d in active]
        if not any(depths):continue
        dl=float(np.interp(center,bt,bp['low_cut_db'],left=0,right=0));dm=float(np.interp(center,bt,bp['lowmid_cut_db'],left=0,right=0))
        _,split,q=frame_response(dl,dm,depths,shapes,A,B)
        stats['max_joint_db']=max(stats['max_joint_db'],q['max_joint_db']);stats['redundant_bins']+=q['redundant_bins']
        if not np.any(split):continue
        audio=np.zeros((n,2));rl=max(0,left);rh=min(n_total,right)
        if rl<a or rh>a+len(x):raise RuntimeError('Insufficient render halo')
        audio[rl-left:rh-left]=x[rl-a:rh-a]
        z=np.fft.rfft(audio*win[:,None],axis=0);stats['fft_frames']+=1
        for j in np.flatnonzero(np.any(split,axis=1)):
            diff=np.fft.irfft(z*split[j,:,None],n=n,axis=0)*win[:,None]
            acc[j,outsl]+=diff[wsl]
    if np.any(den<1e-12):raise RuntimeError('Incomplete overlap-add support')
    positions=np.arange(start,stop);delta=np.zeros_like(base)
    for j,(item,knots,depth) in enumerate(active):
        strength=np.interp(positions,knots,depth,left=0,right=0)/max(float(depth.max()),1e-30)
        fade=.12*sr
        gate=_smoothstep((positions-knots[0])/fade)*_smoothstep((knots[-1]-positions)/fade)*_smoothstep(strength)
        delta+=acc[j]/den[:,None]*gate[:,None]
    dry=x[start-a:stop-a];delta[np.all(dry==0,axis=1)]=0;result=base+delta
    if not np.isfinite(result).all():raise RuntimeError('Nonfinite joint render')
    return result,stats


def render(source,physical,destination,snapshot,plan,*,progress=None,chunk_frames=None):
    source,physical,destination=map(Path,(source,physical,destination))
    snapshot.verify(source,physical);validate_plan(plan,snapshot)
    if not plan['narrow_cuts']:
        r=broad.render(source,physical,destination,snapshot,plan['broad_plan'],progress=progress,chunk_frames=chunk_frames)
        return dict(r,version=VERSION,plan_sha256=plan['sha256'],assessment=plan['assessment'],narrow_operations=0,broad_delegate_exact=True)
    if destination.exists() or destination.is_symlink():raise FileExistsError('Existing destination preserved')
    if destination.resolve() in (source.resolve(),physical.resolve()):raise ValueError('Immutable input')
    sr=snapshot.physical.samplerate;length=snapshot.physical.frames
    requested=chunk_frames if chunk_frames is not None else 2*sr;integer(requested,'chunk frames',sr//2)
    if requested>16*sr:raise ValueError('Unbounded render chunk')
    # Bound per-operation overlap-add arrays independently of track duration.
    width=min(requested,2*sr)
    destination.parent.mkdir(parents=True,exist_ok=True);tmp=destination.with_name(destination.name+'.partial.wav')
    if tmp.exists() or tmp.is_symlink():raise FileExistsError('Foreign partial preserved')
    geo=geometry(sr);pad=max(sr//2,geo[0]+2*geo[1]);stats=dict(max_joint_db=0.,redundant_bins=0,fft_frames=0,peak_active=0,max_audio_read_frames=0,render_block_frames=width)
    try:
        with sf.SoundFile(physical) as src,sf.SoundFile(tmp,'w',samplerate=sr,channels=2,format='WAV',subtype='DOUBLE') as dst:
            for start in range(0,length,width):
                stop=min(length,start+width);a=max(0,start-pad);b=min(length,stop+pad)
                src.seek(a);x=src.read(b-a,dtype='float64',always_2d=True)
                if len(x)!=b-a or not np.isfinite(x).all():raise ValueError('Invalid physical read')
                y,q=_render_block(x,a,start,stop,snapshot,plan,geo);dst.write(y)
                stats['max_audio_read_frames']=max(stats['max_audio_read_frames'],len(x))
                for name in ('max_joint_db','peak_active'):stats[name]=max(stats[name],q[name])
                for name in ('fft_frames','redundant_bins'):stats[name]+=q[name]
                if progress:progress.set('JOINT_LOWEND_RENDER',stop,length)
        snapshot.verify(source,physical);out=capture(tmp)
        if (out.samplerate,out.frames,out.channels)!=(sr,length,2):raise RuntimeError('Changed output shape')
        if destination.exists():raise FileExistsError('Destination appeared')
        os.rename(tmp,destination)
        return dict(version=VERSION,plan_sha256=plan['sha256'],snapshot_sha256=snapshot.token,
            assessment=plan['assessment'],control_requested=True,waveform_changed=out.pcm_sha256!=snapshot.physical.pcm_sha256,
            output_identity=asdict(out),old_note_sub_called=False,sub_synthesis='NOT_CONNECTED',narrow_operations=len(plan['narrow_cuts']),
            broad_delegate_exact=False,stats=stats,budget_scope='FRAME_RESPONSE;_WAVEFORM_QC_REQUIRED',subjective_quality='NOT_EVALUATED')
    except BaseException:
        if tmp.is_file() and not tmp.is_symlink():tmp.unlink()
        raise
