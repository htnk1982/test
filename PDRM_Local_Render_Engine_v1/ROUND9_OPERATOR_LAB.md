# PDRM Round 9 Operator Lab

## Status

**Experimental only.**  This directory does not unlock or modify the production
`pdrm_engine` / `pdrm_runtime` Round 8 hard cap.  Round 9 is executed only by
`pdrm_operator_lab.round9` or `round9_lab.cmd`.

## Crux

Can a very small nonlinear harmonic/loudness operator add **surface gloss and
elasticity** to the user-selected Round 8 A baseline without reducing attack,
groove or breathability?

This round intentionally does **not** combine clipping, HF acceleration,
multiband limiting, spectral repair, EQ, or a new density stage.

## Candidates

1. `Control_Round8A`
   - Same decoded Round 8 A baseline.
   - Level-matched only.

2. `HarmonicElasticity`
   - 4x oversampled PDRM-original odd-symmetric cubic/quintic transfer.
   - Default: `a=0.105`, quintic scale `0.30`.
   - It is not a proprietary processor emulation.

3. `PeakProtectedLoudness`
   - Small/mid amplitude promotion, max `0.70 dB`.
   - Promotion continuously fades to zero near larger amplitudes.
   - Extremely light odd cubic elasticity after promotion.
   - No clipping or limiter is silently inserted.

## Fairness contract

- Every candidate begins from the exact same decoded baseline PCM.
- Baseline is normalized to **-14.00 LUFS-I** before nonlinear processing.
- Nonlinear candidates are normalized again to **-14.00 LUFS-I** after processing.
- 4x polyphase oversampling is applied only around the nonlinear transfers.
- If a candidate approaches 0 dBTP, the experiment aborts instead of adding an
  unplanned limiter.
- Blind mapping is deterministic from input/config hashes.
- The blind ZIP does not contain the reveal mapping.

## Listening decision

Rank A/B/C only after repeated listening.

PASS means:

- gloss / elasticity rather than simple brightness;
- body and upper partials feel like one physical object;
- attack and groove stay alive;
- breathing space is not reduced;
- no hot, hard, fizzy or squeezed sensation after repetition.

A numerical metric moving toward a reference corridor does **not** override the
listening result.

## Local execution

1. Keep the accepted Local Render Engine installation as-is.
2. Download/extract the `pdrm-round9-operator-lab` branch into a new folder.
3. Run `setup.cmd` and `selftest.cmd`.
4. Drag the Round 8 A listening winner onto `round9_lab.cmd`.
5. Open the generated `PDRM_v0_6_Round9_HarmonicLoudness_BLIND.zip`.
6. Fix your listening rank before opening `REVEAL_AFTER_LISTENING.txt`.

The job folder contains candidate-level checkpoints.  A rerun reuses a completed
candidate only when its recorded SHA-256 still matches the file on disk.
