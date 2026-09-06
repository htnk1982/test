# OPPO v3.2 — 実曲失敗の構造修正と作業領域クリーンアップ

日付: 2026-09-06
実装・配布検証commit: `a0f14ebd80598c07cd759474bca9ef17ffa9aad5`
GitHub Actions: `34023965688` / success
状態: V3_2_BUILT_AND_MACHINE_VERIFIED / FIELD_25_TRACK_RETEST_PENDING

## 実曲で確認したv3.1の反例

利用者PCのバッチ実行で `01 - くしゃみ.wav` が、旧42.67msソルバーのpointwise budget不成立後、v3.1 Rescueでも次で停止した。

`Rescue local naturalness gate failed: {'residual': False, 'energy': False}; ... window 1.557s to 1.600s`

この観測を「許容値が厳しすぎる」とだけ解釈せず、短い窓の内部だけで修正を完結させようとした表現上の限界と判断した。v3.1の局所自然さゲートを緩めて通す変更は採用しない。

## v3.2

- 選好済みv0.1ソルバーが成立する窓は従来計算を維持する。
- v0.1が正確にpointwise residual budget不足となる窓だけを、全曲仮出力の後に長文脈Rescueへ送る。
- 文脈は128/256/512/1024msを有限に試す。
- ピーク上限へ必要な最小修正を置いた後、失われた短時間エネルギーを、ピーク余裕のある前後の**元波形そのもの**へ小さい正ゲインとして再配置する。
- 文脈ごとに差分RMS、エネルギー、20ms包絡P95/最大、M/Sを検査する。全曲の既存engineering gatesも保持する。
- 4x格子で成立後、native rateへ戻して再補間したTPが再上昇した場合、処理済み候補をclipせず、同じ参照から内部ceilingを下げて有限回再最適化する。
- 通常limiter、clipper、目標LUFSの自動引下げ、旧前段への自動fallbackは使用しない。

## 永続化修正

`contexts_ms` がPythonではtuple、JSON復元後はlistになり、値が同一でもchunk identity比較がfalseになる欠陥を修正した。設定をJSON正準形へ変換し、途中中断後に確定済みchunkを実際に再利用する回帰を通した。

## SSD容量

v3.2は曲単位でwork lifecycleを閉じる。

- 公開成功: `processed` の同名WAV/MP3とreceiptを検査後、その曲の大容量中間音声・chunk・codec検査音を削除。
- 通常失敗: 大容量中間WAV/MP3を削除し、小さい診断JSONだけ保持。
- 強制中断: 同じv3.2の未完了jobはresume用に保持。
- v3.2で曲を選んだprestart時: 同じsource hashに紐づく旧 `oppo_finish_v3` / `oppo_finish_v31` workを回収。無関係な他曲は削除しない。
- 元音源、source側`processed`、手動編集物はcleanup対象外。

## 検証

run 34023965688はsource job、Windows jobともsuccess。

- Ubuntu source regressions: 244件 PASS
- Windows Server 2022 / Python 3.12: 244件 PASS
- PyInstaller x64 build: success
- isolated EXE smoke: success
- 44.1/48/96kHz、WAV/FLAC、日本語名、独立WAV/MP3 target: pass
- source/EXE output equivalence: pass
- successful track leaves no cached WAV/MP3 in OPPO v3.2 LOCALAPPDATA work root: pass
- failed track deletes large intermediate audio and retains compact diagnostic: pass
- cache deletion後のreceipt-based idempotent skip: pass
- old-feasible audio path sample identity: pass
- interrupted chunk reuse: pass
- matching v3.0/v3.1 source cache reclamation and unrelated-cache preservation: pass

配布ZIP: `PDRM_OPPO_EXE_Windows_x64_v3.2.0.zip`
SHA-256: `f5cb2a75e248d9589b72919e21963f50eeb25cdc6aebcfc4cdecda1a75728c09`

利用者の25曲本体はCIにないため、今回の修正で25曲全件が成立するとはまだ記録しない。次の実バッチが適用範囲を確定する識別観測である。
