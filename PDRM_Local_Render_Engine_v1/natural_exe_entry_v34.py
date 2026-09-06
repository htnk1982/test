"""Portable Windows entry for PDRM AUTO v3.4."""
from contextlib import contextmanager
import multiprocessing,os,sys
from pathlib import Path
import natural_exe_entry as base
import natural_gui as gui_base
import natural_gui_v34 as gui34

APP_VERSION='3.4.1-auto-exe'

def _backend(preparation):
    import natural_finish_v34
    return natural_finish_v34

def _work_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'oppo_finish_v34'

@contextmanager
def _runtime():
    old=(base.APP_VERSION,base._backend,base._work_root,base.bootstrap,gui_base.choose_targets,gui_base.self_check)
    original_bootstrap=base.bootstrap
    def bootstrap34():
        _,manifest=original_bootstrap()
        import offline_peak_stream_v32 as shared
        # Check the imported bundled implementation before any audio is touched.
        for ms,expected in ((128,6144),(1024,49152)):
            a,b=shared._context_bounds(150*48000,150*48000+2048,300*48000,48000,ms,12)
            if b-a!=expected:raise RuntimeError('Bundled context millisecond contract failed')
        import processed_finish_v32 as app
        return app,manifest
    try:
        base.APP_VERSION=APP_VERSION;base._backend=_backend;base._work_root=_work_root;base.bootstrap=bootstrap34
        gui_base.choose_targets=gui34.choose_targets;gui_base.self_check=gui34.self_check;yield
    finally:
        base.APP_VERSION,base._backend,base._work_root,base.bootstrap,gui_base.choose_targets,gui_base.self_check=old

def run(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    with _runtime():return base.run(args)

if __name__=='__main__':multiprocessing.freeze_support();raise SystemExit(run())
