"""PDRM OPPO v3.2 integration wrapper.

Keeps natural_finish v3.0 and the listening-selected v0.1 kernel untouched.
Only the final OPPO backend is replaced with v3.2 during this call.
"""
from contextlib import contextmanager
import natural_finish as base
import offline_peak_stream_v32 as oppo32
import workspace_cleanup

io=base.io
legacy=base.legacy
FILES=base.FILES
VERSION='natural-finish-3.2.0'
IDENTITY_MODULES=base.IDENTITY_MODULES+(
    'natural_finish_v32.py','offline_peak_stream_v32.py','offline_peak_context.py','workspace_cleanup.py')
verify_final=base.verify_final

@contextmanager
def _runtime():
    with base._LOCK:
        old=(base.oppo,base.VERSION,base.IDENTITY_MODULES)
        try:
            base.oppo=oppo32;base.VERSION=VERSION;base.IDENTITY_MODULES=IDENTITY_MODULES
            yield
        finally:
            base.oppo,base.VERSION,base.IDENTITY_MODULES=old

def run_file(source,root,*,targets=None,write_mp3=True,interrupt_after=None,preparation='gain_only'):
    with _runtime():
        return base.run_file(source,root,targets=targets,write_mp3=write_mp3,
            interrupt_after=interrupt_after,preparation=preparation)

def cleanup_source_workspace(source,root,*,success=False,error=None,prestart=False):
    return workspace_cleanup.cleanup_source(root,source,current_version=VERSION,
        success=success,error=error,prestart=prestart)
