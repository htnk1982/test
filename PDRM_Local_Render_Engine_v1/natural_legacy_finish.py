"""Explicit compatibility frontend with the same OPPO final processor.
This module is selected before rendering. No automatic fallback from gain-only.
"""
import natural_finish as engine
io=engine.io
legacy=engine.legacy
VERSION=engine.VERSION+'-legacy-prep'
FILES=engine.FILES
IDENTITY_MODULES=engine.IDENTITY_MODULES+('natural_legacy_finish.py',)
verify_final=engine.verify_final

def run_file(source,root,*,targets=None,write_mp3=True,interrupt_after=None):
    return engine.run_file(source,root,targets=targets,write_mp3=write_mp3,
        interrupt_after=interrupt_after,preparation='legacy_peak')
