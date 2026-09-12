"""P08 product-candidate worker.

The canonical reference is decoded once per batch, calibration is built once,
and one persistent isolated Spleeter observer is reused across tracks. Normal
CLI execution accepts only the canonical historical reference.zip and resolves
the observer runtime beside the frozen product. Alternate reference/runtime
identities are available only to imported acceptance-verifier calls.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,sys,traceback

import automatic_joint_v51 as planner51
import gui_runtime_v44 as gui44
import p01_private_calibration_bootstrap as refadapt
import product_gui_runtime_v52 as request
import product_processed_v52 as product
from spleeter_observer_adapter_v48 import SpleeterRuntimeObserver
from target_settings import Targets

VERSION='product-worker-0.1.0'


def bundle_root():
    if getattr(sys,'frozen',False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def runtime_root():
    return bundle_root()/'PDRM_OBSERVER_RUNTIME'


def _read(path,expected_reference_sha=None):
    if expected_reference_sha is None:
        return request.read_manifest(path)
    return request._read_manifest(path,expected_reference_sha=expected_reference_sha)


def _references(reference,temp,*,allow_fixture_reference=False):
    if not allow_fixture_reference:
        return refadapt._reference_files(reference,temp)
    old=refadapt._SELFTEST_REFERENCE
    refadapt._SELFTEST_REFERENCE=True
    try:
        return refadapt._reference_files(reference,temp)
    finally:
        refadapt._SELFTEST_REFERENCE=old


def run_manifest(path,*,runtime_override=None,expected_reference_sha=None,
                 allow_fixture_reference=False):
    """Run a sealed batch. Override arguments are for imported CI verifier only."""
    manifest=_read(path,expected_reference_sha)
    targets=Targets.from_fields(manifest['targets'])
    sources=[Path(p) for p in manifest['sources']]
    work=Path(manifest['work_root']).absolute();work.mkdir(parents=True,exist_ok=True)
    session=Path(manifest['session_dir']).absolute()
    status=gui44.StatusProgress(session,manifest['sha256'])
    status.file_total=len(sources)
    observer=None
    try:
        status.set('REFERENCE_LOCAL_DECODE',0,1)
        with TemporaryDirectory(prefix='p08_reference_',dir=work) as ref_td, \
             TemporaryDirectory(prefix='p08_observer_',dir=work) as observer_td:
            refs=_references(Path(manifest['reference_zip']),Path(ref_td),
                             allow_fixture_reference=allow_fixture_reference)
            if len(refs)!=24:
                raise RuntimeError('Accepted calibration requires exactly 24 references')
            status.set('REFERENCE_CALIBRATION',0,1)
            specs=[dict(path=p,role='bass',quality='positive') for p in refs]
            calibration=planner51.make_calibration(specs)
            status.set('REFERENCE_CALIBRATION',1,1)

            runtime=Path(runtime_override).absolute() if runtime_override is not None else runtime_root()
            if not runtime.is_dir():
                raise RuntimeError('Bundled PDRM_OBSERVER_RUNTIME is missing')
            observer=SpleeterRuntimeObserver(runtime,work_root=Path(observer_td),timeout=600)
            planner=planner51.AutomaticJointPlanner(calibration,observer)
            planner.preflight()
            identity=planner.identity()
            if identity.get('planner_id')!=planner51.VERSION:
                raise RuntimeError('Unexpected product planner identity')

            render_root=work/'renders';render_root.mkdir(parents=True,exist_ok=True)
            for i,source in enumerate(sources,1):
                status.set_file(i,len(sources),source)
                try:
                    result,_=product.run_file(
                        source,render_root,planner=planner,targets=targets,
                        replace_managed=manifest['replace_managed'],progress=status)
                    if (result.get('product_candidate') is not True or
                            result.get('render_backend')!='joint-v46' or
                            result.get('finalizer')!='auto-peak-v3.4.0'):
                        raise RuntimeError('Product candidate identity not preserved')
                    status.success(source,result)
                except InterruptedError:
                    raise
                except Exception as exc:
                    status.failure(source,exc)
            final=status.finish('COMPLETE_WITH_ERRORS' if status.failures else 'COMPLETE')
            final['planner_identity']=identity
            final['product_worker_version']=VERSION
            gui44.atomic_json(session/'product_summary.json',final)
            return final
    except InterruptedError as exc:
        final=status._write('CANCELLED',0,1,'CANCELLED',cancel_reason=str(exc))
        gui44.atomic_json(session/'product_summary.json',dict(final,product_worker_version=VERSION))
        return final
    except Exception as exc:
        failure=dict(
            schema=1,version=VERSION,error_type=type(exc).__name__,error=str(exc),
            traceback=traceback.format_exc(),manifest_sha256=manifest.get('sha256') if 'manifest' in locals() else None,
        )
        gui44.atomic_json(session/'PRODUCT_FAILURE.json',failure)
        status._write('FAILED',0,1,'FAILED',failures=[dict(error_type=type(exc).__name__,error=str(exc))])
        raise
    finally:
        if observer is not None:
            observer.close()


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--worker-manifest',type=Path,required=True);a=p.parse_args(argv)
    result=run_manifest(a.worker_manifest)
    return 0 if result['overall'] in ('COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED') else 1


if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    raise SystemExit(main())
