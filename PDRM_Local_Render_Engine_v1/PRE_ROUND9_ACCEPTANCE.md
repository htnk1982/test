# PDRM Local Render Engine v1 — Pre-Round-9 Acceptance

Round 9 remains **HARD LOCKED**. This table distinguishes CI-proven mechanics from tests that still require local real music / codec execution.

Latest cross-platform evidence at the time of this document: GitHub Actions run `33890239805`, Ubuntu 24.04 + Windows Server 2025, Python 3.12, both successful.

| Gate | Requirement | Status | Evidence / remaining work |
|---|---|---|---|
| G1 | real `pdrm_engine.engine.run_job()` imports and executes | PASS | real-core integration unit tests on Windows/Linux |
| G2 | real WAV preflight / authority gate | PASS | mono/stereo accepted; unsupported 3ch rejected; non-finite/short/low-SR audit implemented |
| G3 | NO-OP is a valid exact solution | PASS | already-optimal input is byte-copied exactly |
| G4 | NORMALIZE_ONLY path | PASS | gain-only candidate reaches safe target without nonlinear processing |
| G5 | baseline limiter / safe frontier | PASS (MVP-0) | spiky synthetic material passes TP safety or retreats to quality fallback |
| G6 | exact outer validation + rollback | PASS | injected post-write gate failure rolls processed result back to exact NO-OP |
| G7 | hard-kill / restart | PASS for real core; PARTIAL for whole runtime | real core is killed at `SAFE_FRONTIER`, publishes no final, restart output equals clean PCM hash; stale runtime locks and pending commits are separately recovered. A whole-process real-music kill/restart remains a local acceptance step. |
| G8 | idempotent second run / no rerender | PASS | real runtime+core second run returns `IDEMPOTENT_SKIP`; counting core called once |
| G9 | foreign output protection | PASS | pre-existing foreign output is never overwritten; no-replace commit is used |
| G10 | input change during render | PASS | input SHA-256 is rechecked before commit; mutation test leaves no final/sidecar |
| G11 | multi-minute real music | NOT YET | must be run locally on at least one real 2mix; CI uses synthetic fixtures only |
| G12 | deterministic PCM | PASS | same input/config yields identical decoded PCM SHA-256; hard-kill restart equals clean run |
| G13 | codec QC | NOT YET | ffmpeg/codec round-trip gate is deliberately outside MVP-0 and must be added before Round 9 |
| G14 | Round 9 hard lock | PASS | config/runtime above round 8 rejected; result must report `round9_executed=false` |

## Additional resilience already covered

- atomic/private staging before final publication
- pending-commit recovery when a process exits after final publish but before sidecar
- SQLite `quick_check`; corrupted DB family archived/rebuilt
- operational SQLite errors (e.g. `database is locked`) are not mislabeled as corruption
- dead PID lock reclaim with PID process-creation token protection
- source file is never quarantined/deleted by the runtime
- maximum failed-attempt counter per job
- persistent `heartbeat.json` and `CANCEL` marker
- owned stale output can be archived/rebuilt; unrelated output cannot
- vectorized limiter release envelope matches scalar recurrence and removes the previous long-render Python loop bottleneck

## Round 9 unlock rule

Round 9 may be unlocked only after all of the following are true:

1. G11 PASS on local real music, including at least one 3+ minute file.
2. G13 codec QC implemented and PASS.
3. Whole-process local kill/restart on real audio completes without foreign/partial final output and rerun verifies.
4. `verify` returns PASS and second identical invocation performs no DSP rerender.

No listening-round code may bypass this gate.
