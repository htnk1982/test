# PDRM Groove-First Low-End Architecture v2

Date: 2026-09-07
Status: DESIGN_LOCK / DSP_NOT_IMPLEMENTED

## 0. User value

The target is not “more bass.” The target is low-frequency motion that participates in groove: present when musically useful, clearly withdrawn between events, and never a continuous boomy floor unless the performance itself intentionally sustains it.

## 1. Architecture decision

Use source separation as an ANALYSIS-ONLY semantic observer. Never reconstruct or publish audio by summing separated stems. All audible edits are applied to the original two-mix / accepted physical processing path.

Rationale:
- Two-mix-only pitch tracking cannot reliably distinguish a bass-note role from drums, pads, harmonics, or a missing-fundamental hypothesis.
- Separation artifacts are useful as uncertain semantic evidence but are unacceptable as replacement audio.
- The original mix remains the physical truth for level, phase, stereo, masking, true peak and final QC.

Initial observer interface must be model-agnostic. Candidate families: BS-RoFormer / Mel-band RoFormer and HTDemucs. Model selection is based on task-specific errors on the user's material, not global SDR alone: bass event onset/offset, f0 trajectory, false bass in sparse endings, kick leakage, and low-frequency attribution.

## 2. Parallel analysis graph

SOURCE 2MIX
├─ semantic observer (no audible output)
│  ├─ bass estimate
│  ├─ drums estimate
│  ├─ other/vocal estimates when useful for attribution
│  ├─ section map
│  ├─ bass note/event map
│  ├─ kick onset map
│  └─ confidence / disagreement map
└─ physical path
   HarmonicElasticity -> AUTO prep -> Groove Low-End Controller -> HFTC -> final AUTO/OPPO

Semantic analysis should be derived from the unmodified source (after only required resampling/level-neutral preparation). Amount decisions are re-measured on the physical signal after HE/AUTO preparation.

## 3. Preserve performance timing

Never quantize bass or kick events to a beat grid. Tempo/beat/downbeat estimates are context only. Actual detected onset, peak and release times are retained, including microtiming, anticipations and laid-back placement.

## 4. Low-end event state machine

Each bass-role event is represented as:
REST -> ATTACK -> BODY -> TAIL -> REST
or, when strongly supported by the performance,
REST -> ATTACK -> INTENTIONAL_SUSTAIN -> RELEASE -> REST.

Unknown/ambiguous regions never authorize synthesis.

Key measured descriptors:
- onset time and attack slope
- f0 and harmonic support
- 20-60, 60-120, 120-220 Hz energy
- event-to-valley contrast
- onset/body and body/tail ratios
- decay time
- low-frequency spectral flux
- low-frequency duty cycle
- inter-event valley floor
- kick/bass overlap and relative timing
- section density / sparse-ending context
- stereo coherence / source attribution

## 5. Role gate before amount

A detected periodic pitch is not permission to synthesize sub.

Authorization order:
1. Is there a credible bass-role event?
2. Is its start/end musically supported by bass-stem envelope and original-mix evidence?
3. Is the requested fundamental already present in the two-mix?
4. Is low-end addition actually needed after HE/AUTO prep?
5. Does addition improve temporal contrast / translation without raising valley floor or duty cycle excessively?

Default prohibition: do not create a new octave-below pitch merely because an f0 above the sub range was detected. Octave-down generation is arrangement-level behavior and is disabled in automatic mastering.

Missing-fundamental repair is a distinct, stricter operation. It requires consistent upper harmonics of the SAME inferred fundamental, bass-role confidence, and insufficient physical energy at that fundamental. If confidence is not high, choose KEEP or HARMONIC_DEFINE, not SYNTHESIZE.

## 6. Candidate actions

For each region choose from a null-inclusive action set:
- KEEP: no audible change
- SUB_ACCENT: short same-fundamental reinforcement following the source event envelope
- FUNDAMENTAL_REPAIR: conservative same-fundamental repair under strict evidence
- SUSTAIN_TRIM: reduce low-frequency body/tail while retaining attack
- VALLEY_RESTORE: reduce low-frequency floor between legitimate events
- RESONANCE_CONTROL: reduce narrow, persistent low-frequency resonance
- HARMONIC_DEFINE: improve bass audibility via harmonics rather than deeper sub

No action is preferred over a small but unjustified action.

## 7. Sub synthesis design

Generated reinforcement is not a continuous sine note spanning the whole tracked note.

Envelope is copied/derived from the bass-role performance:
- onset aligned to detected bass event, never beat-quantized
- fast enough attack to support the original event but no pre-onset energy
- body follows source envelope
- decay follows source decay and must return to the measured valley
- release completes before the next unrelated event unless intentional sustain is strongly supported

Phase is selected against the physical two-mix to avoid destructive interaction and peak inflation. Amount is computed from the mixed result, including cross-term / correlation, not by desired-minus-existing amplitude alone.

## 8. Dynamic reduction on original two-mix

Stem audio is not subtracted from the mix. Reduction is applied to the original two-mix using smooth stereo-linked low-band gain control, guided by the semantic map.

Preferred implementation: smooth, bounded dynamic-EQ / low-band mask on the original complex STFT or an exactly reconstructing complementary band structure. Preserve original phase as far as possible; do not resynthesize stems.

SUSTAIN_TRIM and VALLEY_RESTORE preserve attack and microtiming. They may reduce low-band tail/floor but may not create rhythmic gaps absent from the original performance.

## 9. Reference target: temporal profile, not a static curve

Reference masters are used as soft priors, not rigid matching targets.

Build a Reference Groove Atlas from accepted reference tracks / user-approved tracks. Compare similar section classes rather than whole-song averages. Store robust distributions of:
- event-to-valley contrast
- low-band duty cycle
- onset/body and body/tail ratios
- decay time
- 20-60 / 60-120 / 120-220 balance
- low-frequency spectral flux
- kick/bass overlap
- bass fundamental-to-harmonic balance
- section density and tempo context

Do not claim “top engineer target” until references have been explicitly selected and profiled. The original performance remains a stronger constraint than reference matching.

## 10. Candidate selection objective

Evaluate the rendered MIX, not the isolated added layer.

Choose the smallest audible intervention that moves the output into an acceptable region while preserving performance identity.

Primary objectives:
- preserve or improve event-to-valley contrast
- preserve onset timing / microtiming
- prevent duty-cycle and valley-floor inflation
- keep section-to-section low-end balance within reasonable reference/track context
- avoid TP / LUFS / stereo violations
- minimize waveform change and processing depth

Hard vetoes:
- new bass event in source-defined rest/ambiguous region
- octave-down synthesis without explicit repair evidence
- valley floor increases beyond allowed budget
- event duration extends beyond source support
- low-end dominance worsens when source is already excessive
- large phase/stereo disturbance
- operational/integrity error

## 11. HFTC and HarmonicElasticity: evolutionary, not revolutionary

HFTC is already close to the desired philosophy: strong/onset regions are protected while weaker HF regions may be attenuated. Keep its DSP and limits. Change only decision consistency:
- include explicit KEEP candidate
- choose the minimum depth that yields useful temporal contrast
- evaluate local section context and final rendered output
- share a global perceptual-change budget with low-end/harmonic processing

HarmonicElasticity: keep the accepted transfer as baseline. Do not increase its current maximum effect. Add a conservative track/section opportunity gate only if tests show clear benefit: reduce HE where the signal is already dense/rough/saturated, otherwise retain current amount. Avoid a large redesign unless counterexamples demonstrate need.

## 12. Confidence policy

Separation is evidence, not truth.

For additive synthesis require high confidence from multiple cues:
- separator bass attribution
- original-mix harmonic evidence
- stable event boundaries
- physical headroom / balance need

For ambiguous disagreement: KEEP.
For excessive low-end visible directly in the two-mix: bounded reduction may proceed with lower semantic confidence, but must preserve attacks and source-defined event structure.

## 13. Validation set and stop criteria

Do not iterate on one song at a time.

Required validation corpus:
- the three known failures: 08, 11 Traces, 12 AI-MY
- at least 5-10 user-approved processed tracks as positive controls
- synthetic edge cases: kick-only, bass-only, missing fundamental, sustained pad, bass solo, sparse outro, syncopated/anticipated bass, anti-phase/mono, silence

Acceptance is task-based:
- Traces-like false sub event rate = zero on known sparse-outro negatives
- no regression on positive controls judged useful by user
- event onset/offset alignment remains within analysis tolerance and no beat quantization
- low-end temporal contrast does not worsen without an explicit musical reason
- additive amount never selected merely because TP/LUFS allow it
- reference profile can suggest, never override hard performance evidence

The next implementation should therefore replace Note-Sub's event permission/amount controller while retaining the accepted surrounding chain. HFTC receives only small decision-layer changes. Production remains unchanged until this controller passes the mixed positive/negative corpus.