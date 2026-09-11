"""Conservative same-fundamental permission for deployable observer ambiguity.

Every repair must prove an already-present *weak* f0 in the original 2mix and
pass a source spectral-brightness veto. Legacy strict bass permission remains
preferred. If Spleeter swaps a sustained low event among drums/bass/other across
contexts, a fallback may act only when the event is non-vocal, not drum-dominant,
and bass-pitch/periodicity evidence remains stable. This is intentionally about
safe low-f0 actuation, not exact semantic stem naming.
"""
from __future__ import annotations
from dataclasses import dataclass,asdict
import math
import numpy as np
import event_groove_v37 as legacy

VERSION='same-f0-permission-lab-0.3.0'

@dataclass(frozen=True)
class Config:
    edge_guard_seconds:float=.10
    max_source_fundamental_ratio:float=.15
    max_source_focus_upper_fraction:float=.05
    max_drum_share:float=.50
    max_vocal_share:float=.15
    max_vocal_context_disagreement:float=.15
    min_periodicity:float=.85
    min_supported_fraction:float=.75
    pitch_tolerance_cents:float=50.
    def validate(self):
        for k,v in asdict(self).items():
            if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('Invalid '+k)
        if not 0<self.edge_guard_seconds<=.20:raise ValueError('Invalid edge guard')
        if not 0<self.max_source_fundamental_ratio<=.25 or not 0<self.max_source_focus_upper_fraction<=.10:raise ValueError('Invalid source-shape limits')
        if not .25<=self.max_drum_share<.75 or not 0<=self.max_vocal_share<=.25 or not 0<=self.max_vocal_context_disagreement<=.25:raise ValueError('Invalid role limits')
        if not .5<=self.min_supported_fraction<=1 or not .5<=self.min_periodicity<=1:raise ValueError('Invalid evidence limits')
        return self


def _source_vetoes(source_proof,source_shape,cfg):
    ratio=float(source_proof.get('fundamental_to_upper_ratio',999.)) if isinstance(source_proof,dict) else 999.
    upper_fraction=float(source_shape.get('focus_upper_fraction',999.)) if isinstance(source_shape,dict) else 999.
    reasons=[]
    if not source_proof or source_proof.get('method')!='ORIGINAL_COMPONENT_PRESENT;_HARMONIC_SUPPORTED;_NO_MISSING_FUNDAMENTAL':reasons.append('ABSTAIN_NO_ORIGINAL_F0_PROOF')
    if ratio>cfg.max_source_fundamental_ratio:reasons.append('ABSTAIN_F0_NOT_WEAK_ENOUGH_FOR_REPAIR')
    if upper_fraction>cfg.max_source_focus_upper_fraction:reasons.append('ABSTAIN_SOURCE_TOO_HARMONICALLY_BRIGHT_FOR_SUB_REPAIR')
    return reasons,ratio,upper_fraction


def permit(event,arrays,meta,source_digest,source_proof,source_shape,cfg=Config()):
    cfg.validate();baseline=legacy.permit(event,arrays,meta,source_digest);source_reasons,ratio,upper_fraction=_source_vetoes(source_proof,source_shape,cfg)
    if not baseline['allowed']:
        structural=[r for r in baseline.get('reason_codes',[]) if r!='ABSTAIN_LOCAL_ROLE_OR_PITCH']
        if structural:
            return dict(baseline,allowed=False,permission_version=VERSION,permission_path='LEGACY_DENIAL_PRESERVED',envelope_role_indices=[2],source_shape=source_shape,source_proof=source_proof,source_veto_reasons=source_reasons)
    if baseline['allowed']:
        if source_reasons:
            return dict(baseline,allowed=False,reason_codes=source_reasons,permission_version=VERSION,permission_path='STRICT_ROLE_SOURCE_VETO',envelope_role_indices=[2],source_shape=source_shape,source_proof=source_proof,source_veto_reasons=source_reasons)
        return dict(baseline,permission_version=VERSION,permission_path='LEGACY_STRICT_WITH_SOURCE_VETO',envelope_role_indices=[2],source_shape=source_shape,source_proof=source_proof,source_veto_reasons=[])
    if baseline.get('reason_codes')!=['ABSTAIN_LOCAL_ROLE_OR_PITCH']:
        return dict(baseline,permission_version=VERSION,permission_path='LEGACY_DENIAL_PRESERVED',envelope_role_indices=[2],source_shape=source_shape,source_proof=source_proof,source_veto_reasons=source_reasons)
    reasons=list(source_reasons);t=legacy._check(arrays,meta,source_digest);a=float(event['start']);b=float(event['end']);f0=float(event['source_f0_hz']);target=float(event['target_hz'])
    if abs(1200*math.log2(f0/target))>cfg.pitch_tolerance_cents:reasons.append('DENY_NEW_OCTAVE')
    keep=(t>=a+cfg.edge_guard_seconds)&(t<b-cfg.edge_guard_seconds)
    if keep.sum()<6:reasons.append('ABSTAIN_INSUFFICIENT_INTERIOR_FRAMES')
    p=np.asarray(arrays['low_power'],float)+np.asarray(arrays['body_power'],float);roles=p[:,:,1:]/np.maximum(p[:,:,1:].sum(axis=2,keepdims=True),1e-24)
    drums=roles[:,:,0];bass=roles[:,:,1];other=roles[:,:,2];vocals=roles[:,:,3]
    vocal_disagreement=np.abs(vocals[0]-vocals[1]);pitch=np.asarray(arrays['bass_f0_hz'],float);period=np.asarray(arrays['bass_periodicity'],float);cents=np.abs(1200*np.log2(np.maximum(pitch,1e-12)/f0))
    reliable=(drums.max(axis=0)<=cfg.max_drum_share)&(vocals.max(axis=0)<=cfg.max_vocal_share)&(vocal_disagreement<=cfg.max_vocal_context_disagreement)
    reliable&=(cents.max(axis=0)<=cfg.pitch_tolerance_cents)&(period.min(axis=0)>=cfg.min_periodicity)
    # drum leakage may authorize context robustness but is never synthesized;
    # the audible envelope still comes only from bass+other evidence.
    energy=(p[:,:,2]+p[:,:,3]).min(axis=0);peak=max(float(energy.max()),1e-24);reliable&=energy>max(peak*1e-4,1e-12)
    fraction=float(np.mean(reliable[keep])) if np.any(keep) else 0.
    if fraction<cfg.min_supported_fraction:reasons.append('ABSTAIN_FALLBACK_ROLE_OR_PITCH')
    out=dict(baseline,allowed=not reasons,reason_codes=reasons or ['ALLOW_EXISTING_WEAK_F0_FALLBACK'],permission_version=VERSION,permission_path='EXISTING_WEAK_F0_FALLBACK',source_proof=source_proof,source_shape=source_shape,source_veto_reasons=source_reasons,
        envelope_role_indices=[2,3],fallback_supported_fraction=fraction,fallback_bass_other_q20=float(np.percentile((bass+other).min(axis=0)[keep],20)) if np.any(keep) else 0.,fallback_drum_share_q80=float(np.percentile(drums.max(axis=0)[keep],80)) if np.any(keep) else 1.,fallback_vocal_share_q80=float(np.percentile(vocals.max(axis=0)[keep],80)) if np.any(keep) else 1.,fallback_vocal_context_disagreement_p95=float(np.percentile(vocal_disagreement[keep],95)) if np.any(keep) else 1.)
    if out['allowed']:
        out['render_support_times']=t[keep].tolist();out['render_support_mask']=reliable[keep].astype(int).tolist()
    return out
