# PDRM Local Render Engine v1 — Pre-Round-9 Acceptance

Round 9 remains **HARD LOCKED**. This table distinguishes cross-platform CI-proven mechanics from the final local real-music acceptance.

Latest consolidated cross-platform evidence: GitHub Actions run `33890809970`, commit `bd3eaa9a858121ff82c086c4a0bd9bd6ecfecfb3`, Ubuntu 24.04 + Windows Server 2025, Python 3.12. **Both jobs completed successfully.** The suite ran 27 tests on each platform. The representative codec round-trip test actually executed (not skipped), and the whole resilient-runner process was hard-killed while the real DSP core was active, then restarted to the same PCM as a clean run.

| Gate | Requirement | Status | Evidence / remaining work |
|---|---|---|---|
| G1 | real `pdrm_engine.engine.run_job()` imports and executes | PASS | real-core integration tests on Windows/Linux |
| G2 | real WAV preflight / authority gate | PASS | mono/stereo accepted; unsupported 3ch rejected; non-finite/short/low-SR audit implemented |
| G3 | NO-OP is a valid exact solution | PASS | already-optimal input is byte-copied exactly |
| G4 | NORMALIZE_ONLY path | PASS | gain-only candidate reaches a safe target without nonlinear processing |
| G5 | baseline limiter / safe frontier | PASS (MVP-0) | spiky synthetic material passes TP safety or retreats to quality fallback |
| G6 | exact outer validation + rollback | PASS | injected post-write gate failure rolls processed result back to exact NO-OP |
| G7 | whole resilient runtime hard-kill / restart | PASS (mechanics) | Windows + Linux test kills the whole `ResilientRunner` process while the real core is at `SAFE_FRONTIER`; no final exists; same job restarts; `verify` passes; restarted PCM equals independent clean-render PCM; stale process lock is reclaimed |
| G8 | idempotent second run / no rerender | PASS | real runtime+core second run returns `IDEMPOTENT_SKIP`; counting core called once |
| G9 | foreign output protection | PASS | pre-existing foreign output is never overwritten; no-replace commit is used |
| G10 | input change during render | PASS | input SHA-256 is rechecked before commit; mutation test leaves no final/sidecar |
| G11 | multi-minute **real music** | LOCAL PENDING | run locally on at least one actual 3+ minute 2mix; private audio must not be uploaded to this public test repository |
| G12 | deterministic PCM | PASS | same input/config yields identical decoded PCM SHA-256; hard-kill restart equals clean run |
| G13 | representative lossy codec QC mechanics | PASS; REAL MUSIC LOCAL PENDING | bundled `imageio-ffmpeg` fallback removes the system-ffmpeg dependency; codec round-trip test actually ran successfully on Windows/Linux. Final local test must run the available AAC/Opus/MP3 profiles on the real output. These are robustness probes, not claims to emulate a platform's exact codec. |
| G14 | Round 9 hard lock | PASS | config/runtime above round 8 rejected; result must report `round9_executed=false` |

## Additional resilience covered

- atomic/private staging before final publication
- pending-commit recovery when a process exits after final publish but before sidecar
- SQLite `quick_check`; corrupted DB family archived/rebuilt
- operational SQLite errors (e.g. `database is locked`) are not mislabeled as corruption
- dead PID lock reclaim with PID process-creation token protection
- source file is never quarantined/deleted by the runtime
- source SHA-256 is rechecked immediately before final commit
- maximum failed-attempt counter per job
- persistent `heartbeat.json` and `CANCEL` marker
- owned stale output can be archived/rebuilt; unrelated output cannot
- vectorized limiter release envelope matches the scalar recurrence and removes the previous long-render Python loop bottleneck
- representative codec QC can use packaged ffmpeg when no system ffmpeg is installed

## Round 9 unlock rule

Only the local private-audio acceptance now remains. Round 9 may be unlocked after all of the following are true on at least one actual 3+ minute 2mix:

1. long real-audio render completes through the resilient runner;
2. `verify` returns PASS;
3. identical rerun returns `IDEMPOTENT_SKIP` (no DSP rerender);
4. a clean second-destination render has the same PCM SHA-256;
5. representative lossy codec QC executes and passes the configured risk gates;
6. a local whole-process kill/restart on the real track leaves no foreign/partial final and the restarted result verifies.

The next implementation step is an automated `accept_real_audio` command that performs this sequence locally and writes a machine-readable acceptance report. No listening-round code may bypass this gate.
