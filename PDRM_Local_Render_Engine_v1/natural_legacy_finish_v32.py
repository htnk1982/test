"""Explicit legacy-peak preparation with OPPO v3.2 final processor."""
import natural_finish_v32 as engine
io=engine.io
legacy=engine.legacy
VERSION=engine.VERSION+'-legacy-prep'
FILES=engine.FILES
IDENTITY_MODULES=engine.IDENTITY_MODULES+('natural_legacy_finish_v32.py',)
verify_final=engine.verify_final

def run_file(source,root,*,targets=None,write_mp3=True,interrupt_after=None):
    return engine.run_file(source,root,targets=targets,write_mp3=write_mp3,
        interrupt_after=interrupt_after,preparation='legacy_peak')

def cleanup_source_workspace(source,root,*,success=False,error=None,prestart=False):
    return engine.cleanup_source_workspace(source,root,success=success,error=error,prestart=prestart)
