"""Whole-source proposal extraction, not semantic note transcription.

Short-window energy rises provide onset hypotheses. Longer, event-contained
windows provide pitch evidence. A periodicity estimate never grants synthesis.
No filename, BPM grid or handwritten event time participates in detection.
"""
from __future__ import annotations
from dataclasses import asdict, dataclass
from pathlib import Path
import math
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import uniform_filter1d
from integration_contract_v40 import capture, digest, Span, integer
import lowend_boundary_lab as boundary

VERSION = 'source-events-lab-0.1.0'
FS = 12000
HOP = 120  # 10 ms measurement clock, NOT guaranteed timing accuracy.
EPS = 1e-24

@dataclass(frozen=True)
class Config:
    chunk_seconds: int = 8
    halo_seconds: int = 1
    rise_seconds: float = .04
    minimum_rise_db: float = 3.
    minimum_separation_seconds: float = .09
    activity_below_peak_db: float = 45.
    release_below_peak_db: float = 22.
    maximum_event_seconds: float = 8.
    maximum_events: int = 12000
    def validate(self):
        for k,v in asdict(self).items():
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):
                raise ValueError('Invalid config: '+k)
        if type(self.chunk_seconds) is not int or not 2<=self.chunk_seconds<=16 or self.halo_seconds!=1:
            raise ValueError('Bounded integer second chunks and 1-second context required')
        if not .02<=self.rise_seconds<=.08 or not 1<=self.minimum_rise_db<=9:
            raise ValueError('Invalid onset evidence')
        if not .06<=self.minimum_separation_seconds<=.3 or not 30<=self.activity_below_peak_db<=70:
            raise ValueError('Invalid timing/activity budget')
        if not 12<=self.release_below_peak_db<=40 or not 1<=self.maximum_event_seconds<=8:
            raise ValueError('Invalid event duration/release')
        if type(self.maximum_events) is not int or not 1<=self.maximum_events<=20000:
            raise ValueError('Invalid event count budget')
        return self


def _read_12k(handle, first, last):
    """Align input start to a complete rational SRC phase; return absolute origin."""
    sr=handle.samplerate; g=math.gcd(sr,FS); down=sr//g
    first=(max(0,first)//down)*down; last=min(handle.frames,last)
    handle.seek(first); x=handle.read(last-first,dtype='float64',always_2d=True)
    if len(x)!=last-first or not np.isfinite(x).all():raise ValueError('Invalid/truncated analysis read')
    y=signal.resample_poly(x,FS//g,down,axis=0,window=('kaiser',10.5))
    origin=(first//down)*(FS//g)
    return y,origin


def extract_features(source, *, anchor_gain_db=0., progress=None, cfg=Config()):
    """Full-song compact features; no full-song high-rate audio array or stems.

    The original boundary feature definition is approximated with one-second
    halos around each finite chunk. Partition agreement is a measured tolerance,
    not claimed bitwise equality. Gain is ONE whole-song constant from caller.
    """
    cfg.validate(); ident=capture(source)
    if not math.isfinite(anchor_gain_db):raise ValueError('Finite whole-track anchor required')
    total=(ident.frames*FS+ident.samplerate-1)//ident.samplerate
    positions=np.arange(0,total,HOP,dtype=np.int64)
    results={k:np.empty(len(positions)) for k in
             ('full_db','low_db','lowmid_db','mid_db','deep_db','fast_db','tonal_fast_db')}
    filters={k:signal.butter(4,[lo,hi],btype='bandpass',fs=FS,output='sos')
             for k,lo,hi in [('low_db',20,120),('lowmid_db',120,300),('mid_db',250,2000),
                             ('deep_db',30,65),('activity',25,750)]}
    max_read=0; chunks=0; width=cfg.chunk_seconds*FS
    with sf.SoundFile(source) as f:
        for start in range(0,total,width):
            stop=min(total,start+width); indices=np.flatnonzero((positions>=start)&(positions<stop))
            a=math.floor(max(0,start-FS)*ident.samplerate/FS)
            b=math.ceil(min(total,stop+FS)*ident.samplerate/FS)
            x,origin=_read_12k(f,a,b); max_read=max(max_read,len(x)); chunks+=1
            loc=positions[indices]-origin
            if len(loc) and (loc[0]<0 or loc[-1]>=len(x)):raise RuntimeError('SRC/grid coverage mismatch')
            def db_envelope(z,seconds=.06):
                power=uniform_filter1d(np.mean(z*z,axis=1),round(seconds*FS),mode='nearest')
                return 10*np.log10(np.maximum(power[loc],EPS))+anchor_gain_db
            results['full_db'][indices]=db_envelope(x)
            for key,sos in filters.items():
                y=signal.sosfiltfilt(sos,x,axis=0)
                if key=='activity':
                    results['fast_db'][indices]=db_envelope(y,.02)
                else:results[key][indices]=db_envelope(y)
            tonal=signal.sosfiltfilt(signal.butter(4,[80,750],btype='bandpass',fs=FS,output='sos'),x,axis=0)
            results['tonal_fast_db'][indices]=db_envelope(tonal,.02)
            if progress:progress.set('SOURCE_EVENT_SCAN',min(ident.frames,round(stop*ident.samplerate/FS)),ident.frames)
    ident.verify(source)
    result=dict(results,time=positions/FS,present=results['full_db']>-45,
                low_active=(results['full_db']>-45)&(results['low_db']>-50),
                configuration=asdict(boundary.Config()),source_identity=asdict(ident),
                anchor_gain_db=float(anchor_gain_db),feature_version=VERSION,
                max_analysis_read_frames=max_read,analysis_chunks=chunks)
    return result


def _runs(mask):
    edges=np.diff(np.r_[False,mask,False].astype(int))
    return list(zip(np.flatnonzero(edges==1),np.flatnonzero(edges==-1)))


def discover(features, cfg=Config()):
    """Returns event proposals and unresolved activity, never bass permissions."""
    cfg.validate(); t=np.asarray(features['time']);d=np.asarray(features['fast_db'])
    td=np.asarray(features['tonal_fast_db']);ident=features['source_identity']
    if d.shape!=t.shape or td.shape!=t.shape or len(t)<2 or not all(np.isfinite(v).all() for v in (t,d,td)):
        raise ValueError('Invalid event features')
    if abs(t[0])>1e-12 or not np.allclose(np.diff(t),.01,atol=1e-9):raise ValueError('Expected global 10-ms second clock')
    if d.max()<=-160:return dict(events=[],unresolved=[],digital_silence=True,healthy_audio_claim=False)
    floor=max(float(d.max())-cfg.activity_below_peak_db,-150.)
    active=d>floor; lag=round(cfg.rise_seconds/.01)
    novelty=np.maximum(d-np.r_[np.repeat(d[0],lag),d[:-lag]],
                       td-np.r_[np.repeat(td[0],lag),td[:-lag]])
    peaks,_=signal.find_peaks(novelty,height=cfg.minimum_rise_db,prominence=1.,
                             distance=max(1,round(cfg.minimum_separation_seconds/.01)))
    onsets=[]
    for p in peaks:
        if not active[p]:continue
        # Locate the rise shoulder, not the novelty peak or a beat grid point.
        lo=max(0,p-round(.08/.01)); before=d[lo:p+1]
        base=float(np.min(before)); top=float(np.max(d[p:min(len(d),p+5)]))
        crossings=np.flatnonzero(before>=base+.2*max(0.,top-base))
        idx=lo+int(crossings[0]) if len(crossings) else int(p)
        if onsets and idx-onsets[-1]<round(cfg.minimum_separation_seconds/.01):continue
        onsets.append(idx)
    # Activity that starts at a file boundary does not have witnessed pre-onset.
    for a,b in _runs(active):
        if not any(a-2<=i<min(b,a+12) for i in onsets):onsets.append(a)
    onsets=sorted(set(onsets))
    if len(onsets)>cfg.maximum_events:raise RuntimeError('Event capacity exceeded; no silent truncation')
    events=[]; unresolved=[];sr=ident['samplerate'];n=ident['frames']
    for k,a in enumerate(onsets):
        next_onset=onsets[k+1] if k+1<len(onsets) else len(t)
        cap=min(next_onset,a+round(cfg.maximum_event_seconds/.01))
        if cap-a<3:continue
        head_peak=float(np.max(d[a:min(cap,a+15)]))
        released=d[a:cap]<max(floor,head_peak-cfg.release_below_peak_db)
        release_runs=[(u,v) for u,v in _runs(released) if v-u>=4 and u>=4]
        b=a+release_runs[0][0] if release_runs else cap
        if b<=a:continue
        start=max(0,min(n-1,round(t[a]*sr)));end=min(n,round(b*.01*sr))
        if end<=start:continue
        open_left=a==0;open_right=not release_runs and cap==len(t)
        item=dict(event_id=digest(dict(source=ident['file_sha256'],start=start,stop=end))[:24],
            start_frame=start,stop_frame=end,start_seconds=start/sr,end_seconds=end/sr,
            onset_supported=not open_left,release_observed=bool(release_runs),
            left_censored=open_left,right_censored=open_right,
            classification='ACTIVITY_CANDIDATE',role='UNASSIGNED',synthesis_authorized=False,
            pitch_hz=None,periodicity=None,source_sha256=ident['file_sha256'])
        events.append(item)
        if not release_runs and cap<next_onset:
            unresolved.append(dict(start_frame=end,stop_frame=min(n,round(next_onset*.01*sr)),reason='LONG_ACTIVITY_NOT_FULLY_SEGMENTED'))
    return dict(events=events,unresolved=unresolved,digital_silence=False,
                healthy_audio_claim=False,scope='Energy-rise event proposals, not complete transcription')


def pitch_evidence(source, event):
    """Longer window contained in the proposed event. No octave-down mapping."""
    sr=sf.info(source).samplerate;a=event['start_frame'];b=event['stop_frame']
    if (b-a)/sr<.14:return dict(event,pitch_status='ABSTAIN_SHORT_EVENT')
    length=min(b-a,round(.256*sr)); first=a+(b-a-length)//2
    with sf.SoundFile(source) as f:x,_=_read_12k(f,first,first+length)
    x=x[:round(length*FS/sr)];power=np.mean(x*x,axis=0);mono=x[:,int(np.argmax(power))]
    # Selecting a non-cancelling channel does not establish centred bass role.
    z=signal.sosfiltfilt(signal.butter(4,[25,750],btype='bandpass',fs=FS,output='sos'),mono)
    z-=z.mean();n=len(z)
    if np.mean(z*z)<1e-16:return dict(event,pitch_status='ABSTAIN_LOW_ENERGY')
    ac=signal.correlate(z,z,mode='full',method='fft')[n-1:];cs=np.r_[0,np.cumsum(z*z)]
    lag=np.arange(n);nsdf=2*ac/np.maximum(cs[n-lag]+cs[n]-cs[lag],EPS)
    lo=math.ceil(FS/180);hi=min(n-2,math.floor(FS/30));peaks,_=signal.find_peaks(nsdf[lo:hi+1]);peaks+=lo
    if not len(peaks):return dict(event,pitch_status='ABSTAIN_NO_PERIOD')
    best=float(nsdf[peaks].max());good=peaks[nsdf[peaks]>=max(.85,best*.96)]
    if not len(good):return dict(event,pitch_status='ABSTAIN_WEAK_PERIOD',periodicity=best)
    p=int(good[0]);aa,bb,cc=nsdf[p-1:p+2];den=aa-2*bb+cc
    shift=float(np.clip(.5*(aa-cc)/den,-.5,.5)) if abs(den)>EPS else 0.
    f0=FS/(p+shift);tt=np.arange(n)/FS;window=signal.windows.hann(n)
    amps=[abs(2*np.sum(window*z*np.exp(-2j*np.pi*f0*h*tt))/window.sum()) for h in range(1,7) if f0*h<750]
    support=sum(v>=max(amps)*.12 for v in amps)
    return dict(event,pitch_status='PERIODIC_CANDIDATE' if support>=2 else 'ABSTAIN_ROLE_AMBIGUOUS_SINE',
                pitch_hz=float(f0),periodicity=float(bb),harmonic_count=int(support),
                classification='TONAL_CANDIDATE' if support>=2 else 'UNRESOLVED_PERIODIC',
                pitch_window_seconds=n/FS,synthesis_authorized=False)


def analyze_source(source,progress=None,cfg=Config()):
    f=extract_features(source,progress=progress,cfg=cfg);catalog=discover(f,cfg)
    out=[]
    for i,e in enumerate(catalog['events']):
        out.append(pitch_evidence(source,e))
        if progress:progress.set('SOURCE_EVENT_PITCH',i+1,len(catalog['events']))
    capture(source).verify(source)
    if capture(source).file_sha256!=f['source_identity']['file_sha256']:raise RuntimeError('Source changed during event analysis')
    catalog.update(events=out,source_identity=f['source_identity'],version=VERSION,
                   control_parameters=asdict(cfg),new_octaves_allowed=False)
    return f,catalog


def ranges_from_depth(time,depth,rate,length):
    time=np.asarray(time);depth=np.asarray(depth)
    if time.shape!=depth.shape or not np.isfinite(depth).all() or (depth<0).any():raise ValueError('Invalid cut timeline')
    return [Span(max(0,math.floor(time[a]*rate)),min(length,math.ceil((time[b-1]+.01)*rate)))
            for a,b in _runs(depth>1e-6)]


def schedule(spans, *, rate, length):
    """8-second overlapping cores. Both contexts observe the same source clock.

    400-ms core edges remain uncertain. Overlap covers internal seams; actual
    file edges cannot be supplied by zero padding and are reported separately.
    """
    integer(rate,'rate',1);integer(length,'length',1)
    merged=[]
    for s in sorted(spans,key=lambda s:(s.start,s.stop)):
        s.validate(length)
        if merged and s.start<=merged[-1].stop:merged[-1]=Span(merged[-1].start,max(s.stop,merged[-1].stop))
        else:merged.append(s)
    result=[];seen=set();grid=max(1,rate//50);guard=math.ceil(.4*rate);width=8*rate
    for s in merged:
        cursor=s.start
        while cursor<s.stop:
            a=max(0,((cursor-guard)//grid)*grid);b=min(length,a+width)
            if b-a<rate//2:a=max(0,b-rate//2)
            key=(a,b)
            if key not in seen:
                seen.add(key);result.append(dict(core_start_frame=a,core_stop_frame=b,
                    read_start_frame=max(0,a-2*rate),read_stop_frame=min(length,b+2*rate),
                    trusted_start_frame=a+guard,trusted_stop_frame=max(a+guard,b-guard)))
            nxt=b-guard
            if nxt<=cursor or b==length:break
            cursor=nxt
    return dict(windows=result,requested=[asdict(s) for s in merged],
                observed=False,source_rate=rate,source_frames=length,
                unresolved_file_edges=True if merged else False)
