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
- input SHA-256 recheck before commit
- idempotent second run (no second DSP render)
- corrupt-ledger archive/rebuild, without confusing normal lock/I/O errors with corruption
- persistent heartbeat and cancel marker
- maximum 3 failed attempts per job
- Round 9 result contract verification

## Codec QC

`pdrm_engine.codec` performs representative lossy encode/decode stress tests using
available AAC/Opus/MP3 encoders. A packaged `imageio-ffmpeg` fallback is used when
there is no system `ffmpeg` in PATH. These profiles are robustness probes only;
they do **not** claim to emulate Spotify/SoundCloud/etc. exactly.

```bat
codec_qc.cmd output.wav
```

## Windows quick start

1. `setup.cmd`
2. `selftest.cmd`
3. `doctor.cmd`
4. Drag a WAV onto `run.cmd` for resilient rendering
5. Drag the result onto `verify.cmd`

Terminal equivalents:

```bat
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime doctor
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime render input.wav output.wav --target-lufs -9 --tp -2
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime verify output.wav
.venv\Scripts\pdrm-safe-render.exe --work-root .pdrm_runtime codec-qc output.wav
```

## Private real-audio pre-Round-9 acceptance

After setup/selftest, drag one **private 3+ minute WAV** onto:

```text
accept_real_audio.cmd
```

The audio stays on the local PC. The command intentionally:

1. starts the real resilient runner + real DSP core;
2. kills the child process at `SAFE_FRONTIER`;
3. checks that no final output was published;
4. restarts the same job and verifies the output;
5. repeats the identical job and requires `IDEMPOTENT_SKIP`;
6. performs an independent clean-destination render and requires identical PCM SHA-256;
7. runs every available representative lossy codec QC profile;
8. confirms the source hash did not change and Round 9 remained locked;
9. writes `ACCEPTANCE_REPORT.json` and `ACCEPTANCE_REPORT.md` under `.pdrm_acceptance`.

Default acceptance target is deliberately moderate (`-14 LUFS / -2 dBTP`) because
this is an infrastructure acceptance test, not an instruction to master every song
to that loudness.

## Development tests

```bash
python -m unittest discover -s tests -v
```

CI runs the same suite on Windows and Ubuntu. It includes real-core integration,
post-write rollback, deterministic PCM, direct-core and whole-runtime hard-kill
recovery, idempotent runtime suppression, pending-commit recovery, stale-lock
recovery, foreign-output protection, input-mutation rejection, corrupt-ledger
rebuild, and a real representative codec encode/decode round trip.

## Round 9 gate

This is still a **pre-Round-9** build. Cross-platform synthetic/mechanical gates are
implemented and tested. The final missing evidence is one private local 3+ minute
real-music `accept_real_audio.cmd` PASS. Review `PRE_ROUND9_ACCEPTANCE.md` before
changing the hard lock.
