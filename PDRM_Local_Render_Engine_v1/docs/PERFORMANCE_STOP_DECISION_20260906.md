# PDRM performance stop decision — 2026-09-06

## User decision

Current corrected build completes processing in roughly 1.5x the source duration. This is acceptable. Further speed optimization is not required.

## Decision

Stop the 10x acceleration work. Do not trade numerical behavior, quality gates, AUTO routing, safety checks, cleanup semantics, or maintainability for additional speed.

Use the unit-corrected runtime as the performance baseline going forward. The millisecond conversion defect is a correctness fix and is not reverted for output compatibility.

## Priorities from here

1. Correctness of context units and processing boundaries.
2. Audio quality and established OPPO/Note-Sub/HFTC/HarmonicElasticity behavior.
3. Safe AUTO routing: gain-only -> OPPO -> limiter only on explicit acoustic NotFeasible.
4. Source/output integrity and fail-closed behavior for operational errors.
5. Per-track cleanup of large LOCALAPPDATA intermediates.
6. Performance only if a new regression makes normal use impractical.

No new speed-only DSP or native acceleration path should be merged merely to chase the former 10x target.
