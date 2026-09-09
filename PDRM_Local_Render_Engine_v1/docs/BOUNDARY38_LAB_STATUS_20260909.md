# PDRM Boundary38 — Relative spectral boundary and per-band observation

Date: 2026-09-09
Status: EXPERIMENTAL_IMPLEMENTATION / NOT_PRODUCTION_RELEASE / NO_LISTENING_APPROVAL
Code commit: cfcab2043cccc46e4cfda4ade094fd1c5b8f04d5
Parent: 6509e836984425259b6ee631674c5075486c7f77

## Implemented scope

`relative_spectral_v38.py` replaces the previous same-frequency absolute-floor comparison with the 20th percentile of each band's level relative to the same-frame analysis-mixture power. The reference upper envelope admits a finite +/- two-bin neighbourhood, equivalent to +/- one third octave. This is an explicit nuisance tolerance, not detected pitch, harmonic equivalence, or a calibrated taste model. The renderer from Boundary37 is unchanged.

`role_observer_v38.py` measures the original mixture and four estimated roles on the same twenty spectral bands and 20-ms clock. This replaces reliance on one broad 300-450 Hz role ratio for every narrow candidate. It validates source identity, band order, units, coverage and checkpoint. Estimated audio is never used in the output. Voice-dominant, ambiguous, negligible-energy, unsupported and transient regions are protected.

The whole-track percentile screen targets recurring persistence. It can miss short isolated defects; the existing event-permission path is not replaced. KEEP, no supported persistence and observer abstention remain distinct. None certifies that an entire track is healthy.

## Real-data experiments

All 24 supplied reference source hashes were verified and the prior full-length features reused. Four fixed 8-second cores were observed twice with different surrounding context. Two additional neural passes verified exact feature equivalence between the reusable new observer and the standalone experiment. Total new neural passes: ten. No claim of full-track source separation or current-best model selection.

Nine bass-role-positive references were checked one-at-a-time out of calibration. Previous absolute-band screening proposed changes in three cases; the new relative screen proposed none of the nine. The three prior cases were also rendered at full length with supplied actual observers: exact zero PCM difference. This is development-corpus regression, NOT independent generalization. The corpus and earlier failures informed the design. A positive bass review does not imply that other roles in the same mixture are positive; the reference features are not clean bass stems.

Known Q=4 resonant transfer faults were injected into the same three full-length originals at 0/+3/+6/+9 dB. Every original had no candidate. All +6 and +9 dB cases were detected. One +3 dB case was missed: eight of nine altered cases had candidates. This is a sensitivity experiment, not human confirmation that every alteration is objectionable. The faulty copies were not given the unchanged source observer for rendering.

## Bounded candidate and final integration

The prior negative persistence case retained candidates at centres 320 and 359.19 Hz, with differential-mask support approximately 285-403 Hz. Operation was restricted to the observed 40-48 second interval. Thus the time coverage stayed fixed, but the frequency support expanded compared with the prior single-band candidate.

Strengths .25/.5/.75/1.0 were rendered. Mean dB changes on fixed source-defined time-frequency cells were -0.1931/-0.3848/-0.5751/-0.7640 dB. Strength .75 was the first to reach the predeclared diagnostic -0.5 dB change; this is not a taste-optimal amount. Maximum mask depth was 1.125 dB. The full-length rendering had exact zero difference outside the observed interval before final normalization. Local above-1-kHz residual was about -93.22 dB relative to local source RMS, not a proof of inaudibility.

Both baseline and candidate were passed through unchanged v3.4.1 AUTO and its codec branch, and saved WAV plus decoded MP3 were measured:

| Profile / variant | Actual master route | WAV LUFS-I | WAV TP estimate | Decoded MP3 LUFS-I | MP3 TP estimate |
|---|---|---:|---:|---:|---:|
| -12/-2 baseline | GAIN_ONLY | -12.000000 | -2.373608 | -14.001403 | -4.405242 |
| -12/-2 candidate | GAIN_ONLY | -12.000000 | -2.371969 | -14.001952 | -4.401236 |
| -10/-2 stress baseline | OPPO | -10.010755 | -2.013473 | -14.000079 | -5.817212 |
| -10/-2 stress candidate | OPPO | -10.010783 | -2.013464 | -14.000020 | -5.829150 |

The fixed-cell difference after full-track level matching was -0.57348 dB at the normal target and -0.56663 dB with actual OPPO activity. MP3 branches were gain-only. The stress target is a test condition, not a product-default change. Active limiter interactions and every target combination are not certified by this test. Outside-interval zero difference applies to the spectral stage alone, not to the whole nonlinear final mastering result.

## Tests and operating boundary

34 new plus 86 prior LAB contracts: 120 passed locally and in Ubuntu/Windows CI, run 34356677362. CI verifies seven existing production-core files unchanged. It does not perform neural inference, a subjective listening trial or an EXE build. It is not a re-run of every historical production test.

HE, HFTC, OPPO, corrected millisecond conversion, current EXE/GUI and application cleanup are unchanged. The completed experiment removed its own full-length intermediate work directory, retaining small evidence and diagnostic excerpts. No source files or previous user outputs were removed.

User audio, review text, reference atlas and model weights were not uploaded with these changes. The research checkpoint is not included in the deliverables or a product executable.

## Remaining limits

This is a conservative relative-spectral rule, not complete recognition of legitimate harmonics versus unwanted resonance. The small positive corpus is mixture-level and not fully role/timbre-conditioned. Mild injected changes and short isolated defects remain limitations. Same-fundamental amount calibration, whole-track observer scheduling and combined-controller product integration remain separate unresolved work. Do not declare subjective improvement from the attenuation statistic or demand a new full-corpus listening test to substitute for this missing work.
