"""Subprocess entry for GUI batch processing.

Only an explicit engineering-fixture runtime is currently executable. The
future product runtime stays closed until P02/P03/P04 supply its accepted planner
and model manifest. This prevents GUI plumbing from silently becoming a release.
"""
from pathlib import Path
import argparse,os,sys
ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
import gui_runtime_v44 as runtime


def fixture_processor(source,targets,replace,work,status):
    if os.environ.get('PDRM_ENABLE_GUI_FIXTURE')!='1':raise RuntimeError('Engineering fixture runtime not explicitly enabled')
    from joint42_selftest import FixturePlanner
    import processed_integration as publish
    result,_=publish.run_file(source,work,planner=FixturePlanner('tail'),targets=targets,
        replace_managed=replace,enable_lab=True,render_backend='joint-v42',progress=status)
    return result


def run_manifest(path):
    manifest=runtime.read_manifest(path);mode=manifest['runtime_id']
    if mode=='engineering_fixture_tail':processor=fixture_processor
    elif mode=='product_release':raise RuntimeError('Product planner/model gate not accepted; P02/P03/P04 remain open')
    else:raise ValueError('Unknown fixed worker runtime')
    result=runtime.run_batch(path,processor)
    return 0 if result['overall'] in ('COMPLETE','COMPLETE_WITH_ERRORS','CANCELLED') else 1


def main(argv=None):
    p=argparse.ArgumentParser();p.add_argument('--worker-manifest',type=Path,required=True);a=p.parse_args(argv)
    return run_manifest(a.worker_manifest)

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support();raise SystemExit(main())
