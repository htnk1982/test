# PDRM Local Render Engine v1 — Core + Resilient Runner / MVP-0

This repository rebuilds the missing DSP core and the local execution shell for
PDRM Local Render Engine v1.

## Definition

PDRM is an offline finalizer for reasonably finished mono/stereo 2mixes. The
finished 2mix is the artistic source of truth. Requested loudness / TP is pursued
only while output-validity and musical-relation gates remain satisfied.

Priority is lexicographic:

1. valid output / no catastrophic defect
2. preserve musical relations
3. avoid audible artifacts
4. approach requested loudness / TP
5. minimize intervention complexity
6. delivery robustness

**NO-OP is a valid successful solution.** Round 9 is hard-locked.

## DSP Core — MVP-0 Universal Safety Shell

`pdrm_engine.engine.run_job(input_path, output_path, config, runtime_context)`
implements:

- WAV preflight
- LUFS / sample peak / chunked oversampled TP / PLR
- crest / transient / spectrum / stereo / section-relation audit
- exact NO-OP
- gain-only candidate
- conservative linked offline limiter
- Loudness–Distortion Frontier retreat
- preservation gates
- deterministic dither and PCM output
- exact post-write validation
- rollback to NO-OP on outer-validation failure
- mandatory runtime context / Round 9 rejection

Advanced operators (Peak→Body, Small-Signal Density, Harmonic Loudness,
spectral clipping, HF acceleration, psychoacoustic multiband search) remain
outside MVP-0 until the safety/runtime acceptance gates pass.

## Resilient Runner

Use `pdrm-safe-render`, not the bare core, for normal local operation.

The resilient runner adds:

- input/config/core fingerprinted job identity
- SQLite ledger + sidecar proof
- live-PID + process-creation-token lock
- stale-lock recovery
- private staging output
- no-replace final publish
- pending-commit recovery after a crash between publish and sidecar
- foreign-output protection
- owned-stale-output archive and rebuild
- idempotent second run (no second DSP render)
- corrupt-ledger archive/rebuild
- persistent heartbeat and cancel marker
- maximum 3 failed attempts per job
- Round 9 result contract verification

## Windows quick start

1. `setup.cmd`
2. `selftest.cmd`
3. For direct core experimentation: drag a WAV onto `run.cmd`
4. For resilient production use from a terminal:

```bat
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime doctor
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime render input.wav output.wav --target-lufs -9 --tp -2
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime verify output.wav
```

## Development tests

```bash
python -m unittest discover -s tests -v
```

CI runs the same suite on Windows and Ubuntu. It includes real-core integration,
post-write rollback, deterministic PCM, hard-kill/no-partial-final behavior,
idempotent runtime suppression, pending-commit recovery, stale-lock recovery,
foreign output protection and corrupt-ledger rebuild.

## Round 9 gate

This is still a **pre-Round-9** build. Passing unit/CI tests proves the rebuilt
MVP-0 core/runtime mechanics; actual multi-minute music, codec QC and the US-SOTA
advanced operators must be validated before Round 9 is unlocked.
