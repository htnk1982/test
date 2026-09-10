"""Publish new integration output through the existing same-name publisher.

LAB opt-in is mandatory. Publication COMPLETE is not musical approval. Fresh
verified snapshots and exact delivered-audio identity are both checked. Normal
and hard-death workspaces are owned by sealed manifests; stale dead owners can
be recovered on the next run without touching other sources or user outputs.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json,math,shutil
import integrated_finish_v40 as finish
import processed_finish as publisher
import crash_recovery_v43 as recovery
from integration_contract_v40 import capture,digest,valid_hash
from target_settings import Targets

VERSION='processed-integration-lab-1.1.0'
SCHEMA=1
io=publisher.io
ASSESSMENTS={'KEEP_SUPPORTED','CANDIDATE','PARTIAL','ABSTAIN'}
MIN_HEADROOM_BYTES=128*1024**2


def _plain(value):return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))

def _safe_directory(path):
    path=Path(path).absolute()
    for node in (path,)+tuple(path.parents):
        if publisher._redirected(node):raise ValueError('Redirected output/work directory refused: '+str(node))
    publisher._plain_dir(path);return path


def _read_sidecar(path,request):
    if publisher._redirected(path) or not path.is_file() or path.stat().st_size>2*1024**2:raise RuntimeError('Missing or invalid integration receipt')
    value=io.read_json(path);body=dict(value);seal=body.pop('sha256',None)
    if seal!=digest(body) or value.get('schema')!=SCHEMA or value.get('request')!=request:raise RuntimeError('Integration receipt changed or belongs to another request')
    if value.get('lowend_assessment') not in ASSESSMENTS or value.get('quality_status')!='NOT_EVALUATED':raise RuntimeError('Invalid musical assessment in receipt')
    if value.get('publication_scope')!='LAB_TECHNICAL_ONLY' or not valid_hash(value.get('lowend_pcm_sha256')):raise RuntimeError('Invalid LAB output/PCM identity')
    return value


def same_delivery(previous,current):
    excluded={'snapshot_sha256','sha256'}
    return {k:v for k,v in previous.items() if k not in excluded}=={k:v for k,v in current.items() if k not in excluded}


def estimate_required_bytes(source):
    ident=capture(source)
    # Existing integration may hold several double-precision intermediates and
    # encoded copies. Conservative finite preflight, not a guarantee against a
    # filesystem that changes capacity mid-run.
    return max(MIN_HEADROOM_BYTES,ident.frames*ident.channels*8*12+64*1024**2)


def preflight_space(root,source,folder):
    required=estimate_required_bytes(source)
    work_free=shutil.disk_usage(root).free
    output_free=shutil.disk_usage(folder).free
    # Output needs at least delivered PCM24 + encoded copy plus journal margin.
    ident=capture(source);public_required=max(32*1024**2,ident.frames*ident.channels*3+16*1024**2)
    if work_free<required:raise OSError(f'Insufficient working space: need {required}, free {work_free}')
    if output_free<public_required:raise OSError(f'Insufficient output space: need {public_required}, free {output_free}')
    return dict(work_required_bytes=required,work_free_bytes=work_free,output_required_bytes=public_required,output_free_bytes=output_free)


class _Backend:
    FILES=('MASTER.wav','ENCODE_INPUT.wav','LISTEN_320kbps.mp3')
    def __init__(self,planner,render_backend,progress=None):
        if planner is None:raise ValueError('Explicit planner required; no silent KEEP')
        if render_backend not in ('broad-v40','joint-v42'):raise ValueError('Unknown fixed-registry renderer')
        self.planner=planner;self.planner_identity=_plain(planner.identity());self.render_backend=render_backend;self.progress=progress
        self.request=None;self.sidecar=None;self.report=None;self.replay_snapshot_changed=False
        self.VERSION=VERSION+':'+digest(dict(planner=self.planner_identity,backend=render_backend))
        extra=('joint_lowend_v42.py','physical_decay_bridge_v42.py') if render_backend=='joint-v42' else ()
        self.IDENTITY_MODULES=tuple(sorted(set(finish.MODULES+extra+('processed_integration.py','processed_finish.py','crash_recovery_v43.py'))))
    def run_file(self,source,root,*,targets=None,write_mp3=True):
        if write_mp3 is not True or self.request is None or self.sidecar is None:raise ValueError('Bound publication context and WAV/MP3 pair required')
        if _plain(self.planner.identity())!=self.planner_identity:raise RuntimeError('Planner identity changed before rendering')
        raw,final=finish.run_lab(source,root,self.planner,targets=targets,write_mp3=True,enable_lab=True,progress=self.progress,render_backend=self.render_backend)
        verified=finish._proof(final,raw['identity']);comparable=dict(raw);comparable.pop('rerun_status',None)
        if comparable!=verified:raise RuntimeError('Returned report differs from sealed completion report')
        if (raw.get('status')!='LAB_RENDER_COMPLETE_NOT_LISTENING_APPROVED' or raw.get('source_unchanged') is not True or raw.get('old_note_sub_called') is not False or raw.get('render_backend')!=self.render_backend or raw.get('lowend_assessment') not in ASSESSMENTS or raw['identity']['planner']!=self.planner_identity or raw['identity']['write_mp3'] is not True):raise RuntimeError('New-chain verification/provenance failed')
        if capture(source).file_sha256!=self.request['source_sha256']:raise RuntimeError('Original changed before publication')
        if raw['requested_targets']!=(targets or Targets()).validate().to_dict():raise RuntimeError('Rendered targets differ from request')
        names=(Path(source).stem+'.wav',Path(source).stem+'.mp3');hashes={names[0]:io.file_hash(final/self.FILES[0]),names[1]:io.file_hash(final/self.FILES[2])}
        evidence=dict(schema=SCHEMA,version=VERSION,request=self.request,publication_scope='LAB_TECHNICAL_ONLY',quality_status='NOT_EVALUATED',lowend_assessment=raw['lowend_assessment'],output_files=hashes,lowend_pcm_sha256=raw['lowend_report']['output_identity']['pcm_sha256'],planner_identity=self.planner_identity,render_backend=self.render_backend,source_sha256=self.request['source_sha256'],snapshot_sha256=raw['snapshot_sha256'],master_metrics=raw['master_metrics'],codec_metrics=raw['codec_metrics'],prep_route=raw['preparation']['auto_route'],master_route=raw['master']['auto_route'],codec_routes=[p['auto_report']['auto_route'] for p in raw['codec_trials']],old_note_sub_called=False,sub_synthesis=raw['sub_synthesis'],work_cleanup='SEALED_OWNED_WORKSPACE',hard_termination_recovery='STALE_DEAD_OWNER_ONLY')
        evidence=_plain(evidence);evidence['sha256']=digest(evidence)
        if self.sidecar.exists():
            previous=_read_sidecar(self.sidecar,self.request)
            if not same_delivery(previous,evidence):
                keys=sorted(k for k in set(previous)|set(evidence) if k not in ('sha256','snapshot_sha256') and previous.get(k)!=evidence.get(k));raise RuntimeError('Rerender delivery differs; nothing overwritten; fields='+','.join(keys))
            self.replay_snapshot_changed=previous['snapshot_sha256']!=evidence['snapshot_sha256']
        else:
            if self.sidecar.is_symlink():raise RuntimeError('Linked receipt refused')
            io.atomic_json(self.sidecar,evidence)
        self.report=raw
        return dict(raw,status='COMPLETE',identity=dict(source_sha256=self.request['source_sha256'],integration_identity=raw['identity'])),final
    def verify_final(self,final,identity):
        if identity.get('source_sha256')!=self.request['source_sha256']:raise RuntimeError('Publisher/source identity mismatch')
        raw=finish._proof(final,identity['integration_identity']);receipt=_read_sidecar(self.sidecar,self.request)
        if raw['lowend_assessment']!=receipt['lowend_assessment'] or raw['lowend_report']['output_identity']['pcm_sha256']!=receipt['lowend_pcm_sha256']:raise RuntimeError('Musical assessment/lowend PCM changed')
        for name,internal in zip((Path(self.request['source_name']).stem+'.wav',Path(self.request['source_name']).stem+'.mp3'),(self.FILES[0],self.FILES[2])):
            if io.file_hash(Path(final)/internal)!=receipt['output_files'][name]:raise RuntimeError('Verified output changed before publisher copy')
        return raw


def run_file(source,work_root=None,*,planner=None,targets=None,render_backend='joint-v42',enable_lab=False,replace_managed=False,progress=None,interrupt_after=None):
    if enable_lab is not True:raise RuntimeError('Release blocked: explicit LAB opt-in required')
    if type(replace_managed) is not bool:raise ValueError('Explicit replacement flag required')
    if interrupt_after not in (None,1,2) or isinstance(interrupt_after,bool):raise ValueError('Invalid controlled interruption point')
    targets=(targets or Targets()).validate();backend=_Backend(planner,render_backend,progress);planner.preflight()
    source=Path(source).absolute();folder,paths=publisher.output_paths(source)
    root=Path(work_root) if work_root is not None else publisher.default_work_root().parent/'integrated_publication';root=root.absolute()
    if root.resolve()==source.parent.resolve() or source.parent.resolve() in root.resolve().parents:raise ValueError('Render work must be outside original/processed folder')
    _safe_directory(root);_safe_directory(folder);meta=_safe_directory(folder/'.pdrm')
    backend.request=publisher.request_identity(source,targets,backend=backend);request_hash=digest(backend.request)
    key=hashlib.sha256(source.stem.casefold().encode('utf-8')).hexdigest()[:24]
    backend.sidecar=meta/(key+'.'+request_hash+'.integration.json')
    if backend.sidecar.exists() or backend.sidecar.is_symlink():_read_sidecar(backend.sidecar,backend.request)
    lock=meta/(key+'.integration.lock')
    if publisher._redirected(lock):raise RuntimeError('Linked lock refused')
    with io.job_lock(lock):
        recovered=recovery.recover(root,source_sha256=backend.request['source_sha256'])
        capacity=preflight_space(root,source,folder)
        with recovery.owned_workspace(root,source_sha256=backend.request['source_sha256'],request_sha256=request_hash) as owned:
            result,dest=publisher.run_file(source,owned,targets=targets,replace_managed=replace_managed,backend=backend,interrupt_after=interrupt_after)
            evidence=_read_sidecar(backend.sidecar,backend.request)
            if result.get('status')!='COMPLETE' or result.get('request')!=backend.request or result.get('files')!=evidence['output_files']:raise RuntimeError('Publication and integration evidence disagree')
            for name,expected in evidence['output_files'].items():
                path=folder/name
                if publisher._redirected(path) or not path.is_file() or io.file_hash(path)!=expected:raise RuntimeError('Published output changed before acceptance')
            if io.file_hash(source)!=backend.request['source_sha256']:raise RuntimeError('Source changed before acceptance')
        if Path(owned).exists():raise RuntimeError('Owned completed render cache not removed')
        return dict(result,publication_scope='LAB_TECHNICAL_ONLY',quality_status=evidence['quality_status'],lowend_assessment=evidence['lowend_assessment'],processing_evidence=str(backend.sidecar),final_cache_removed=True,replay_verified_snapshot_changed=backend.replay_snapshot_changed,hard_termination_recovery='STALE_DEAD_OWNER_ONLY',recovery=recovered,capacity_preflight=capacity),dest
