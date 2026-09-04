# PDRM Local Render Engine v1 — Core Rebuild / MVP-0

This is the rebuilt DSP core for **PDRM Local Render Engine v1**.

The surviving resilience runtime (`resilience r8.2`) is the outer execution shell.
This project restores the missing inner DSP entry point:

```python
pdrm_engine.engine.run_job(input_path, output_path, config, runtime_context)
```

## Definition

PDRM is an offline finalizer for reasonably finished stereo/mono 2mixes. It must
not reinterpret the artistic mix. It approaches a requested loudness / true-peak
profile only as far as preservation gates allow.

Priority is lexicographic:

1. valid output / no catastrophic defect
2. preserve musical relations
3. avoid audible artifacts
4. approach requested loudness / TP
5. minimize intervention complexity
6. codec/delivery robustness

**NO-OP is a valid successful solution.**

## MVP-0 — Universal Safety Shell

Implemented now:

- WAV input preflight
- integrated loudness / sample peak / chunked oversampled TP estimate
- PLR / crest / transient / spectrum / stereo / section-relation audit
- exact NO-OP when input is already suitable
- gain-only candidate
- conservative linked-channel offline baseline limiter
- Loudness–Distortion Frontier retreat when the requested target is unsafe
- preservation gates
- deterministic PCM dither/output
- exact post-write validation
- automatic rollback to NO-OP if a processed output fails outer validation
- mandatory `runtime_context`
- **Round 9 hard lock**

Not yet in MVP-0:

- Peak→Body Transport
- Small-Signal Density
- Harmonic Loudness / saturation
- spectral/surgical clipping
- HF acceleration control
- psychoacoustic multiband envelope search
- codec-in-loop QC

Those are intentionally held outside the safety core until the real runtime/core
integration tests pass.

## Runtime contract

`runtime_context` is mandatory and must expose either a mapping key or attribute:

```text
max_round_allowed <= 8
```

Optional callbacks:

```text
heartbeat(stage=..., progress=..., message=...)
is_cancelled() -> bool
```

The core rejects:

- `round9_enabled=true`
- `requested_round >= 9`
- runtime authority above round 8

Every result explicitly reports:

```json
{
  "round9_executed": false,
  "max_round_executed": 8,
  "runtime_context_ack": true
}
```

## CLI

After installation:

```bash
pdrm-render input.wav output.wav --target-lufs -9 --tp -2
```

For development:

```bash
python -m pdrm_engine.cli input.wav output.wav --target-lufs -9 --tp -2
```

## Tests

```bash
python -m unittest discover -s tests -v
```

The current CI runs on both Windows and Linux. Round 9 remains locked until the
real DSP core passes the acceptance sequence with actual audio and the surviving
r8.2 resilience shell.
