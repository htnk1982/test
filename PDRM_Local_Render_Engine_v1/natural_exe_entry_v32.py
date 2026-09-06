"""Portable Windows entry for PDRM OPPO v3.2."""
from contextlib import contextmanager
import multiprocessing,os
from pathlib import Path
import natural_exe_entry as base

APP_VERSION='3.2.0-oppo-exe'

def _backend(preparation):
    if preparation=='legacy_peak':
        import natural_legacy_finish_v32
        return natural_legacy_finish_v32
    import natural_finish_v32
    return natural_finish_v32

def _work_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'oppo_finish_v32'

@contextmanager
def _runtime():
    old=(base.APP_VERSION,base._backend,base._work_root,base.bootstrap)
    original_bootstrap=base.bootstrap
    def bootstrap32():
        _,manifest=original_bootstrap()
        import processed_finish_v32 as app
        return app,manifest
    try:
        base.APP_VERSION=APP_VERSION;base._backend=_backend;base._work_root=_work_root;base.bootstrap=bootstrap32
        yield
    finally:
        base.APP_VERSION,base._backend,base._work_root,base.bootstrap=old

def run(argv=None):
    with _runtime():return base.run(argv)

if __name__=='__main__':
    multiprocessing.freeze_support();raise SystemExit(run())
