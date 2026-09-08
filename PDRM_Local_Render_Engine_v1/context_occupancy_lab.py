"""Finite-context occupancy correction experiment, not a universal bass target.

Fits a permissive outer envelope from explicitly accepted reference bass. Uses
whole-song level normalization, local 12 s windows and exact source time spans.
No filename/category enters inference. Long sustain alone is never a defect.
"""
import math
import numpy as np
from scipy.ndimage import maximum_filter1d
import lowend_boundary_lab as base
VERSION='context-occupancy-lab-0.1.0'

def windows(f,cfg=base.Config()):
 width=round(cfg.phrase_seconds/cfg.grid_seconds);hop=round(4/cfg.grid_seconds);n=len(f['time'])
 starts=list(range(0,max(1,n-width+1),hop))
 if n>width and (not starts or starts[-1]!=n-width):starts.append(n-width)
 result=[]
 for a in starts:
  b=min(n,a+width);valid=f['present'][a:b];low=f['low_db'][a:b][valid]
  if len(low)<.6*(b-a) or len(low)<100:continue
  q20,q90=np.percentile(low,[20,90])
  result.append(dict(start_index=a,end_index=b,start_seconds=float(f['time'][a]),end_seconds=float(f['time'][b-1]+cfg.grid_seconds),
                     floor_db=float(q20),peak_db=float(q90),contrast_db=float(q90-q20)))
 return result

def calibrate(features,ids,cfg=base.Config()):
 base.calibrate(features,ids,cfg)
 signatures=[]
 for f in features:
  w=windows(f,cfg)
  if not w:raise ValueError('Insufficient reference contexts')
  signatures.append(max(x['floor_db'] for x in w))
 return dict(version=VERSION,config=base.asdict(cfg),floor_cap_db=max(signatures)+cfg.reference_margin_db,
             reference_ids=list(ids),per_track_max_floors=signatures,scope='Exploratory reference occupancy bound; not calibrated preference probability')

def plan(f,atlas,cfg=base.Config()):
 if atlas['version']!=VERSION or atlas['config']!=base.asdict(cfg) or f['configuration']!=base.asdict(cfg):raise ValueError('Calibration mismatch')
 cap=float(atlas['floor_cap_db'])
 if not math.isfinite(cap):raise ValueError('Non-finite cap')
 n=len(f['time']);depth=np.zeros(n);selected=[]
 low=f['low_db'];mid=f['mid_db']
 # A rise supported in both low and mid energy is a conservative attack proxy.
 # It is not a bass-note detector, and never authorizes synthesis.
 lag=4;lr=low-np.r_[np.repeat(low[0],lag),low[:-lag]];mr=mid-np.r_[np.repeat(mid[0],lag),mid[:-lag]]
 protect=maximum_filter1d(((lr>5)&(mr>1)).astype(float),size=13,mode='nearest')>0
 for w in windows(f,cfg):
  excess=w['floor_db']-cap
  if excess<cfg.minimum_excess_db:continue
  a,b=w['start_index'],w['end_index'];local=np.minimum(excess,cfg.max_tail_cut_db)*np.clip((low[a:b]-(cap-6))/6,0,1)
  edge=min((b-a)//2,round(.5/cfg.grid_seconds));r=np.linspace(0,1,edge)
  local[:edge]*=r;local[-edge:]*=r[::-1]
  depth[a:b]=np.maximum(depth[a:b],local);selected.append(dict(w,excess_db=excess))
 depth[protect|~f['present']]=0
 depth=base._smooth_bounded(depth,cfg.grid_seconds,cfg.join_seconds)
 guard=min(n//2,round(.1/cfg.grid_seconds));depth[:guard]*=np.linspace(0,1,guard);depth[-guard:]*=np.linspace(1,0,guard)
 return dict(time=f['time'],low_cut_db=depth,lowmid_cut_db=np.zeros(n),status='CONTEXT_CANDIDATE' if selected else 'NO_CONTEXT_EXCESS',
             selected_windows=selected,reference_floor_cap_db=cap,scope='No semantic claim: local low-band occupancy excess only')

def score(f,p):
 cap=p['reference_floor_cap_db'];excess=[]
 for w in p['selected_windows']:
  a,b=w['start_index'],w['end_index'];v=f['low_db'][a:b][f['present'][a:b]]
  if not len(v):raise ValueError('Missing evaluation support')
  excess.append(max(0.,float(np.percentile(v,20))-cap))
 return float(np.mean(excess)) if excess else 0.

def process(x,sr,f,atlas,cfg=base.Config()):
 p=plan(f,atlas,cfg)
 if not p['selected_windows']:return x.copy(),p,dict(status='NO_CONTEXT_EXCESS',strength=0.,trials=[])
 start=score(f,p);best=None;trials=[]
 for s in (.5,1.):
  y=base.render_array(x,sr,p,cfg,strength=s);fy=base.extract(y,sr,cfg);q=base.evaluate_change(x,y,sr);end=score(fy,p)
  valid=q['finite'] and q['source_silence_preserved'] and q['residual_above1k_db']<=-60 and end<start-.1
  trials.append(dict(strength=s,source_excess_db=start,output_excess_db=end,valid=valid,**q))
  if valid and (best is None or end<best[0]):best=(end,y,s)
  if valid and end<=.25:return y,p,dict(status='NUMERICAL_CONTEXT_TARGET_MET',strength=s,trials=trials,subjective_quality='NOT_EVALUATED')
 if best is None:return x.copy(),p,dict(status='ABSTAIN_NO_VALID_IMPROVEMENT',strength=0.,trials=trials)
 return best[1],p,dict(status='PARTIAL_CONTEXT_BUDGET_LIMITED',strength=best[2],trials=trials,subjective_quality='NOT_EVALUATED')
