"""PDRM OPPO v3.2 integration wrapper.

Keeps natural_finish v3.0 and the listening-selected v0.1 kernel untouched.
Only the final OPPO backend is replaced with v3.2 during this call.
"""
from contextlib import contextmanager
from pathlib import Path
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
    """Clean current per-track work and reclaim matching obsolete OPPO caches.

    At prestart the same v3.2 unfinished job is retained for resume, while the
    matching source's v3.0/v3.1 jobs are obsolete and removed. We never delete
    an entire legacy root blindly; every deletion is tied to the selected source
    hash. Public `processed` outputs are outside these roots and remain untouched.
    """
    root=Path(root).resolve()
    results=[workspace_cleanup.cleanup_source(root,source,current_version=VERSION,
        success=success,error=error,prestart=prestart)]
    if prestart:
        for name in ('oppo_finish_v3','oppo_finish_v31'):
            old=root.parent/name
            if old.resolve()==root:continue
            results.append(workspace_cleanup.cleanup_source(old,source,
                current_version='__obsolete_for_v32__',success=False,error=None,prestart=True))
    return dict(
        removed=[p for r in results for p in r.get('removed',[])],
        bytes_freed=sum(r.get('bytes_freed',0) for r in results),
        diagnostic=next((r.get('diagnostic') for r in results if r.get('diagnostic')),None),
        success=bool(success))
