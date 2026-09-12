"""P01 v51 bootstrap: reuse the accepted canonical-MP3 boundary with v51 core."""
from __future__ import annotations
from pathlib import Path
import json

import automatic_joint_v51 as planner51
import p01_private_calibration_bootstrap as legacy
import p01_private_calibration_entry_v51 as core

# The accepted bootstrap functions resolve their module-global `core` at call
# time. Redirect that single dependency to the v51 wrapper; the canonical MP3
# validation/decode/provenance implementation itself remains unchanged.
legacy.core=core
core._reference_files=legacy._reference_files

VERSION='p01-reference-compat-v51-0.1.0'
calibrate=legacy.calibrate
_failure=legacy._failure
gui=legacy.gui


def self_test(dest):
    summary=legacy.self_test(dest)
    summary['bootstrap_version']=VERSION
    summary['planner_implementation']=planner51.VERSION
    path=Path(dest).resolve()/'P01_BUNDLE_SELFTEST.json'
    path.write_text(json.dumps(summary,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    return summary


def main():
    # Reuse the accepted CLI/GUI parser, replacing only its self-test symbol so
    # delivered-artifact acceptance records v51 explicitly.
    legacy.self_test=self_test
    return legacy.main()


if __name__=='__main__':
    main()
