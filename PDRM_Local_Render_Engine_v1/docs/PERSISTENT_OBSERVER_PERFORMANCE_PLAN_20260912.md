# Persistent Observer Performance Gate — 2026-09-12

## Q1

Can PDRM remove repeated Python/TensorFlow/Spleeter startup from every observer window **without changing the accepted observer semantics or audio decision logic**?

This is a transport/lifetime optimization only. It must not tune P03/P04 thresholds, change Spleeter model/version, alter the two context pads, persist stems, or add stem audio to the master.

## Why now

Private song 11 completed successfully and the listening result was positive: the result was materially improved, sufficiently loud, and the processing did not become irritating. The accepted run nevertheless took roughly 53 minutes. The progress trace shows repeated STEM_OBSERVER work across many windows. The current client launches a new embedded-Python worker for every `observe_dual()` call, and the worker creates a new `Separator` for every process invocation.

The next question is therefore not GPU migration. The first removable cost is repeated process/model initialization.

## Invariants

- accepted P03-A baseline remains `50a4592e45b3f810e905041c25cff1c3e35b2a88`
- Spleeter asset/hash and preprocessing remain unchanged
- contexts remain `(1.0, 2.0)` seconds
- source hash must remain unchanged
- no runtime model download
- no stem audio persisted
- no stem audio crosses the observer IPC boundary
- no stem audio enters the master
- one-shot observer path remains available as an equivalence oracle

## Implementation boundary

Introduce one persistent worker process per `SpleeterRuntimeObserver` instance. The worker loads TensorFlow and constructs the Spleeter `Separator` once, then accepts sequential sealed JSON jobs through a private temporary session directory. Audio remains referenced by source path and stems remain process-memory-only.

## Acceptance gates

1. One-shot and persistent observation on the same generated fixture return equivalent feature arrays within tight floating-point tolerance.
2. Two persistent calls reuse the same worker PID, proving model/process lifetime reuse.
3. Source SHA remains unchanged.
4. Session IPC contains JSON/control data only; no WAV/FLAC/MP3 is persisted.
5. Worker crash/timeout is surfaced as a concrete error and the child can be terminated.
6. Existing P02 Windows isolated-runtime CI passes.
7. Existing P01 Frozen bundle + artifact roundtrip self-test passes.
8. No private audio is sent to CI.

## Stop condition

Do not add GPU/WSL/ONNX migration in this step. If persistent lifetime reuse is proven and the current musical invariants survive, ship that bounded change first. Measure the next private run before deciding whether another inference backend is justified.
