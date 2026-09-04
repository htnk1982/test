# PDRM Local Render Engine v1 — Pre-Round-9 Acceptance

Round 9 remains **HARD LOCKED**. This table distinguishes cross-platform CI-proven mechanics from the final local real-music acceptance.

Latest consolidated code evidence: GitHub Actions run `33891245929`, commit `4287e32cdd0126d25e4b80c77915e78ca43eb24a`, Ubuntu 24.04 + Windows Server 2025, Python 3.12. **Both jobs completed successfully.** The suite ran **28 tests** on each platform. The new full acceptance sequence itself was executed end-to-end on a synthetic fixture and passed on both systems, including intentional child-process termination, restart, idempotent rerun, clean second render, PCM-hash equality and real lossy codec encode/decode.

| Gate | Requirement | Status | Evidence / remaining work |
|---|---|---|---|
| G1 | real `pdrm_engine.engine.run_job()` imports and executes | PASS | real-core integration tests on Windows/Linux |
| G2 | real WAV preflight / authority gate | PASS | mono/stereo accepted; unsupported 3ch rejected; non-finite/short/low-SR audit implemented |
| G3 | NO-OP is a valid exact solution | PASS | already-optimal input is byte-copied exactly |
| G4 | NORMALIZE_ONLY path | PASS | gain-only candidate reaches a safe target without nonlinear processing |
| G5 | baseline limiter / safe frontier | PASS (MVP-0) | spiky synthetic material passes TP safety or retreats to quality fallback |
| G6 | exact outer validation + rollback | PASS | injected post-write gate failure rolls processed result back to exact NO-OP |
| G7 | whole resilient runtime hard-kill / restart | PASS (mechanics) | Windows + Linux tests kill the whole `ResilientRunner` process while the real core is at `SAFE_FRONTIER`; no final exists; same job restarts; `verify` passes; restarted PCM equals independent clean-render PCM; stale process lock is reclaimed |
| G8 | idempotent second run / no rerender | PASS | real runtime+core second run returns `IDEMPOTENT_SKIP`; counting core called once |
| G9 | foreign output protection | PASS | pre-existing foreign output is never overwritten; no-replace commit is used |
| G10 | input change during render | PASS | input SHA-256 is rechecked before commit; mutation test leaves no final/sidecar |
| G11 | multi-minute **real music** | LOCAL PENDING | run `accept_real_audio.cmd` locally on at least one actual 3+ minute 2mix; private audio must not be uploaded to this public test repository |
| G12 | deterministic PCM | PASS | same input/config yields identical decoded PCM SHA-256; hard-kill restart equals clean run |
| G13 | representative lossy codec QC mechanics | PASS; REAL MUSIC LOCAL PENDING | bundled `imageio-ffmpeg` fallback removes the system-ffmpeg dependency; codec round-trip actually ran on Windows/Linux. The automated local acceptance runs all available representative profiles on the real output. These are robustness probes, not claims to emulate a platform's exact codec. |
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

## Automated private local acceptance

`accept_real_audio.cmd` is implemented. Drag one private 3+ minute WAV onto it. The audio remains local. The command automatically:

1. fingerprints the input and checks duration;
2. starts the real resilient runner/core and intentionally kills the child at `SAFE_FRONTIER`;
3. requires that no final output exists after the kill;
4. restarts the exact same job and verifies it;
5. repeats the exact job and requires `IDEMPOTENT_SKIP`;
6. renders the same input/config to an independent clean destination and requires identical PCM SHA-256;
7. runs all available representative lossy codec profiles;
8. rechecks the source SHA-256 and Round 9 lock;
9. writes `ACCEPTANCE_REPORT.json` + `ACCEPTANCE_REPORT.md` under `.pdrm_acceptance`.

The default local acceptance profile is `-14 LUFS / -2 dBTP`. This is intentionally a moderate infrastructure test target, not a mastering prescription.

## Round 9 unlock rule

Only the private real-audio evidence remains. Round 9 may be considered for unlocking only after one actual 3+ minute WAV produces `ACCEPTANCE_REPORT.json` with `result: PASS` and all gate booleans true.

Even then, the hard lock is not modified automatically. The report must be reviewed first because infrastructure safety is separate from listening quality. No listening-round code may bypass this gate.
