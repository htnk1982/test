"""P02 engineering comparison: deployable Spleeter vs research HDEMUCS.

Uses generated counterexamples and the *actual PDRM permission mathematics*.
It does not require a separator to choose the human semantic stem name when the
product only needs a safe actuation decision. HDEMUCS remains research-only.
"""
from pathlib import Path
import hashlib,json,math,os,tarfile,tempfile,urllib.request,platform,sys
import numpy as np
import soundfile as sf
from scipy import signal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stem_observer_lab import Observer,CHECKPOINT_SHA256
from role_observer_v37 import observe_dual as observe_hdem
from observer_worker_spleeter_v47 import _features
import event_groove_v37 as event_gate

OUT=ROOT/'P02_ROLE_COMPARISON_EVIDENCE';BASE='https://github.com/deezer/spleeter/releases/download/v1.4.0'


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(2**20),b''):h.update(b)
    return h.hexdigest()


def download(url,path):
    with urllib.request.urlopen(url,timeout=90) as r,Path(path).open('wb') as f:
        while True:
            b=r.read(2**20)
            if not b:break
            f.write(b)


def safe_tar(archive,dest):
    dest=Path(dest).resolve()
    with tarfile.open(archive,'r:gz') as t:
        ms=t.getmembers()
        for m in ms:
            p=(dest/m.name).resolve()
            if dest not in p.parents and p!=dest:raise RuntimeError('archive escape')
            if m.issym() or m.islnk():raise RuntimeError('archive link')
        t.extractall(dest,members=ms)


def smooth_gate(t,a,b,fade=.06):
    g=((t>=a)&(t<b)).astype(float);e=np.minimum(np.clip((t-a)/fade,0,1),np.clip((b-t)/fade,0,1));return g*e*e*(3-2*e)


def fixture(kind,sr=44100,seconds=8.):
    t=np.arange(round(sr*seconds))/sr;left=np.zeros_like(t);right=np.zeros_like(t)
    def add(x,pan=.9):
        nonlocal left,right;left+=x;right+=pan*x
    add(.004*np.sin(2*np.pi*1700*t),.75) # weak non-degenerate bed
    if kind=='bass_event':
        g=smooth_gate(t,2.25,5.35);add(g*(.10*np.sin(2*np.pi*55*t)+.045*np.sin(2*np.pi*110*t)),1.)
    elif kind=='kick_only':
        phase=(t-.1)%0.5;add(.18*np.sin(2*np.pi*58*t)*np.exp(-36*phase),1.)
    elif kind=='vocal_low':
        # Deliberately ambiguous harmonic low voice proxy. A separator may call
        # it vocals/other; the PDRM safety requirement is specifically NOT BASS.
        g=smooth_gate(t,2.2,5.4);v=g*(.055*np.sin(2*np.pi*165*t)+.040*np.sin(2*np.pi*330*t)+.025*np.sin(2*np.pi*495*t))*(1+.12*np.sin(2*np.pi*4.8*t));add(v,.82)
    elif kind=='rest_gap':
        g=smooth_gate(t,2.15,3.25)+smooth_gate(t,4.75,5.85);add(g*(.095*np.sin(2*np.pi*55*t)+.04*np.sin(2*np.pi*110*t)),1.)
    else:raise ValueError(kind)
    return np.column_stack((left,right)).astype('float32')


def observe_spleeter(separator,source,start=2.,end=6.,pads=(1.,2.)):
    info=sf.info(source);results=[];re=[]
    for pad in pads:
        left=max(0,start-pad);right=min(info.duration,end+pad)
        with sf.SoundFile(source) as f:
            f.seek(round(left*info.samplerate));raw=f.read(round((right-left)*info.samplerate),dtype='float32',always_2d=True)
        g=math.gcd(info.samplerate,44100);x=signal.resample_poly(raw,44100//g,info.samplerate//g,axis=0,window=('kaiser',10.5)).astype('float32')
        stems=separator.separate(x,'pdrm-role-fixture');i=round((start-left)*44100);j=i+round((end-start)*44100);core=x[i:j];s={k:np.asarray(v[i:j],dtype='float32') for k,v in stems.items()}
        results.append(_features(core,s,44100,start));err=np.sqrt(np.mean((sum(s.values())-core)**2))/max(np.sqrt(np.mean(core**2)),1e-12);re.append(float(20*np.log10(max(err,1e-15))))
    arrays={'time':np.asarray(results[0]['time'])}
    for k in ('low_power','body_power','focus_power','upper_focus_power','bass_f0_hz','bass_periodicity'):arrays[k]=np.asarray([r[k] for r in results],dtype=float)
    meta=dict(version='role-observer-0.2.0',source_sha256=sha(source),source_frames=info.frames,source_samplerate=info.samplerate,
        source_order=['mix','drums','bass','other','vocals'],start_seconds=start,end_seconds=end,contexts_seconds=list(pads),
        reconstruction_error_db=re,probabilities_calibrated=False,stem_audio_in_output=False)
    return arrays,meta


def semantic_diagnostics(a):
    t=a['time'];event=(t>=2.4)&(t<5.2);names=('drums','bass','other','vocals');out={}
    for key in ('low_power','body_power','focus_power'):
        p=np.median(a[key][:,event,1:],axis=(0,1));p=p/max(float(p.sum()),1e-24);out[key.replace('_power','_share')]={n:float(v) for n,v in zip(names,p)}
    return out


def reduction_permission(a,start=2.,end=6.):
    """Same gate as automatic_lowend_v41.verify_observation, without provider ID."""
    t=np.asarray(a['time']);p=np.asarray(a['low_power']);shares=p[:,:,1:]/np.maximum(p[:,:,1:].sum(axis=2,keepdims=True),1e-24)
    grouped=shares[:,:,0]+shares[:,:,1];disagreement=np.sum(abs(shares[0]-shares[1]),axis=1)/2;instrument=(p[:,:,1]+p[:,:,2]).min(axis=0)
    ok=(grouped.min(axis=0)>=.75)&(shares[:,:,3].max(axis=0)<=.15)&(disagreement<=.25)
    ok&=(p[:,:,0].min(axis=0)>1e-12)&(instrument>=.05*p[:,:,0].min(axis=0));ok&=(t>=start+.4)&(t<=end-.4)
    return t,ok,dict(supported_fraction=float(ok.mean()),supported_frames=int(ok.sum()),context_disagreement_p95=float(np.percentile(disagreement,95)))


def frac(t,mask,a,b):
    s=(t>=a)&(t<b);return float(mask[s].mean()) if np.any(s) else 0.


def same_f0(a,m,source_digest,start,end,f0,target=None):
    e=dict(start=start,end=end,source_f0_hz=f0,target_hz=f0 if target is None else target)
    d=event_gate.permit(e,a,m,source_digest)
    return dict(allowed=bool(d['allowed']),reason_codes=d['reason_codes'],supported_fraction=float(d.get('local_supported_fraction',0.)),
        bass_share_q20=float(d.get('local_bass_share_q20',0.)),disagreement_p95=float(d.get('local_disagreement_p95',0.)))


def evaluate(kind,a,m,digest_):
    t,permission,gate=reduction_permission(a);diag=semantic_diagnostics(a)
    out=dict(semantic_diagnostic=diag,reduction_gate=gate)
    if kind=='bass_event':
        red=frac(t,permission,2.45,5.15);add=same_f0(a,m,digest_,2.45,5.10,55.)
        passed=red>=.60 and add['allowed'];out.update(reduction_event_fraction=red,same_f0=add,pass_=passed,
            criterion='reduction permission >=.60 inside bass event AND same-f0 permission allowed')
    elif kind=='kick_only':
        red=frac(t,permission,2.4,5.2);add=same_f0(a,m,digest_,2.45,4.95,58.)
        passed=red>=.50 and not add['allowed'];out.update(reduction_event_fraction=red,same_f0=add,pass_=passed,
            criterion='drum low-hit may support reduction, but must NOT authorize bass same-f0 addition')
    elif kind=='vocal_low':
        red=frac(t,permission,2.4,5.2);wrong_pitch=same_f0(a,m,digest_,2.45,5.10,55.);octave=same_f0(a,m,digest_,2.45,5.10,165.,55.)
        passed=red<=.05 and not wrong_pitch['allowed'] and not octave['allowed']
        out.update(reduction_event_fraction=red,counterfactual_55hz_same_f0=wrong_pitch,actual_165_to_55=octave,pass_=passed,
            criterion='vocal-like low content must NOT enter reduction instrument gate or bass-add gate; octave-down rejected')
    elif kind=='rest_gap':
        first=frac(t,permission,2.45,3.10);gap=frac(t,permission,3.55,4.45);second=frac(t,permission,4.90,5.55)
        add1=same_f0(a,m,digest_,2.45,3.10,55.);add2=same_f0(a,m,digest_,4.90,5.55,55.)
        passed=first>=.50 and second>=.50 and gap<=.05 and add1['allowed'] and add2['allowed']
        out.update(reduction_first_fraction=first,reduction_gap_fraction=gap,reduction_second_fraction=second,same_f0_first=add1,same_f0_second=add2,pass_=passed,
            criterion='event support on both sides, <=.05 false permission in rest gap, both local same-f0 events allowed')
    else:raise ValueError(kind)
    out['pass']=bool(out.pop('pass_'));return out


def main():
    OUT.mkdir(exist_ok=True);checkpoint=Path(os.environ.get('PDRM_HDEMUCS_CHECKPOINT',''))
    if not checkpoint.is_file() or sha(checkpoint)!=CHECKPOINT_SHA256:raise RuntimeError('Validated HDEMUCS research checkpoint required')
    with tempfile.TemporaryDirectory(prefix='pdrm_observer_compare_') as td:
        td=Path(td);idx=td/'checksum.json';arc=td/'4stems.tar.gz';download(BASE+'/checksum.json',idx);download(BASE+'/4stems.tar.gz',arc)
        expected=json.loads(idx.read_text(encoding='utf-8'))['4stems'];actual=sha(arc)
        if actual!=expected:raise RuntimeError('Spleeter checksum mismatch')
        root=td/'models';model=root/'4stems';model.mkdir(parents=True);safe_tar(arc,model);(model/'.probe').write_text('OK',encoding='utf-8');os.environ['MODEL_PATH']=str(root)
        from spleeter.separator import Separator
        sep=Separator('spleeter:4stems',multiprocess=False);hdem=Observer(checkpoint,threads=2);records={};kinds=('bass_event','kick_only','vocal_low','rest_gap')
        for kind in kinds:
            p=td/(kind+'.wav');sf.write(p,fixture(kind),44100,subtype='FLOAT');digest_=sha(p)
            s,sm=observe_spleeter(sep,p);h,hm=observe_hdem(hdem,p,2.,6.,pads=(1.,2.))
            records[kind]=dict(spleeter=evaluate(kind,s,sm,digest_),hdemucs=evaluate(kind,h,hm,digest_))
        scores={m:sum(int(records[k][m]['pass']) for k in kinds) for m in ('spleeter','hdemucs')}
        spleeter_pass=all(records[k]['spleeter']['pass'] for k in kinds)
        decision='DEPLOYMENT_CANDIDATE_FOR_PRIVATE_AUDIO_CALIBRATION' if spleeter_pass else 'REJECT_OR_REDESIGN_OBSERVER_BEFORE_PRIVATE_AUDIO'
        result=dict(success=True,platform=platform.platform(),python=sys.version,spleeter_asset_sha256=actual,hdemucs_checkpoint_sha256=CHECKPOINT_SHA256,
            records=records,scores=scores,acceptance_tasks=list(kinds),decision=decision,private_audio_used=False,subjective_quality='NOT_EVALUATED',
            previous_test_error='The prior vocal criterion demanded semantic VOCALS labeling, although PDRM only needs the content excluded from bass/drums actuation. Both models failed that unrelated semantic criterion; this revision evaluates exact PDRM gates instead.',
            warning='Generated counterexamples test actuation safety, not general source-separation accuracy or user taste.')
        (OUT/'SUMMARY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8');print('P02_ROLE_COMPARISON '+json.dumps(result,ensure_ascii=True),flush=True)
        if not spleeter_pass:raise SystemExit(2)

if __name__=='__main__':main()
