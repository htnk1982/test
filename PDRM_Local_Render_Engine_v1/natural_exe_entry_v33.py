"""Portable Windows entry for PDRM AUTO v3.3."""
from contextlib import contextmanager
import multiprocessing,os,sys
from pathlib import Path
import natural_exe_entry as base
import natural_gui as gui_base
import natural_gui_v33 as gui33

APP_VERSION='3.3.0-auto-exe'

def _backend(preparation):
    import natural_finish_v33
    return natural_finish_v33

def _work_root():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()/'.local/share'))) / 'PDRM_Local_Render_Engine_v1' / 'oppo_finish_v33'

@contextmanager
def _runtime():
    old=(base.APP_VERSION,base._backend,base._work_root,base.bootstrap,gui_base.choose_targets,gui_base.self_check)
    original_bootstrap=base.bootstrap
    def bootstrap33():
        _,manifest=original_bootstrap()
        import processed_finish_v32 as app
        return app,manifest
    try:
        base.APP_VERSION=APP_VERSION;base._backend=_backend;base._work_root=_work_root;base.bootstrap=bootstrap33
        gui_base.choose_targets=gui33.choose_targets;gui_base.self_check=gui33.self_check
        yield
    finally:
        base.APP_VERSION,base._backend,base._work_root,base.bootstrap,gui_base.choose_targets,gui_base.self_check=old

def run(argv=None):
    args=list(sys.argv[1:] if argv is None else argv)
    # v3.3 has no user-selectable peak method. Old CLI flags are accepted by the
    # compatibility parser but never change the backend; record this by design.
    with _runtime():return base.run(args)

if __name__=='__main__':
    multiprocessing.freeze_support();raise SystemExit(run())
