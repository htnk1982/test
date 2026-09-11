"""P02 engineering comparison: deployable Spleeter vs research HDEMUCS.

Uses generated fixtures only. Scores are role/task diagnostics, not SDR and not
private-music accuracy. HDEMUCS remains research-only and is never packaged.
"""
from pathlib import Path
import hashlib,json,math,os,tarfile,tempfile,urllib.request,platform,sys,time
import numpy as np
import soundfile as sf
from scipy import signal

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from stem_observer_lab import Observer,CHECKPOINT_SHA256
from role_observer_v37 import observe_dual as observe_hdem
from observer_worker_spleeter_v47 import _features

OUT=ROOT/'P02_ROLE_COMPARISON_EVIDENCE'
BASE='https://github.com/deezer/spleeter/releases/download/v1.4.0'


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
    # constant weak high-frequency bed prevents completely degenerate silence.
    add(.004*np.sin(2*np.pi*1700*t),.75)
    if kind=='bass_event':
        g=smooth_gate(t,2.25,5.35);add(g*(.10*np.sin(2*np.pi*55*t)+.045*np.sin(2*np.pi*110*t)),1.)
    elif kind=='kick_only':
        phase=(t-.1)%0.5;env=np.exp(-36*phase);add(.18*np.sin(2*np.pi*58*t)*env,1.)
    elif kind=='vocal_low':
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
    return arrays,dict(source_order=['mix','drums','bass','other','vocals'],reconstruction_error_db=re)


def role_shares(a,key,mask):
    # Ignore mix column; compare estimated roles only.
    p=np.median(a[key][:,mask,1:],axis=(0,1));return p/max(float(p.sum()),1e-24)


def metrics(kind,a):
    t=a['time'];event=(t>=2.4)&(t<5.2);gap=(t>=3.55)&(t<4.45);edge=((t>=2.0)&(t<2.2))|((t>=5.55)&(t<6.0))
    low=role_shares(a,'low_power',event);body=role_shares(a,'body_power',event);focus=role_shares(a,'focus_power',event)
    names=('drums','bass','other','vocals');share=lambda v:{n:float(x) for n,x in zip(names,v)}
    out=dict(low_share=share(low),body_share=share(body),focus_share=share(focus))
    if kind=='bass_event':
        out['pass']=bool(low[1]>.35 and low[1]>max(low[0],low[2],low[3]));out['criterion']='bass low share > .35 and dominant'
    elif kind=='kick_only':
        out['pass']=bool(low[0]>low[1]);out['criterion']='drums low share > bass low share'
    elif kind=='vocal_low':
        out['pass']=bool((body[3]+focus[3])>(body[1]+focus[1]));out['criterion']='vocal body+focus share > bass'
    elif kind=='rest_gap':
        bass=a['low_power'][:,:,2];ev=(t>=2.35)&(t<3.1);gp=gap
        db=float(10*np.log10(max(float(np.median(bass[:,ev])),1e-24)/max(float(np.median(bass[:,gp])),1e-24)));out['bass_event_to_gap_db']=db;out['pass']=bool(db>=10);out['criterion']='bass event/gap >= 10 dB'
    # context disagreement on bass low curve, diagnostic only.
    b=a['low_power'][:,:,2];out['bass_context_log_disagreement_db']=float(np.median(abs(10*np.log10(np.maximum(b[0],1e-24)/np.maximum(b[1],1e-24)))))
    return out


def main():
    OUT.mkdir(exist_ok=True)
    checkpoint=Path(os.environ.get('PDRM_HDEMUCS_CHECKPOINT',''))
    if not checkpoint.is_file() or sha(checkpoint)!=CHECKPOINT_SHA256:raise RuntimeError('Validated HDEMUCS research checkpoint required')
    with tempfile.TemporaryDirectory(prefix='pdrm_observer_compare_') as td:
        td=Path(td);idx=td/'checksum.json';arc=td/'4stems.tar.gz';download(BASE+'/checksum.json',idx);download(BASE+'/4stems.tar.gz',arc)
        expected=json.loads(idx.read_text(encoding='utf-8'))['4stems'];actual=sha(arc)
        if actual!=expected:raise RuntimeError('Spleeter checksum mismatch')
        root=td/'models';model=root/'4stems';model.mkdir(parents=True);safe_tar(arc,model);(model/'.probe').write_text('OK',encoding='utf-8');os.environ['MODEL_PATH']=str(root)
        from spleeter.separator import Separator
        sep=Separator('spleeter:4stems',multiprocess=False);hdem=Observer(checkpoint,threads=2)
        records={};kinds=('bass_event','kick_only','vocal_low','rest_gap')
        for kind in kinds:
            p=td/(kind+'.wav');sf.write(p,fixture(kind),44100,subtype='FLOAT')
            s,_=observe_spleeter(sep,p);h,_=observe_hdem(hdem,p,2.,6.,pads=(1.,2.))
            records[kind]=dict(spleeter=metrics(kind,s),hdemucs=metrics(kind,h))
        scores={m:sum(int(records[k][m]['pass']) for k in kinds) for m in ('spleeter','hdemucs')}
        critical=('kick_only','vocal_low','rest_gap');spleeter_critical=all(records[k]['spleeter']['pass'] for k in critical)
        # Deployment candidacy requires no critical false-role regression on this
        # engineering suite; superiority to research HDEMUCS is not required.
        decision='DEPLOYMENT_CANDIDATE_FOR_PRIVATE_AUDIO_CALIBRATION' if spleeter_critical else 'REJECT_OR_REDESIGN_OBSERVER_BEFORE_PRIVATE_AUDIO'
        result=dict(success=True,platform=platform.platform(),python=sys.version,spleeter_asset_sha256=actual,hdemucs_checkpoint_sha256=CHECKPOINT_SHA256,
            records=records,scores=scores,critical_tasks=list(critical),decision=decision,private_audio_used=False,subjective_quality='NOT_EVALUATED',
            warning='Generated role fixtures are engineering counterexamples, not source-separation accuracy certification or user-taste evidence.')
        (OUT/'SUMMARY.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
        print('P02_ROLE_COMPARISON '+json.dumps(result,ensure_ascii=True),flush=True)
        if not spleeter_critical:raise SystemExit(2)

if __name__=='__main__':main()
