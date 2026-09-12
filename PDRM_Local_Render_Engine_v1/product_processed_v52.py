"""P08 product-candidate publication path.

This module does not invent a new DSP. It reuses P07's accepted publication,
recovery and capacity logic, but fixes the already accepted joint-v46 renderer
so the v51 planner can reach the same-name processed outputs. The underlying
integration receipt remains LAB_TECHNICAL_ONLY until the final P08 private
acceptance; this wrapper is therefore a product *candidate*, not a release flag.
"""
from __future__ import annotations
from pathlib import Path
import hashlib,json

import processed_integration as base
import processed_finish as publisher
import crash_recovery_v43 as recovery
from integration_contract_v40 import capture,digest
from target_settings import Targets

VERSION='product-processed-candidate-0.1.0'
io=publisher.io


def _plain(value):
    return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))


class ProductBackend(base._Backend):
    """P07 backend with the accepted joint-v46 renderer opened explicitly."""
    def __init__(self,planner,progress=None):
        if planner is None:
            raise ValueError('Explicit accepted planner required')
        self.planner=planner
        self.planner_identity=_plain(planner.identity())
        self.render_backend='joint-v46'
        self.progress=progress
        self.request=None
        self.sidecar=None
        self.report=None
        self.replay_snapshot_changed=False
        self.VERSION=VERSION+':'+digest(dict(planner=self.planner_identity,backend=self.render_backend))
        extra=(
            'joint_lowend_v42.py','physical_decay_bridge_v42.py',
            'joint_lowend_v46.py','physical_add_bridge_v46.py','event_groove_v37.py',
        )
        self.IDENTITY_MODULES=tuple(sorted(set(
            base.finish.MODULES+extra+(
                'processed_integration.py','processed_finish.py','crash_recovery_v43.py',
                'product_processed_v52.py',
            )
        )))


def run_file(source,work_root=None,*,planner=None,targets=None,
             replace_managed=False,progress=None,interrupt_after=None):
    """Publish accepted v51/joint-v46 output through the P07 safe publisher."""
    if type(replace_managed) is not bool:
        raise ValueError('Explicit replacement flag required')
    if interrupt_after not in (None,1,2) or isinstance(interrupt_after,bool):
        raise ValueError('Invalid controlled interruption point')
    targets=(targets or Targets()).validate()
    backend=ProductBackend(planner,progress)
    planner.preflight()

    source=Path(source).absolute()
    folder,paths=publisher.output_paths(source)
    root=Path(work_root) if work_root is not None else publisher.default_work_root().parent/'product_candidate_v52'
    root=root.absolute()
    if root.resolve()==source.parent.resolve() or source.parent.resolve() in root.resolve().parents:
        raise ValueError('Render work must be outside original/processed folder')
    base._safe_directory(root)
    base._safe_directory(folder)
    meta=base._safe_directory(folder/'.pdrm')

    backend.request=publisher.request_identity(source,targets,backend=backend)
    request_hash=digest(backend.request)
    key=hashlib.sha256(source.stem.casefold().encode('utf-8')).hexdigest()[:24]
    backend.sidecar=meta/(key+'.'+request_hash+'.integration.json')
    if backend.sidecar.exists() or backend.sidecar.is_symlink():
        base._read_sidecar(backend.sidecar,backend.request)
    lock=meta/(key+'.integration.lock')
    if publisher._redirected(lock):
        raise RuntimeError('Linked lock refused')

    with io.job_lock(lock):
        recovered=recovery.recover(root,source_sha256=backend.request['source_sha256'])
        capacity=base.preflight_space(root,source,folder)
        with recovery.owned_workspace(
                root,source_sha256=backend.request['source_sha256'],request_sha256=request_hash) as owned:
            result,dest=publisher.run_file(
                source,owned,targets=targets,replace_managed=replace_managed,
                backend=backend,interrupt_after=interrupt_after)
            evidence=base._read_sidecar(backend.sidecar,backend.request)
            if (result.get('status')!='COMPLETE' or result.get('request')!=backend.request or
                    result.get('files')!=evidence['output_files']):
                raise RuntimeError('Publication and integration evidence disagree')
            for name,expected in evidence['output_files'].items():
                path=folder/name
                if publisher._redirected(path) or not path.is_file() or io.file_hash(path)!=expected:
                    raise RuntimeError('Published output changed before acceptance')
            if io.file_hash(source)!=backend.request['source_sha256']:
                raise RuntimeError('Source changed before acceptance')
        if Path(owned).exists():
            raise RuntimeError('Owned completed render cache not removed')

        return dict(
            result,
            publication_scope='PRODUCT_CANDIDATE_NOT_FINAL',
            product_candidate=True,
            product_version=VERSION,
            planner_identity=backend.planner_identity,
            render_backend='joint-v46',
            finalizer='auto-peak-v3.4.0',
            finalizer_policy='GAIN_ONLY -> OPPO -> LIMITER_IF_OPPO_NOT_FEASIBLE',
            final_cache_removed=True,
            replay_verified_snapshot_changed=backend.replay_snapshot_changed,
            hard_termination_recovery='STALE_DEAD_OWNER_ONLY',
            recovery=recovered,
            capacity_preflight=capacity,
        ),dest
