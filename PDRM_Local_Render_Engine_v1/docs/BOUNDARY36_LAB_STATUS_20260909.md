# PDRM Boundary / Context / Observer LAB — 2026-09-09

Status: EXPERIMENTAL_IMPLEMENTATION, NOT_PRODUCTION_RELEASE.

## Implemented

- `lowend_boundary_lab.py`: original stereo-power features; whole-track constant-loudness anchor; empirical positive-reference bounds; bounded overlarge-hit rendering; explicit same-fundamental permission gate; candidate rendering and remeasurement.
- `context_occupancy_lab.py`: 12-second windows on a 10-ms grid, 4-second step, fixed original evaluation spans; local occupancy excess planning and bounded rendering. These are analysis windows, NOT automatically recognized musical phrases.
- `stem_observer_lab.py`: actual local Hybrid Demucs research inference, explicit checkpoint hash, no per-stem normalization, no stem waveform in the audible output; source estimates reported as uncertain observations, not probabilities.
- 44 new synthetic contract tests; Ubuntu and Windows CI. Prior production HE/HFTC/OPPO and publishing files are checked unchanged against `cbefe937d9cfc41de42fce0729b96871c65e59de`.

The observer checkpoint was evaluated on eight bounded user-provided audio contexts locally. No music, original review workbook, private comments, separated audio, or reference atlas was uploaded to GitHub. CI contains synthetic contract tests only, not neural inference or listening tests.

## Results and limitations

Reference-boundary experiments use nine role-explicit positive examples, including positive roles in otherwise negative tracks. Null processing is possible without filename whitelists. Initial floor-only reasoning produced a leave-one-track-out false intervention and was revised. The revised nine-track internal checks are NOT independent generalization evidence because the repertoire and failures informed design.

An overlarge-hit candidate measurably reduced its pressure statistic. Three local-occupancy candidates measurably reduced their fixed-source-window excess statistic. All remained within the bounded 2-dB branch attenuation limit, but did NOT fully meet the provisional numerical goal; the recorded status is PARTIAL_BUDGET_LIMITED. This does not establish perceptual improvement.

Narrow-band unpleasant persistence remains unresolved. No mean-spectrum match, universal genre-independent floor threshold, global SDR-to-musical-quality inference, or fully trained taste model is claimed. The octave permission gate is implemented and tested but is not yet integrated with a new production sub renderer.

## Preserved boundaries

- No HE/HFTC/OPPO DSP redesign.
- No production EXE update or new user installation requirement.
- No replacement of the original mix by separated stems.
- No speed project or checkpoint bundled for production distribution.
- No claim that all uploaded music was source-separated: eight 8-second cores with surrounding context only.
- No source-wide quality certification from new contract tests.
- No reinterpretation of blank reviews as positive labels.

## Research model deployment boundary

The evaluated checkpoint is TorchAudio HDEMUCS_HIGH_MUSDB, a Hybrid Demucs baseline, not a declared best-performing current model. Torchaudio code is BSD-licensed; code licensing is not taken as sufficient evidence of unrestricted checkpoint deployment. The upstream Demucs author states scientific-purpose restrictions for pretrained weights in issue 327. Research testing is distinct from approval to include this checkpoint in a distributed application.

Primary sources:
- https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.HDEMUCS_HIGH_MUSDB.html
- https://github.com/facebookresearch/demucs/issues/327#issuecomment-1134828611

## Next acceptance gates

Role attribution and narrow-band diagnosis must be improved before wider low-mid actuation. Validate a source-rest rejection on actual isolated evidence, preserve explicit positive examples, and inspect final mastering interactions. Do not present the current partial candidates as approved masters, or request a repeat full-corpus listening evaluation as a substitute for implementation work.
