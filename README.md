# LocalScribe — developer branch, not a product release

This branch is incomplete application source. Do not run the old GUI or build it as a finished product.

## Active experiment: official-API CPU reference

The workflow now executes only `localscribe/ci/reference_gate.py` using standard pip-installed vendor wheels. It does not import the application's custom common/network/install modules. Those modules are not registered here and are not being resubmitted. The change reduces the test's capabilities and scope; it is not an alternative transport for the old installer.

One fixed public Japanese fixture and one fixed OpenVINO Whisper snapshot are read in an ephemeral Windows developer VM. There is no microphone/loopback access, personal file access, credential loading, arbitrary remote code, security-setting modification, package self-update, automatic device fallback, release creation, or push from the workflow. The workflow token is read-only and is not persisted by checkout.

A reference pass means only vendor API -> CPU inference -> local Markdown succeeded for this fixture. It does NOT mean the app installer, portable executable, GUI, NPU, two-stream live transcription, or accuracy/performance requirements passed. The existing Windows application gate is deferred, not marked passed.

## Fixture attribution and limits

- Dataset: `japanese-asr/ja_asr.jsut_basic5000`, revision `278db379fc96167ff2293d7abf9ab86976afcd78`, `sample.flac`.
- Ryosuke Sonobe, Shinnosuke Takamichi and Hiroshi Saruwatari, *JSUT corpus: free large-scale Japanese speech corpus for end-to-end speech synthesis*, 2017, arXiv:1711.00354.
- Terms: https://sites.google.com/site/shinnosuketakamichi/publication/jsut
- Limited to personal, noncommercial developer testing. Audio and generated transcript content are not committed or uploaded as artifacts. Text/corpus rights are separate from the application MIT license.

## Completion required before a user trial

1. Reference success with recorded versions, model/fixture hashes and a real nonempty result.
2. Windows application integration including GUI, packaged runtime and Markdown persistence.
3. Error preservation, interruption, rollback, file sharing and transcript validation.
4. Only then target-machine NPU-specific acceptance, with bounded time and useful evidence.

`main`, unrelated branches, repository permissions, paid-runner settings, secrets and releases are not changed. This branch must not be auto-merged.
