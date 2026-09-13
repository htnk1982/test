"""P08 product-candidate worker with precomputed sealed calibration.

Normal product execution never decodes or scans reference audio. The canonical
24-track calibration is shipped as derived metadata and installed into the local
sealed cache on demand. Legacy/bootstrap construction remains only for imported
fixture verification and is not part of the user GUI path.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,sys,traceback

import accepted_calibration_cache_v53 as calcache
import automatic_joint_v51 as planner51
import gui_runtime_v44 as gui44
import p01_private_calibration_bootstrap as refadapt
import product_gui_runtime_v52 as request
import product_processed_v52 as product
from spleeter_observer_adapter_v48 import SpleeterRuntimeObserver
from target_settings import Targets

VERSION='product-worker-0.3.0'


def bundle_root():
    if getattr(sys,'frozen',False):return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

def runtime_root():return bundle_root()/'PDRM_OBSERVER_RUNTIME'

def _read(path,expected_reference_sha=None):
    if expected_reference_sha is None:return request.read_manifest(path)
    return request._read_manifest(path,expected_reference_sha=expected_reference_sha)

def _references(reference,temp,*,allow_fixture_reference=False):
    if not allow_fixture_reference:return refadapt._reference_files(reference,temp)
    old=refadapt._SELFTEST_REFERENCE;refadapt._SELFTEST_REFERENCE=True
    try:return refadapt._reference_files(reference,temp)
    finally:refadapt._SELFTEST_REFERENCE=old


def run_manifest(path,*,runtime_override=None,expected_reference_sha=None,
                 allow_fixture_reference=False,cache_root_override=None):
    """Run a sealed batch. Override arguments are for imported CI verifier only."""
    manifest=None;session=None;status=None;observer=None
    try:
        manifest=_read(path,expected_reference_sha)
        targets=Targets.from_fields(manifest['targets']);sources=[Path(p) for p in manifest['sources']]
        work=Path(manifest['work_root']).absolute();work.mkdir(parents=True,exist_ok=True)
        session=Path(manifest['session_dir']).absolute();status=gui44.StatusProgress(session,manifest['sha256']);status.file_total=len(sources)
        ref_sha=manifest['reference_sha256'];expected_cal=manifest.get('calibration_sha256')
        status.set('CALIBRATION_CACHE_CHECK',0,1)
        calibration=calcache.load(ref_sha,expected_calibration_sha=expected_cal,root=cache_root_override)
        cache_state='HIT' if calibration is not None else 'MISS'

        # Canonical product path: install derived metadata shipped with the EXE.
        if (calibration is None and not allow_fixture_reference and
            ref_sha==calcache.EXPECTED_REFERENCE_ZIP_SHA256 and
            expected_cal==calcache.EXPECTED_CALIBRATION_SHA256):
            status.set('PRECOMPUTED_CALIBRATION_INSTALL',0,1)
            calibration=calcache.install_precomputed(root=cache_root_override)
            cache_state='PRECOMPUTED_INSTALLED'

        # Retained only for generated fixture verification / noncanonical tests.
        if calibration is None:
            if manifest.get('reference_mode')!=request.BOOTSTRAP_MODE:
                raise RuntimeError('Calibration cache is missing or invalid')
            status.set('REFERENCE_LOCAL_DECODE_FIXTURE',0,1)
            with TemporaryDirectory(prefix='p08_reference_',dir=work) as ref_td:
                refs=_references(Path(manifest['reference_zip']),Path(ref_td),allow_fixture_reference=allow_fixture_reference)
                if len(refs)!=24:raise RuntimeError('Calibration fixture requires exactly 24 references')
                specs=[dict(path=p,role='bass',quality='positive') for p in refs]
                status.set('REFERENCE_CALIBRATION_FIXTURE',0,len(refs));calibration=calcache.build_calibration(specs,status)
            if expected_cal is not None and calibration.get('sha256')!=expected_cal:
                raise RuntimeError('Fixture calibration did not reproduce the expected SHA')
            calcache.save(calibration,ref_sha,expected_calibration_sha=expected_cal,root=cache_root_override);cache_state='BUILT_AND_SAVED'
        status.set('CALIBRATION_READY',1,1)

        with TemporaryDirectory(prefix='p08_observer_',dir=work) as observer_td:
            runtime=Path(runtime_override).absolute() if runtime_override is not None else runtime_root()
            if not runtime.is_dir():raise RuntimeError('Bundled PDRM_OBSERVER_RUNTIME is missing')
            observer=SpleeterRuntimeObserver(runtime,work_root=Path(observer_td),timeout=600)
            planner=planner51.AutomaticJointPlanner(calibration,observer);planner.preflight();identity=planner.identity()
            if identity.get('planner_id')!=planner51.VERSION:raise RuntimeError('Unexpected product planner identity')
            if expected_cal is not None and identity.get('calibration_sha256')!=expected_cal:raise RuntimeError('Planner did not bind expected calibration')
            render_root=work/'renders';render_root.mkdir(parents=True,exist_ok=True)
            for i,source in enumerate(sources,1):
                status.set_file(i,len(sources),source)
                try:
                    result,_=product.run_file(source,render_root,planner=planner,targets=targets,
                        replace_managed=manifest['replace_managed'],progress=status)
                    if (result.get('product_candidate') is not True or result.get('render_backend')!='joint-v46' or result.get('finalizer')!='auto-peak-v3.4.0'):
                        raise RuntimeError('Product candidate identity not preserved')
                    status.success(source,result)
                except InterruptedError:raise
                except Exception as exc:status.failure(source,exc)
            final=status.finish('COMPLETE_WITH_ERRORS' if status.failures else 'COMPLETE')
            final['planner_identity']=identity;final['product_worker_version']=VERSION
            final['calibration_cache']=dict(state=cache_state,version=calcache.VERSION,reference_sha256=ref_sha,
                calibration_sha256=calibration['sha256'],reference_audio_embedded=False,precomputed_product_metadata=not allow_fixture_reference)
            gui44.atomic_json(session/'product_summary.json',final);return final
    except InterruptedError as exc:
        if status is None:raise
        final=status._write('CANCELLED',0,1,'CANCELLED',cancel_reason=str(exc));gui44.atomic_json(session/'product_summary.json',dict(final,product_worker_version=VERSION));return final
    except Exception as exc:
        failure=dict(schema=1,version=VERSION,error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc(),manifest_sha256=(manifest or {}).get('sha256'))
        if session is not None:gui44.atomic_json(session/'PRODUCT_FAILURE.json',failure)
        if status is not None:
            status.failures.append(dict(file=status.current_file,error_type=type(exc).__name__,error=str(exc)));status._write('FAILED',0,1,'FAILED')
        raise
    finally:
        if observer is not None:observer.close()


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--worker-manifest',type=Path,required=True);a=p.parse_args(argv)
    result=run_manifest(a.worker_manifest);return 0 if result['overall'] in ('COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED') else 1

if __name__=='__main__':
    import multiprocessing;multiprocessing.freeze_support();raise SystemExit(main())
