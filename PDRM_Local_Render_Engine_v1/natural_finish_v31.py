"""PDRM OPPO v3.1 integration wrapper.

It keeps natural_finish v3.0 untouched. During a v3.1 call, only the OPPO backend,
version and identity-module list are replaced under the existing reentrant lock.
The v0.1 listening-selected solver remains first choice inside that backend.
"""
from contextlib import contextmanager
import natural_finish as base
import offline_peak_stream_v31 as oppo31

io=base.io
legacy=base.legacy
FILES=base.FILES
VERSION='natural-finish-3.1.0'
IDENTITY_MODULES=base.IDENTITY_MODULES+(
    'natural_finish_v31.py','offline_peak_stream_v31.py','offline_peak_rescue.py')
verify_final=base.verify_final

@contextmanager
def _runtime():
    # natural_finish uses RLocks, so this remains serial and restores the old
    # module even if processing aborts.
    with base._LOCK:
        old=(base.oppo,base.VERSION,base.IDENTITY_MODULES)
        try:
            base.oppo=oppo31
            base.VERSION=VERSION
            base.IDENTITY_MODULES=IDENTITY_MODULES
            yield
        finally:
            base.oppo,base.VERSION,base.IDENTITY_MODULES=old


def run_file(source,root,*,targets=None,write_mp3=True,interrupt_after=None,preparation='gain_only'):
    with _runtime():
        return base.run_file(source,root,targets=targets,write_mp3=write_mp3,
            interrupt_after=interrupt_after,preparation=preparation)
