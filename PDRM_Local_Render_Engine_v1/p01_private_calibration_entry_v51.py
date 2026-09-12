"""P01 private-calibration core using observer-pruned automatic_joint_v51.

The accepted v50 musical policy remains the baseline. This wrapper changes only
the planner implementation selected by the existing P01 entry so the established
GUI, privacy boundary, failure record and fixture code remain unchanged.
"""
from __future__ import annotations
from pathlib import Path
import json,time

import automatic_joint_v51 as planner51
import p01_private_calibration_entry as legacy

VERSION='p01-private-calibration-0.1.3'
ACCEPTED_P03A_COMMIT=legacy.ACCEPTED_P03A_COMMIT
AUDIO_EXTS=legacy.AUDIO_EXTS

# Bootstrap compatibility aliases. The MP3 boundary replaces _reference_files
# on this module; calibrate() forwards that replacement into the legacy entry.
_safe_extract_zip=legacy._safe_extract_zip
_reference_files=legacy._reference_files
_hash_manifest=legacy._hash_manifest
_copy_verified=legacy._copy_verified
_fixture_reference=legacy._fixture_reference
_fixture_source=legacy._fixture_source
_encode_mp3=legacy._encode_mp3


def _failure_record(output,source,reference,exc):
    p=legacy._failure_record(output,source,reference,exc)
    try:
        data=json.loads(Path(p).read_text(encoding='utf-8'))
        data['version']=VERSION
        data['planner_implementation']=planner51.VERSION
        Path(p).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    except Exception:
        pass
    return p


def calibrate(source,reference,output,*,targets=None):
    # Deliberately patch only the legacy module's planner handle and the P01
    # boundary callback. All other established P01 behavior remains unchanged.
    started=time.monotonic()
    legacy.planner50=planner51
    legacy._reference_files=_reference_files
    final,manifest=legacy.calibrate(source,reference,output,targets=targets)
    manifest['version']=VERSION
    manifest['planner_implementation']=planner51.VERSION
    manifest['accepted_p03a_commit']=ACCEPTED_P03A_COMMIT
    manifest['performance']=dict(elapsed_seconds=float(time.monotonic()-started),timing_scope='P01_CALIBRATE_END_TO_END')
    (Path(final)/'CALIBRATION_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return final,manifest
