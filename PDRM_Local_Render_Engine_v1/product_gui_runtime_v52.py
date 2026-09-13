"""Sealed request boundary for the P08 product candidate.

Normal execution now has two explicit modes:
- ACCEPTED_CACHE: the already accepted calibration exists locally; no reference
  ZIP path is needed and reference calibration is skipped.
- CANONICAL_BOOTSTRAP: one-time local bootstrap from the canonical reference.zip.

The manifest still pins the canonical reference SHA even in cache mode so a
request can never silently drift to another calibration identity.
"""
from __future__ import annotations
from pathlib import Path
import json

import gui_runtime_v44 as gui44
import accepted_calibration_cache_v53 as calcache
from integration_contract_v40 import digest,file_hash
from target_settings import Targets

VERSION='product-gui-runtime-0.2.0'
SCHEMA=2
RUNTIME_ID='product_candidate_v53'
EXPECTED_REFERENCE_ZIP_SHA256=calcache.EXPECTED_REFERENCE_ZIP_SHA256
EXPECTED_CALIBRATION_SHA256=calcache.EXPECTED_CALIBRATION_SHA256
CACHE_MODE='ACCEPTED_CACHE'
BOOTSTRAP_MODE='CANONICAL_BOOTSTRAP'


def _reference(reference,expected_sha):
    p=Path(reference).absolute()
    if not p.is_file() or p.suffix.lower()!='.zip':
        raise ValueError('Canonical reference.zip is required for one-time calibration bootstrap')
    actual=file_hash(p)
    if actual!=expected_sha:
        raise ValueError('Wrong reference.zip; select the accepted 24-track archive')
    return str(p),actual


def _body(sources,reference,targets,replace_managed,work_root,session_dir,*,expected_reference_sha,cache_ready=False):
    if type(replace_managed) is not bool:raise ValueError('Explicit replacement flag required')
    src=gui44.validate_sources(sources);targets=targets.validate()
    if cache_ready:
        if reference not in (None,''):raise ValueError('Cache-ready request must not depend on a reference path')
        mode=CACHE_MODE;ref=None;ref_sha=expected_reference_sha
    else:
        mode=BOOTSTRAP_MODE;ref,ref_sha=_reference(reference,expected_reference_sha)
    body=dict(
        schema=SCHEMA,version=VERSION,runtime_id=RUNTIME_ID,
        sources=src,reference_mode=mode,reference_zip=ref,reference_sha256=ref_sha,
        calibration_sha256=EXPECTED_CALIBRATION_SHA256 if expected_reference_sha==EXPECTED_REFERENCE_ZIP_SHA256 else None,
        targets=targets.to_dict(),replace_managed=replace_managed,
        work_root=str(Path(work_root).absolute()),session_dir=str(Path(session_dir).absolute()),
    )
    body['sha256']=digest(body);return body


def make_manifest(sources,reference,targets,replace_managed,work_root,session_dir,*,cache_ready=False):
    return _body(sources,reference,targets,replace_managed,work_root,session_dir,
                 expected_reference_sha=EXPECTED_REFERENCE_ZIP_SHA256,cache_ready=cache_ready)


def _read_manifest(path,*,expected_reference_sha):
    value=json.loads(Path(path).read_text(encoding='utf-8'));body=dict(value);seal=body.pop('sha256',None)
    if seal!=digest(body):raise ValueError('Product worker manifest changed')
    if value.get('schema')!=SCHEMA or value.get('version')!=VERSION or value.get('runtime_id')!=RUNTIME_ID:
        raise ValueError('Unknown product worker manifest')
    Targets.from_fields(value['targets'])
    if type(value.get('replace_managed')) is not bool:raise ValueError('Invalid replacement flag')
    gui44.validate_sources(value.get('sources',[]))
    mode=value.get('reference_mode')
    if mode==CACHE_MODE:
        if value.get('reference_zip') is not None or value.get('reference_sha256')!=expected_reference_sha:
            raise ValueError('Invalid accepted-cache reference identity')
    elif mode==BOOTSTRAP_MODE:
        ref,sha=_reference(value.get('reference_zip',''),expected_reference_sha)
        if ref!=str(Path(value['reference_zip']).absolute()) or value.get('reference_sha256')!=sha:
            raise ValueError('Reference identity changed after request seal')
    else:raise ValueError('Unknown reference mode')
    if expected_reference_sha==EXPECTED_REFERENCE_ZIP_SHA256 and value.get('calibration_sha256')!=EXPECTED_CALIBRATION_SHA256:
        raise ValueError('Accepted calibration identity changed')
    if not isinstance(value.get('work_root'),str) or not value['work_root']:raise ValueError('Missing work root')
    if not isinstance(value.get('session_dir'),str) or not value['session_dir']:raise ValueError('Missing session directory')
    return value


def read_manifest(path):return _read_manifest(path,expected_reference_sha=EXPECTED_REFERENCE_ZIP_SHA256)

def write_manifest(path,value):gui44.atomic_json(path,value);return Path(path)
