"""Sealed request boundary for the P08 product candidate.

The product candidate adds the one piece P06's generic GUI manifest did not
contain: the canonical private reference.zip identity. The reference remains
local. Normal product execution accepts exactly the already-calibrated 24-MP3
archive; test-only alternate hashes are available only to imported verifier code,
never through the product CLI.
"""
from __future__ import annotations
from pathlib import Path
import json

import gui_runtime_v44 as gui44
from integration_contract_v40 import digest,file_hash
from target_settings import Targets

VERSION='product-gui-runtime-0.1.0'
SCHEMA=1
RUNTIME_ID='product_candidate_v52'
EXPECTED_REFERENCE_ZIP_SHA256='82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a'


def _reference(reference,expected_sha):
    p=Path(reference).absolute()
    if not p.is_file() or p.suffix.lower()!='.zip':
        raise ValueError('Canonical reference.zip is required')
    actual=file_hash(p)
    if actual!=expected_sha:
        raise ValueError('Wrong reference.zip; select the accepted 24-track archive')
    return str(p),actual


def _body(sources,reference,targets,replace_managed,work_root,session_dir,*,expected_reference_sha):
    if type(replace_managed) is not bool:
        raise ValueError('Explicit replacement flag required')
    src=gui44.validate_sources(sources)
    ref,ref_sha=_reference(reference,expected_reference_sha)
    targets=targets.validate()
    body=dict(
        schema=SCHEMA,version=VERSION,runtime_id=RUNTIME_ID,
        sources=src,reference_zip=ref,reference_sha256=ref_sha,
        targets=targets.to_dict(),replace_managed=replace_managed,
        work_root=str(Path(work_root).absolute()),
        session_dir=str(Path(session_dir).absolute()),
    )
    body['sha256']=digest(body)
    return body


def make_manifest(sources,reference,targets,replace_managed,work_root,session_dir):
    """Normal product manifest: canonical reference hash is not configurable."""
    return _body(
        sources,reference,targets,replace_managed,work_root,session_dir,
        expected_reference_sha=EXPECTED_REFERENCE_ZIP_SHA256,
    )


def _read_manifest(path,*,expected_reference_sha):
    value=json.loads(Path(path).read_text(encoding='utf-8'))
    body=dict(value);seal=body.pop('sha256',None)
    if seal!=digest(body):
        raise ValueError('Product worker manifest changed')
    if (value.get('schema')!=SCHEMA or value.get('version')!=VERSION or
            value.get('runtime_id')!=RUNTIME_ID):
        raise ValueError('Unknown product worker manifest')
    Targets.from_fields(value['targets'])
    if type(value.get('replace_managed')) is not bool:
        raise ValueError('Invalid replacement flag')
    gui44.validate_sources(value.get('sources',[]))
    ref,sha=_reference(value.get('reference_zip',''),expected_reference_sha)
    if ref!=str(Path(value['reference_zip']).absolute()) or value.get('reference_sha256')!=sha:
        raise ValueError('Reference identity changed after request seal')
    if not isinstance(value.get('work_root'),str) or not value['work_root']:
        raise ValueError('Missing work root')
    if not isinstance(value.get('session_dir'),str) or not value['session_dir']:
        raise ValueError('Missing session directory')
    return value


def read_manifest(path):
    """Normal product reader. Test fixtures cannot select another archive hash."""
    return _read_manifest(path,expected_reference_sha=EXPECTED_REFERENCE_ZIP_SHA256)


def write_manifest(path,value):
    gui44.atomic_json(path,value)
    return Path(path)
