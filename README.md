# LocalScribe — developer branch, not a product release

The legacy application source on this branch is incomplete. Do not build or distribute the old GUI as a finished product.

## Active work: reusable engine on a Windows developer VM

The workflow installs vendor wheels with standard pip and uses `localscribe/core/whisper_engine.py` to transcribe a fixed public Japanese fixture. The core has no installer, network client, recording, credential access, self-update, or device fallback. The old custom common/network/install modules are not registered or imported. They have not been resubmitted through another mechanism.

## Observed results and design decision

- Run 33962634509: official-API CPU inference and Markdown round-trip passed under OpenVINO 2026.0.0. The pinned model card declares 2026.1.0 minimum, so this is historical evidence, not the supported release baseline.
- Run 33962981894: with the declared 2026.1.0 runtime, two uncached CPU calls passed. Passing CACHE_DIR during a subsequent pipeline construction failed with `Unsupported attribute type for serialization: inputs`. The entire experimental workflow correctly remained failed. This does not prove the root cause of another machine's historical error.
- The new reusable core therefore does not permit CPU disk compilation caching. This is an explicit removal of an optional optimization, not a claim that the failing cached path was repaired. The model remains resident during repeated calls.
- The active workflow now checks real core calls, reconstruction in the same process, transcript consistency, Markdown round-trip and rejection of invalid inputs. New-process/package/GUI/NPU acceptance remains outstanding regardless of its outcome.

Runtime/GenAI/Tokenizers are pinned to 2026.1.0/2026.1.0.0/2026.1.0.0. Exact resolved dependencies and wheel hashes are preserved by pip's install report. Before product packaging, hashes must become enforced inputs, not only recorded outputs.

## Privacy and operation boundaries

Only a fixed public fixture and fixed vendor model are downloaded into an ephemeral Windows VM. No private audio, conversations, diagnostics, user transcripts, company data, microphones, or loopback capture are used. Model/audio/transcript files are not published as artifacts. Only bounded technical evidence is uploaded. No security-setting modification, paid runner, release, or automatic merge is used. Workflow permissions are read-only and checkout credentials are not persisted.

## Fixture attribution

- `japanese-asr/ja_asr.jsut_basic5000`, revision `278db379fc96167ff2293d7abf9ab86976afcd78`, `sample.flac`.
- Ryosuke Sonobe, Shinnosuke Takamichi and Hiroshi Saruwatari, *JSUT corpus: free large-scale Japanese speech corpus for end-to-end speech synthesis*, 2017, arXiv:1711.00354.
- Terms: https://sites.google.com/site/shinnosuketakamichi/publication/jsut
- Personal, noncommercial developer testing only. Corpus rights are separate from the application MIT license.

## Before a user trial

The packaged executable, GUI, offline runtime, persistence, failures and interruption must pass developer-side Windows integration first. Only then may target-machine NPU-specific acceptance be requested. CPU success is not NPU or real-time success. A single public sample is not a general accuracy benchmark.

`main`, unrelated branches, repository permissions, paid-runner settings, secrets and releases are unchanged. Do not merge this draft PR.
