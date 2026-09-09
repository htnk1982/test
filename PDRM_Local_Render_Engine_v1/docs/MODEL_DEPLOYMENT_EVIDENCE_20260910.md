# Observer model deployment evidence — 2026-09-10

Status: PRIMARY-SOURCE REVIEW, NOT MODEL SELECTION OR RELEASE APPROVAL.

## Existing research baseline

The current LAB observer uses TorchAudio HDEMUCS_HIGH_MUSDB. The Demucs maintainer states in issue 327, comment 1134828611, that weights are not under the code MIT license and are provided for scientific purposes. Current experiments explicitly opt into research use. No model weights are bundled in PDRM output artifacts or a product EXE.

Source: https://github.com/facebookresearch/demucs/issues/327#issuecomment-1134828611

## Additional deployability candidate

The Spleeter authors' paper source explicitly states that BOTH the source code and pretrained models are distributed under MIT. The same paper describes the models as trained on Deezer's internal datasets and not trained/validated/optimized on MUSDB18. This is more specific evidence than inferring weight rights from a repository's code license alone.

Primary source: https://github.com/deezer/spleeter/blob/master/paper.md
Observed paper blob SHA: 290a7c6744e0bfeb71e1b8d82d4385434846bc4e
Paper: Romain Hennequin, Anis Khlif, Felix Voituret, Manuel Moussallam, 'Spleeter: a fast and efficient music source separation tool with pre-trained models', JOSS 2020, DOI 10.21105/joss.02154.

This does NOT establish that every later or third-party converted checkpoint shares the same terms. An exact official asset, corresponding notice/license, immutable weight hash and preprocessing/inference identity must be paired before inclusion. It does not establish legal rights in third-party input music or output distribution.

## Engineering decision

Spleeter is an additional candidate for a deployable analysis sensor, not an automatically accepted replacement for the current observer. Its bass onset, rest, vocal protection and narrow-band role evidence must be tested for this task. A source-separation benchmark or MIT statement does not prove musical suitability.

No Spleeter inference was executed in this change, no TensorFlow dependency was added, and no current DSP/model selection was modified. A 2020 claim of state of the art is not described as current state of the art. Any replacement requires its own role calibration and final-output regression; old observer calibration must not be silently reused.
