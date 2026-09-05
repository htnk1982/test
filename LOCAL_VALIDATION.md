# Authoring-environment validation — 2026-09-05

Environment: Linux, LLVM cross-compiler, Python. No Windows kernel, Intel NPU or actual OpenVINO/Whisper inference was used in this validation.

Performed:

- Built the native x64 host from the candidate's source. Verified the embedded manifest against the validated source bytes.
- Ran the retained tests plus internal fault/transaction/gate-judge tests: 168 passed; 2 Windows-specific file-sharing tests skipped on Linux.
- Parsed the workflow YAML; checked fixed action revisions, explicit Windows runner, read-only token, same-repository branch restriction, bounded timeout and evidence-only artifact path.
- Compiled all Python source files for syntax checks. Checked source-package exclusions.

Not performed:

- Upload of this source package to GitHub, workflow registration, Windows job execution or successful actual model inference.
- Target NPU inference, live two-source capture, Wisp comparison, product acceptance or end-user release.

The Windows gate treats any skip in its mandatory suite as failure. The Linux test count is not a substitute for that gate. No new end-user EXE is included in this source package.

Internal changes after v0.2.3 include audited result validation/primary-error retention; a journaled runtime switch that preserves the old library directory until explicit post-inference commit; and separate developer automation/evidence judgment. Those changes have not been declared fixes for the historical CPU/NPU RuntimeError, whose original exception text was not retained.
