"""OPPO v3.4 execution wrapper.

The v3.2 whole-track orchestration remains the behavioral reference. Only its
long-context module is swapped, under a lock, for the mathematically equivalent
sparse principal-block solver. Previous v3.2/v3.3 modules remain untouched.
"""
from __future__ import annotations
from contextlib import contextmanager
from pathlib import Path
import threading
import offline_peak_stream_v32 as base
import offline_peak_context_v34 as context

VERSION='offline-peak-stream-0.5.0-sparse-context'
MAX_SECONDS=base.MAX_SECONDS
verify_kernel=base.verify_kernel
validate_source=base.validate_source
read_padded=base.read_padded
scaled_file=base.scaled_file
measure=base.measure
quality_report=base.quality_report
_shape=base._shape
ContextConfig=context.ContextConfig
_LOCK=threading.RLock()

@contextmanager
def _runtime(progress=None):
    with _LOCK:
        old=(base.context,base.VERSION,base.__file__)
        with context.bind_progress(progress):
            try:
                base.context=context;base.VERSION=VERSION;base.__file__=__file__
                yield
            finally:
                base.context,base.VERSION,base.__file__=old

def render_fixed_gain(source,work,gain_db,ceiling,cfg=None,*,context_cfg=None,chunk_seconds=2.0,progress=None,interrupt_after=None):
    import offline_peak_lab as kernel
    cfg=cfg or kernel.Config();context_cfg=context_cfg or context.ContextConfig()
    with _runtime(progress):
        return base.render_fixed_gain(source,work,gain_db,ceiling,cfg,context_cfg=context_cfg,
            chunk_seconds=chunk_seconds,progress=progress,interrupt_after=interrupt_after)

def fit(source,dest,work,target,ceiling,*,cfg=None,context_cfg=None,progress=None,chunk_seconds=2.0,interrupt_after=None):
    import offline_peak_lab as kernel
    cfg=cfg or kernel.Config();context_cfg=context_cfg or context.ContextConfig()
    if progress:progress.set('OPPO_PLAN',0,1)
    with _runtime(progress):
        report=base.fit(source,dest,work,target,ceiling,cfg=cfg,context_cfg=context_cfg,
            progress=progress,chunk_seconds=chunk_seconds,interrupt_after=interrupt_after)
    report=dict(report,execution_engine=VERSION,long_context_solver=context.VERSION)
    return report
