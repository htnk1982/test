# PDRM Musical Role Controller v1 — Stem Observer / Groove-First Low End

Date: 2026-09-07
Status: DESIGN ONLY / PRODUCTION DSP UNCHANGED

## Decision

Low end will be redesigned around musical role and temporal contrast. Stem separation is used only as an ANALYSIS OBSERVER. Separated stems are never remixed into the published audio. Rendering always modifies the original two-mix physical path. Mid/high DSP kernels remain substantially unchanged; only timing/amount selection is wrapped in the same musical decision contract.

Reason: the observed failures are role/timing/amount errors, not an inability to synthesize or attenuate frequencies. A clean bass/drum observer helps distinguish bass-note events, kick events, sustain and valleys. But separator artifacts must never enter the master.

## Core invariant

A separator may provide evidence, but may not by itself authorize an audible change.

An audible low-end action requires agreement between:
1. mixture evidence from the original 2mix,
2. bass/drum stem evidence,
3. temporal continuity/section context,
4. post-render result gates.

If confidence is insufficient, action = KEEP.

## Parallel observation / physical render

SOURCE
├─ OBSERVER PATH (never published)
│  ├─ section / tempo / density / low-frequency spectral flux
│  ├─ bass stem estimate
│  ├─ drum stem estimate
│  ├─ bass note onset/offset/F0/envelope
│  ├─ kick onset/envelope
│  └─ role/confidence map
│
└─ PHYSICAL PATH
   ├─ HarmonicElasticity
   ├─ automatic preparation
   ├─ Musical Low-End Controller
   ├─ HFTC
   ├─ final AUTO peak processing
   └─ WAV/MP3

Role decisions are observed from SOURCE. Amount decisions are made against the actual physical-path waveform. This avoids letting OPPO/limiter artifacts teach the role detector while still sizing the change against the waveform that will actually be published.

## Observer model choice

Evaluate a BS-RoFormer-family separator first because it has strong published music-source-separation performance and explicit bass/drum stems. HTDemucs remains a practical comparison/fallback candidate. Model selection is NOT based on headline SDR alone.

PDRM acceptance metrics for the observer:
- bass onset precision/recall,
- bass offset error,
- false bass activity during exposed quiet passages,
- bass F0 consistency,
- kick onset precision,
- kick-vs-bass confusion,
- reconstruction/mixture consistency,
- agreement with mixture evidence.

The three known bad tracks plus known-good tracks are mandatory validation material. If a separator hallucinates a bass event, mixture-gating must prevent an audible action.

## Low-end state machine

For each musical event / short interval, classify:
- BASS_ATTACK
- BASS_BODY
- BASS_DECAY
- VALLEY
- KICK
- KICK_PLUS_BASS
- SUSTAINED_INTENTIONAL
- AMBIGUOUS

The controller never maps pitch detection directly to octave-down synthesis.

## Allowed actions

1. KEEP
2. SUB_ACCENT
   - reinforce an existing bass-note event only
   - envelope follows the observed bass event
   - never bridges a rest/valley
3. FUNDAMENTAL_REPAIR
   - only when the same bass F0 is supported and the fundamental itself is deficient relative to its harmonic family
   - octave-down invention is not equivalent to missing-fundamental repair
4. SUSTAIN_TRIM
   - preserve attack/body, attenuate excess tail
5. VALLEY_RESTORE
   - reduce low-frequency floor between confirmed events
6. RESONANCE_CONTROL
   - reduce an overlong narrow low-frequency resonance
7. HARMONIC_DEFINE
   - when deep bass is already sufficient but articulation/translation is weak, add/shape harmonics rather than more sub

Default action is KEEP.

## Hard prohibitions

- no octave-down synthesis from pitch detection alone
- no newly created sub event in a section without confirmed bass-role activity
- no generated sub through an observed rest/valley
- no action based only on a separated stem
- no section-average target that forces a quiet outro toward a dense chorus
- no candidate selection merely because LUFS/TP gates pass
- no largest-allowed amount first

## Groove objective

The primary low-end target is temporal contrast, not average LF level.

Observe per event/section:
- 50–100 Hz spectral flux
- event-to-valley contrast
- attack-to-sustain ratio
- decay time / decay cycles
- low-end duty cycle
- kick-bass overlap
- low-band crest factor
- 20–120 Hz vs 250–2000 Hz balance
- LF floor during valleys

A valid change should make bass events more legible while preserving or deepening the valleys. Increasing average LF energy without improving event/valley behavior is not an improvement.

## Rendering on the original 2mix

### Additive action

Generated reinforcement is an EVENT-SHAPED component, not a continuous sine-note track.

Envelope is derived from the confirmed bass event:
onset -> short body -> decay -> zero before the next valley.

Phase is selected against the physical-path 2mix to minimize peak cost and destructive interference. Duration may not exceed the confirmed bass event without explicit sustained-intent evidence.

### Subtractive action

Use a smooth time-frequency gain field on the original low band, guided by the observer. Preserve attack windows and attenuate only excess sustain/valley floor. Gain transitions must be slow relative to the local bass cycle to avoid modulation artifacts. The implementation may use complementary FIR/STFT reconstruction, but it must pass null/phase/edge tests and cannot introduce separated-stem audio.

## Reference profile

Reference masters are not used as one static EQ curve. Build robust distributions conditioned by section/state:
- event-to-valley contrast
- LF spectral flux
- attack/sustain ratio
- duty cycle
- decay timing
- kick/bass overlap
- LF/MF balance

Compare similar musical states (dense section to dense section, sparse outro to sparse outro). Targets are ranges/quantiles, not exact copied values.

Until a calibrated reference corpus exists, the system must not claim “top-engineer target matching”. It can still use conservative self-relative controls and hard prohibitions.

## Candidate selection

For each event/section, include DRY/KEEP as a candidate.

Selection order is lexicographic:
1. reject role/hallucination violations,
2. reject transient/stereo/phase/TP/LUFS violations,
3. reject candidates that raise valley LF floor without explicit musical intent,
4. prefer candidates that improve the relevant reference-range metrics,
5. among acceptable candidates choose the smallest audible intervention.

Do not use a fabricated single score to trade a serious musical failure against a small metric gain.

After candidate selection, evaluate again after HFTC and final AUTO peak processing. A pre-final improvement that becomes low-end-heavy after final processing is rejected.

## Known bad cases as mandatory tests

### 11 Traces
Observed failure: ~110 Hz detection caused ~55 Hz synthesis in a sparse outro. Expected state: AMBIGUOUS/non-bass or confirmed 110 Hz role without missing-fundamental permission. Required action: KEEP. Any new 55 Hz audible event is test failure.

### 08 微熱サーモグラフィ
Global LF heaviness is largely source-derived. Required behavior: do not add LF merely because a tonal event exists. If improvement is needed, prefer sustain/valley control or harmonic definition; preserve legitimate impact.

### 12 私=AI-MY
Late-song LF dominance is largely source-derived. Required behavior: do not flatten section intent, but if sustain/duty/floor exceeds the reference-conditioned range, preserve attacks while trimming tails/restoring valleys. No accumulating sub-addition.

## Mid/high policy

HFTC and current HarmonicElasticity are already close to the desired sound and are not redesigned wholesale.

Wrap existing kernels in the same controller pattern:
OBSERVE -> MUSICAL STATE -> CANDIDATE AMOUNTS INCLUDING DRY -> POST-RENDER CHECK -> LEAST CHANGE.

Initial production rule:
- current accepted amount is the maximum, not a minimum target;
- reduce/bypass in exposed sparse sections when the benefit is unsupported;
- preserve onset/decay timing;
- amount changes are smoothly interpolated at section/event boundaries;
- do not use stem-separated audio for mid/high rendering;
- do not increase current HFTC/HE strength until a reference-conditioned test shows a need.

This keeps the successful mid/high timbre while making the timing/amount logic consistent with the low-end philosophy.

## Validation gates before production integration

1. Observer benchmark on bad + good tracks.
2. Traces 55 Hz false-positive must be zero.
3. Positive cases where sub reinforcement is musically helpful must remain detectable; always-bypass is not a pass.
4. Compare before/after event-to-valley contrast and LF floor, not only integrated band energy.
5. Check intro/outro/rests, kick-only hits, bass-only passages, sustained pads, key changes, tempo changes.
6. Exact source protection and existing PDRM publication/cleanup guarantees remain.
7. Human listening remains final acceptance, but only after machine evidence shows the controller made the intended musical state transition.

## External technical grounding

- BS-RoFormer: Lu et al., Music Source Separation with Band-Split RoPE Transformer, arXiv:2309.02612; first in SDX23 MSS track.
- Mel-RoFormer: Wang et al., Mel-Band RoFormer for Music Source Separation, arXiv:2310.01809.
- Hybrid Transformer Demucs: Rouard, Massa, Défossez, ICASSP 2023 / Demucs v4.
- Groove literature repeatedly associates low-frequency spectral flux, rhythmic event structure and low-frequency timing with movement/groove; these support using temporal LF contrast as an analysis dimension, not as a guarantee of subjective quality.
