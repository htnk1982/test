"""Sealed reference calibration cache for the single-user product.

The product ships only derived numerical calibration metadata, never reference
audio. The canonical 24-track reference set was calibrated in the private ChatGPT
workspace once, so the user PC no longer needs to decode or scan reference.zip.
The historical P01 accepted calibration SHA is retained as provenance; the
precomputed product calibration differs only by cross-platform floating-point
serialization/rounding and is separately sealed under its own deterministic SHA.
"""
from __future__ import annotations
from dataclasses import asdict
from pathlib import Path
import json,os,tempfile

import auto_peak_v34 as auto
import automatic_joint_v51 as planner51
import automatic_lowend_v41 as broad41
import context_occupancy_lab as occupancy
import lowend_boundary_lab as boundary
import relative_low_dominance_v49 as dominance
import source_events_v41 as events
from integration_contract_v40 import capture,digest,file_hash

VERSION='accepted-calibration-cache-0.2.0'
SCHEMA=2
EXPECTED_REFERENCE_ZIP_SHA256='82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a'
P01_ACCEPTED_CALIBRATION_SHA256='0e258cf233e07e664f7eb56d5e161c20b270211a322282af88efa494993279e1'
EXPECTED_CALIBRATION_SHA256='b2c094d02e6da731c9953ea65f7d2c4fcba7b31b588b6049af86aa0e2d97399f'
PRECOMPUTED_FILENAME='precomputed_calibration_v54.json'
# P01 reports expose the relative-low caps, allowing a direct numerical parity
# check independent of the old platform-specific JSON hash.
P01_RELATIVE_CAP_Q90_DB=16.873808082471403
P01_RELATIVE_CAP_Q97_DB=22.372580401832117
PRECOMPUTED_PARITY_TOLERANCE=1e-9


def default_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'accepted_calibration'


def cache_path(reference_sha=EXPECTED_REFERENCE_ZIP_SHA256,root=None):
    root=Path(root) if root is not None else default_root()
    return root/(reference_sha+'.json')


def precomputed_path():
    return Path(__file__).resolve().parent/PRECOMPUTED_FILENAME


def _atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix='.pdrm_cal_',suffix='.tmp',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as f:
            json.dump(value,f,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def _relative_from_features(features,ids,pcms):
    rows=[dominance._signature(f) for f in features]
    atlas=dict(
        schema=1,version=dominance.VERSION,reference_ids=list(ids),pcm_groups=list(pcms),per_track=rows,
        cap_q90_db=max(r['q90_db'] for r in rows)+dominance.MARGIN_DB,
        cap_q97_db=max(r['q97_db'] for r in rows)+dominance.MARGIN_DB,
        margin_db=dominance.MARGIN_DB,minimum_excess_db=dominance.MIN_EXCESS_DB,
        max_cut_db=dominance.MAX_CUT_DB,
        scope='Positive-reference low/mid balance envelope; duration alone is not a defect',
    )
    atlas['sha256']=digest(atlas)
    return atlas


def build_calibration(reference_specs,progress=None):
    """Legacy/bootstrap builder retained for fixture tests only."""
    if len(reference_specs)<4:raise ValueError('At least four independent references required')
    features=[];ids=[];pcms=[];labels=[]
    for i,spec in enumerate(reference_specs):
        if spec.get('role')!='bass' or spec.get('quality')!='positive':
            raise ValueError('Only explicit bass-positive references are accepted')
        ident=capture(spec['path'])
        if ident.file_sha256 in ids or ident.pcm_sha256 in pcms:
            raise ValueError('Repeated decoded reference is not an independent group')
        m=auto.measure(spec['path'],progress,'REFERENCE_MEASURE')
        if m['lufs_i'] is None:raise ValueError('Reference has no finite loudness')
        features.append(events.extract_features(spec['path'],anchor_gain_db=-14-m['lufs_i'],progress=progress))
        ids.append(ident.file_sha256);pcms.append(ident.pcm_sha256)
        labels.append(dict(role='bass',quality='positive',scope='weak_track_role'))
        if progress:progress.set('REFERENCE_CALIBRATION_SHARED',i+1,len(reference_specs))
    bundle=dict(
        schema=1,version=broad41.VERSION,extractor=events.VERSION,
        broad=boundary.calibrate(features,ids),context=occupancy.calibrate(features,ids),
        source_groups=ids,pcm_groups=pcms,labels=labels,
        target='empirical_low_occupancy_and_hit_envelope',subjective_certification=False,
    )
    bundle['sha256']=digest(bundle)
    bundle['relative_low']=_relative_from_features(features,ids,pcms)
    bundle.pop('sha256');bundle['sha256']=digest(bundle)
    planner51.validate_calibration(bundle)
    return bundle


def _validate_precomputed(calibration):
    if not isinstance(calibration,dict):raise RuntimeError('Bundled calibration is not a JSON object')
    claimed=calibration.get('sha256');body=dict(calibration);body.pop('sha256',None)
    if claimed!=EXPECTED_CALIBRATION_SHA256 or digest(body)!=claimed:
        raise RuntimeError('Bundled calibration seal mismatch')
    relative=calibration.get('relative_low') or {};rsha=relative.get('sha256');rbody=dict(relative);rbody.pop('sha256',None)
    if not rsha or digest(rbody)!=rsha:raise RuntimeError('Bundled relative calibration seal mismatch')
    if len(calibration.get('source_groups',[]))!=24 or len(calibration.get('pcm_groups',[]))!=24:
        raise RuntimeError('Bundled calibration must represent exactly 24 canonical references')
    if len(set(calibration['source_groups']))!=24 or len(set(calibration['pcm_groups']))!=24:
        raise RuntimeError('Bundled calibration contains duplicate reference identities')
    if abs(float(relative.get('cap_q90_db'))-P01_RELATIVE_CAP_Q90_DB)>PRECOMPUTED_PARITY_TOLERANCE:
        raise RuntimeError('Bundled q90 calibration differs from accepted P01 evidence')
    if abs(float(relative.get('cap_q97_db'))-P01_RELATIVE_CAP_Q97_DB)>PRECOMPUTED_PARITY_TOLERANCE:
        raise RuntimeError('Bundled q97 calibration differs from accepted P01 evidence')
    planner51.validate_calibration(calibration)
    return calibration


def read_precomputed():
    path=precomputed_path()
    if not path.is_file():raise RuntimeError('Bundled precomputed calibration metadata is missing')
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:raise RuntimeError('Bundled precomputed calibration metadata is unreadable') from exc
    return _validate_precomputed(value)


def save(calibration,reference_sha,*,expected_calibration_sha=None,root=None):
    planner51.validate_calibration(calibration)
    actual=calibration.get('sha256')
    if expected_calibration_sha is not None and actual!=expected_calibration_sha:
        raise RuntimeError('Calibration differs from the expected product calibration; cache not written')
    body=dict(
        schema=SCHEMA,version=VERSION,planner_version=planner51.VERSION,
        reference_sha256=reference_sha,calibration_sha256=actual,calibration=calibration,
        reference_audio_embedded=False,derived_metadata_only=True,
    )
    body['seal_sha256']=digest(body)
    path=cache_path(reference_sha,root);_atomic_json(path,body)
    return path


def load(reference_sha=EXPECTED_REFERENCE_ZIP_SHA256,*,expected_calibration_sha=EXPECTED_CALIBRATION_SHA256,root=None):
    path=cache_path(reference_sha,root)
    if not path.is_file():return None
    try:value=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return None
    body=dict(value);seal=body.pop('seal_sha256',None)
    if seal!=digest(body):return None
    if (value.get('schema')!=SCHEMA or value.get('version')!=VERSION or
            value.get('planner_version')!=planner51.VERSION or
            value.get('reference_sha256')!=reference_sha or
            value.get('reference_audio_embedded') is not False or
            value.get('derived_metadata_only') is not True):return None
    calibration=value.get('calibration')
    if not isinstance(calibration,dict) or calibration.get('sha256')!=value.get('calibration_sha256'):return None
    if expected_calibration_sha is not None and value.get('calibration_sha256')!=expected_calibration_sha:return None
    try:planner51.validate_calibration(calibration)
    except Exception:return None
    return calibration


def install_precomputed(root=None):
    current=load(root=root)
    if current is not None:return current
    calibration=read_precomputed()
    save(calibration,EXPECTED_REFERENCE_ZIP_SHA256,expected_calibration_sha=EXPECTED_CALIBRATION_SHA256,root=root)
    installed=load(root=root)
    if installed is None:raise RuntimeError('Precomputed calibration could not be installed into LocalAppData')
    return installed


def has_accepted(root=None):
    return load(root=root) is not None


def verify_reference(reference,expected_sha=EXPECTED_REFERENCE_ZIP_SHA256):
    path=Path(reference).absolute()
    if not path.is_file() or path.suffix.lower()!='.zip':raise ValueError('Canonical reference.zip is required for fixture/bootstrap mode')
    actual=file_hash(path)
    if actual!=expected_sha:raise ValueError('Wrong reference.zip')
    return path,actual
