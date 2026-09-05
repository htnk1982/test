# LocalScribe — Developer Windows Gate

## Publication status

**INCOMPLETE SOURCE SNAPSHOT — DO NOT RUN OR RELEASE.**

This isolated development branch contains only part of the prepared source package. Publication of the remaining application modules and tests was blocked by the publishing connection's safety check. No workaround has been applied.

The workflow definition is present, but no pull request has been opened and no Windows integration test has been started for this incomplete snapshot. A workflow file existing in the repository is not evidence of successful execution.

The branch starts from the unchanged main commit `8fb85fb83b740fbb8ebf2a32d146feb9af67437e`. The original file `1` is preserved. No other branches, repository settings, billing settings, secrets, releases or permissions have been changed.

Only developer source and documentation are included. There are no user recordings, transcripts, conversation contents, original device reports or original error logs. There are no model weights, runtime binaries or executable application files.

## Required before running the Windows gate

Complete the source publication through an authorized connection, verify the source snapshot against its publication manifest, then open the planned same-repository draft pull request. Do not start a run against the incomplete snapshot or substitute an end-user machine for development integration testing.

The planned gate uses a standard `windows-2022` runner, a read-only workflow token, exact action revisions, no persisted checkout credentials and a 45-minute job limit. It is restricted to same-repository `localscribe/` pull requests. It does not merge the branch or publish a product release.

Even a successful future CPU integration run would not establish NPU compatibility, real-time two-source audio performance, general Japanese transcription accuracy or product readiness. Those remain separate acceptance conditions.

`LOCAL_VALIDATION.md` is a historical record of the complete prepared package's local validation, not proof that this partial public snapshot is executable.
