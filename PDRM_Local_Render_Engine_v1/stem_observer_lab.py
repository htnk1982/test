"""Research-only, local Hybrid Demucs observer; estimates never become output audio.

The checkpoint is NOT bundled in the PDRM product. Review its separate upstream
use conditions before deployment. Source energy ratios are NOT probabilities.
"""
from pathlib import Path
import hashlib,math,time
import numpy as np
import soundfile as sf
from scipy import signal
from scipy.ndimage import uniform_filter1d

VERSION='stem-observer-research-0.1.0'
CHECKPOINT_SHA256='85ce4420e0852344b816487b4c4bb821bd406376b93bf684b2b76aa56404c46a'
SOURCES=('drums','bass','other','vocals')

def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(2**20),b''):h.update(b)
 return h.hexdigest()

class Observer:
 def __init__(self,checkpoint,threads=2):
  import torch,torchaudio
  if sha(checkpoint)!=CHECKPOINT_SHA256:raise ValueError('Unrecognized research checkpoint')
  torch.set_num_threads(threads)
  self.model=torchaudio.models.hdemucs_high(sources=list(SOURCES))
  self.model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True))
  self.model.eval();self.torch=torch;self.versions={'torch':torch.__version__,'torchaudio':torchaudio.__version__}
 def observe(self,source,start,end,pad=1.):
  source=Path(source);h=sha(source);info=sf.info(source)
  if not 0<=start<end<=info.duration or end-start>16:raise ValueError('Bounded 0-16 s core required')
  left=max(0,start-pad);right=min(info.duration,end+pad)
  with sf.SoundFile(source) as f:
   f.seek(round(left*info.samplerate));x=f.read(round((right-left)*info.samplerate),dtype='float32',always_2d=True)
  if x.shape[1]!=2 or not np.isfinite(x).all():raise ValueError('Invalid stereo source')
  g=math.gcd(info.samplerate,44100);a=signal.resample_poly(x,44100//g,info.samplerate//g,axis=0).astype('float32')
  offset=float(a.mean());scale=float(a.mean(axis=1).std())
  if scale<1e-6:raise ValueError('Insufficient input signal')
  inp=self.torch.from_numpy(((a-offset)/scale).T.copy())[None]
  t0=time.monotonic()
  with self.torch.inference_mode():out=self.model(inp)[0].cpu().numpy()
  if out.shape!=(4,2,len(a)) or not np.isfinite(out).all():raise RuntimeError('Invalid separator output')
  # Preserve relative stem scales. No per-stem normalizing, clipping or encoding.
  out*=scale
  i=round((start-left)*44100);j=i+round((end-start)*44100)
  stems=out[:,:,i:j];original=a[i:j]
  obs=describe(original,stems,44100,start)
  obs.update(source_sha256=h,source_name=source.name,start=start,end=end,model_sha256=CHECKPOINT_SHA256,
             model='HDEMUCS_HIGH_MUSDB',model_input_seconds=len(a)/44100,
             core_seconds=len(original)/44100,wall_seconds=time.monotonic()-t0,versions=self.versions,
             output_audio_uses_stems=False,confidence_calibrated=False,scope='Research observer; not a production model selection')
  if sha(source)!=h:raise RuntimeError('Source changed')
  return obs

def describe(original,stems,sr,start=0):
 g=math.gcd(sr,12000)
 all_audio=np.concatenate([original.T[None],stems],axis=0)
 y=signal.resample_poly(all_audio,12000//g,sr//g,axis=2)
 sr=12000;hop=120;window=720
 curves={};summary={}
 for band,lo,hi in [('low',20,120),('body',120,300),('harmonics',300,1500)]:
  z=signal.sosfiltfilt(signal.butter(4,[lo,hi],btype='bandpass',fs=sr,output='sos'),y,axis=2)
  p=np.maximum(uniform_filter1d(np.mean(z*z,axis=1),window,axis=1,mode='nearest')[:,::hop],1e-24)
  for k,name in enumerate(('mix',)+SOURCES):curves[name+'_'+band]=p[k]
  ep=np.mean(p,axis=1);shares=ep[1:]/max(float(sum(ep[1:])),1e-24)
  summary[band]={name:float(s) for name,s in zip(SOURCES,shares)}
 spectrum={}
 for k,name in enumerate(('mix',)+SOURCES):
  f,p=signal.welch(y[k].mean(axis=0),sr,nperseg=min(16384,y.shape[-1]));sel=(f>=25)&(f<=350)
  peaks,_=signal.find_peaks(p);ids=[v for v in peaks if sel[v]]
  ids=sorted(ids,key=lambda n:p[n],reverse=True)[:6]
  spectrum[name]=[{'hz':float(f[q]),'relative_db':float(10*np.log10(max(p[q],1e-24)/max(np.max(p[sel]),1e-24)))} for q in ids]
 reconstruct=stems.sum(axis=0).T
 err=float(np.sqrt(np.mean((reconstruct-original)**2))/max(np.sqrt(np.mean(original**2)),1e-12))
 return {'curves':curves,'time':start+np.arange(len(next(iter(curves.values()))))*.01,
         'energy_shares':summary,'spectral_peaks':spectrum,'sum_stems_relative_error_db':20*math.log10(max(err,1e-15)),
         'ratio_warning':'Stem energies are neither additive mixture powers nor source probabilities'}
