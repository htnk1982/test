# PDRM Boundary37: spectral persistence and event connection

Date: 2026-09-09
Status: EXPERIMENTAL_IMPLEMENTATION / NOT_PRODUCTION_RELEASE / NO_LISTENING_APPROVAL
Parent: cf2b1a6ab8d10622559ea9d99f26756c804def35

## Implemented

- role_observer_v37.py: same 8-second audio core observed with two different amounts of surrounding context using the existing research Hybrid Demucs checkpoint. Output is power/pitch features, never separated sound. Agreement is not statistical independence or calibrated correctness.
- spectral_persistence_lab.py: twenty logarithmic bands, whole-track loudness anchor, explicit positive-reference envelope, sustained spectral-excess candidates, local observer evidence and vocal/onset protection, bounded original-mix differential rendering. No claim that spectral excess proves objectionable resonance.
- event_groove_v37.py: source identity, clock and coverage verification; local role/pitch permission connected to an actual same-fundamental differential renderer. Unknown internal portions of otherwise eligible events remain unmodified. Missing fundamental restoration and new octave generation are not implemented.
- tests/test_boundary37.py: 42 new contracts. Together with the previous boundary/observer 44, the workflow checks 86 contracts plus unchanged production core files. Neural inference and listening are not part of CI.

## Local audio experiments

This round analyzed 24 reference tracks and four existing before/after inputs at the feature level. Actual new neural inference covered three bounded 8-second cores, with two surrounding contexts per core: six forward passes. Neither private source audio, review comments, reference atlas nor checkpoint weights were uploaded with this commit.

One negative reference yielded an approximately 320-403 Hz intervention candidate. Local observer evidence mostly assigned the relevant non-vocal activity to other, not bass. Actuation was restricted to the observed core; the full track was rendered, with exactly zero waveform difference outside the observed interval before level matching. At a maximum 1.5-dB spectral mask, the designated band level decreased by about 0.63 dB on the fixed source-defined support. This is not proof of perceptual improvement or identification of the sole cause of the user's objection.

Both the baseline and candidate were passed through unchanged AUTO final level fitting at -12 LUFS / -2 dBTP. Both selected GAIN_ONLY. The local difference persisted, but this does not test active OPPO/limiter interactions or MP3 round-trip quality.

For the known sparse-outro false-sub event, the connected renderer returned an exactly zero addition. A counterfactual test falsely calling the source pitch 55 Hz still returned zero due to independent local observer-role/pitch evidence. A synthetic positive test produces a nonzero bounded same-fundamental candidate, preventing a permanent-bypass implementation from passing only the negative example.

## Reference boundary not passed

One explicit positive-reference full track produced exact no-op rendering. However, leave-one-track-out feature testing of the new spectral boundary flagged three of nine role-positive reference tracks. Missing observer coverage must not turn these cases into healthy KEEP approvals. The provisional spectral boundary is therefore NOT ready for default production use. Thresholds and filenames were not adjusted to hide these counterexamples. Previous hit/context results must not be attributed to this different boundary.

## Preserved and unresolved

HE, HFTC, OPPO, the corrected time-unit handling, production entry points, GUI, and existing EXE are unchanged. No speed optimization project was resumed.

Unresolved: local role-specific reference calibration; positive real-audio same-fundamental amount calibration; full-track event generation; active final-peak interactions; production checkpoint deployment and operational integration. The event amount ratios are explicit LAB limits, not reference-trained taste estimates.

Actual test completion is in the workflow's BOUNDARY37_TEST_RESULTS.json. Local measurements and diagnostic excerpts are retained on the conversation surface; they are not approved masters. Do not request a repeat full-corpus listening test as a substitute for resolving the three positive-reference counterexamples.
