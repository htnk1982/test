# PDRM v1.0.0 保守運用引継ぎ・詳細設計仕様

更新: 2026-09-15  
対象: **PDRM Release v1.0.0**  
状態: **RELEASE ACCEPTED / MAINTENANCE BASELINE**

---

## 0. この文書の目的

この文書は、PDRM v1.0.0 を今後改修・保守するときに、過去の会話や開発経緯を再現しなくても、**受入済み製品の構造、設計意図、変更禁止境界、ビルド方法、障害解析方法を復元できること**を目的とする。

今後の機能改修では、原則として以下をセットでAI/開発者へ渡す。

1. この `MAINTENANCE_HANDOFF_v1.0.0.md`
2. `AI_RESTART_PROMPT_v1.0.0.md`
3. `RELEASE_BOARD.md`
4. release branch `pdrm-release-v1.0.0` のソース一式
5. 問題再現時は `PDRM_DIAGNOSTIC.zip`

### 受入済み基準版

- release source commit: `f7bc80c35fad8216f52c443e4995f630b4f35619`
- frozen build run: `34740096874`
- accepted artifact ID: `10311564114`
- artifact ZIP SHA256: `7d44afdb6e5b24cbc4532748788e4bf7ca100f1a09c4e17f7857601755a40c35`
- release branch: `pdrm-release-v1.0.0`
- planner: `automatic-joint-lab-0.4.0`
- renderer: `joint-v46`
- finalizer: `auto-peak-v3.4.0`
- observer provider: `spleeter_runtime48`
- observer runtime manifest SHA256: `97189055de8486501cad720562e467af5c97129ce9bfa1dab91813866c6e1d0c`
- product calibration SHA256: `b2c094d02e6da731c9953ea65f7d2c4fcba7b31b588b6049af86aa0e2d97399f`
- historical P01 accepted calibration SHA256: `0e258cf233e07e664f7eb56d5e161c20b270211a322282af88efa494993279e1`
- canonical reference.zip SHA256: `82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a`

本人Windows PCで通常GUI経路の実曲処理を完走し、本人最終聴感「音も問題なし」で受入済み。

---

# 1. 製品としての要求仕様

## 1.1 ユーザー価値

PDRMは、WAV/FLACの2mixに対し、既存の音像を壊さず、必要性が証明できる場合だけ低域を作用させ、最終ラウドネス・True Peak・MP3 codec QCまで一貫して処理するWindowsローカルアプリである。

最上位の音響設計原則は次の2点。

> **嫌な音を増やさず、知覚的に安全な余白を使って大きくする。**

> **作用することより、必要性に応じて作用しないことも含む選択性を正解とする。**

## 1.2 v1.0.0 の標準出力条件

| 出力 | LUFS-I default | True Peak default |
|---|---:|---:|
| WAV | -10.0 LUFS-I | -0.5 dBTP |
| MP3 | -14.0 LUFS-I | -1.0 dBTP |

- LUFS設定範囲: `-30.0` ～ `-8.0`
- LUFS刻み: `0.5 dB`
- TP設定範囲: `-12.0` ～ `-0.5 dBTP`
- TP刻み: `0.5 dB`
- TP上限: `-0.5 dBTP`

実装: `target_settings.py`

## 1.3 入出力

入力:
- WAV
- FLAC
- 1～1000ファイルのbatch

出力:
- 元音源と同じフォルダ直下の `processed/`
- 同名 `.wav`
- 同名 `.mp3`
- `.pdrm/` 内のreceipt / integration evidence

禁止:
- 元音源上書き
- stem音声の完成音への混入
- runtime中のモデルdownload
- user側Python/TensorFlow/Spleeter導入
- integrity errorを音響fallbackで隠すこと

---

# 2. 全体アーキテクチャ

```text
[PDRM.exe GUI process]
    |
    | 1. source selection
    | 2. target selection
    | 3. precomputed calibration install/check
    | 4. sealed request.json
    v
[PDRM.exe worker process]
    |
    +--> accepted calibration cache
    |
    +--> AutomaticJointPlanner v51
    |       |
    |       +--> source analysis
    |       +--> relative-low assessment
    |       +--> same-f0 candidate assessment
    |       +--> only unresolved evidence -> Spleeter observer
    |
    +--> isolated Spleeter observer runtime
    |       CPython 3.11 + TensorFlow + Spleeter 4stems
    |       persistent worker per observer instance
    |       analysis evidence only
    |
    +--> joint-v46 renderer
    |
    +--> HFTC
    |
    +--> auto-peak-v3.4.0
    |       GAIN_ONLY -> OPPO -> LIMITER_FALLBACK only on NotFeasible
    |
    +--> MP3 encode -> decode -> QC
    |
    +--> P07 safe publisher / crash recovery
    v
[processed/*.wav + processed/*.mp3 + .pdrm evidence]
```

### プロセスを分離している理由

GUIスレッド上でDSPを実行しない。GUIはworkerを別プロセスとして起動し、`status.json` をprogress telemetryとして読む。

**重要:** `status.json` は処理の権威ではない。workerのprocess生存/終了とterminal statusが処理結果の権威である。

これはv1.0.0直前に本人PCで判明した重要な設計修正である。WindowsのAV/indexer/共有ロックにより `status.json` のreadが一瞬 `PermissionError` になっても、workerが生きている限りDSPを失敗扱いしてはならない。

---

# 3. GUI / Worker境界

## 3.1 GUI entry

`product_app_v52.py`

役割:
- source選択
- precomputed calibration準備
- target GUI呼出
- session directory生成
- sealed request生成
-同一 `PDRM.exe` を `--worker-manifest` で子process起動
- `worker.log` 捕捉
- progress window管理
- 成否dialog
- 異常時 `PDRM_DIAGNOSTIC.zip` 生成

app local root:

```text
%LOCALAPPDATA%/PDRM_Local_Render_Engine_v1/product_v54/
```

主なsessionファイル:

```text
sessions/<uuid>/
  request.json
  status.json
  worker.log
  product_summary.json
  PRODUCT_FAILURE.json          # Python exception時
  GUI_WORKER_EXIT.json          # abrupt worker exit時
  GUI_FINAL_STATE.json
  PDRM_DIAGNOSTIC.zip           # user共有用
```

診断ZIPにはユーザー音声を含めない。

## 3.2 sealed request

`product_gui_runtime_v52.py`

release v1.0.0:
- version: `product-gui-runtime-0.2.0`
- schema: `2`
- runtime id: `product_candidate_v53`

requestには以下を固定する。

- source absolute paths
- canonical reference identity
- calibration SHA
- 4 target values
- replace flag
- work root
- session directory
- request seal SHA256

通常製品経路は `ACCEPTED_CACHE` として、reference path自体を必要としない。canonical reference SHAだけをidentityとしてpinする。

## 3.3 progress telemetry

`gui_runtime_v44.py`

release version: `gui-runtime-v0.2.2`

### write

`atomic_json()`:
- temp file write
- flush/fsync
- `os.replace`
- Windows `PermissionError` は有限時間retry

### read

`read_status()`:
- `PermissionError`
- `FileNotFoundError`
- 書換途中の `JSONDecodeError`

のみ bounded retryする。

schema mismatch / manifest hash mismatchはretryで隠さずhard error。

`natural_gui_v44.py` はread failureをtelemetry failureとして扱い、worker processが生存中なら処理を継続する。worker終了後にのみterminal statusを長めに再取得し、それでも取れない場合にexit codeから障害化する。

この挙動は**変更禁止に近い保守上の重要契約**。

---

# 4. Reference Calibration設計

## 4.1 なぜユーザーPCでreference calibrationを行わないか

初期版はcanonical 24曲を毎回decode/scanし、重いreference calibrationを繰り返していた。製品v1.0.0ではこの設計を廃止。

開発側で24曲を事前計算し、**derived numerical metadataのみ製品へ同梱**する。

reference音源自体は製品に同梱しない。

## 4.2 実装

`accepted_calibration_cache_v53.py`

release version: `accepted-calibration-cache-0.2.0`

重要identity:

```text
EXPECTED_REFERENCE_ZIP_SHA256 = 82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a
EXPECTED_CALIBRATION_SHA256   = b2c094d02e6da731c9953ea65f7d2c4fcba7b31b588b6049af86aa0e2d97399f
P01_ACCEPTED_CALIBRATION_SHA256 = 0e258cf233e07e664f7eb56d5e161c20b270211a322282af88efa494993279e1
```

precomputed file:

`precomputed_calibration_v54.json`

install先:

```text
%LOCALAPPDATA%/PDRM_Local_Render_Engine_v1/accepted_calibration/<reference_sha>.json
```

cacheはseal付き。以下が一致しなければloadしない。

- schema/version
- planner version
- reference SHA
- calibration SHA
- derived metadata only flag
- seal SHA

### 変更時の原則

reference set・feature extractor・plannerが変わる場合、既存calibration SHAを都合よく書換えてはならない。

必ず:

1. calibrationを新規生成
2. 旧版との差分を説明
3. 実曲回帰
4. 新identityへversion up

とする。

---

# 5. 音響Planner詳細

## 5.1 主planner

`automatic_joint_v51.py`

version:

`automatic-joint-lab-0.4.0`

v51の本質は**v50の音響gateを変えず、最終判断を反転できないSpleeter呼出だけを削除したこと**。

### 削除するobserver call

1. v48 legacy base observer stage
2. relative-low scoreが改善不能 (`<= 0.05 dB`) のwindow
3. source-only vetoですでにsame-f0追加拒否が確定する候補

### 変えてはいけないもの

accepted additionは依然として:
- source fundamental proof
- source brightness veto
- role/pitch evidence
- physical fundamental条件
- peak条件
- 数量/overlap条件

を通過する必要がある。

### assessment

代表state:
- `KEEP_SUPPORTED`
- `CANDIDATE`
- `PARTIAL`
- `ABSTAIN`

`ABSTAIN` / `0 additions` は失敗ではない。

## 5.2 実曲受入の意味

受入3曲は役割が異なる。

- 11: 必要なsame-f0補強を1件だけ通す
- 06: 境界候補はあるが0件、ABSTAIN
- 12: 候補多数でもsource-onlyで拒否、observer 0回、ABSTAIN

したがって将来改修で「何か処理をする率」をKPIにしてはいけない。

KPIは**必要性に対する選択性**。

---

# 6. Spleeter Observer Runtime

## 6.1 分離理由

main mastering executableはPython 3.12系。Spleeter/TensorFlow依存はisolated CPython 3.11 runtimeとして sibling directoryに置く。

```text
PDRM_Windows/
  PDRM.exe
  PDRM_OBSERVER_RUNTIME/
    python.exe
    ... TensorFlow/Spleeter packages
    models/4stems/
```

## 6.2 adapter

`spleeter_observer_adapter_v48.py`

provider:

`spleeter_runtime48`

重要原則:
- TensorFlowをmain processへimportしない
- stem sampleをmain processへ渡さない
- role observer schemaの数値証拠だけ返す
- persistent workerを使い、windowごとのモデル再初期化を避ける
- runtime/model/preprocessing identityを毎job固定

model asset SHA:

`3adb4a50ad4eb18c7c4d65fcf4cf2367a07d48408a5eb7d03cd20067429dfaa8`

## 6.3 preprocessing contract

変更時はrecalibration対象。

release v1.0.0 contract:
- separator rate: 44100 Hz
- feature rate: 12000 Hz
- hop: 120 samples
- window: 720 samples
- bands:
  - low 25–120 Hz
  - body 120–300 Hz
  - focus 300–450 Hz
  - upper_focus 450–700 Hz
- contexts required: 2
- max core: 16 s
- max pad: 4 s

runtime model downloadは禁止。

---

# 7. DSP / Render chain

`integrated_finish_v40.py`

論理chain:

```text
HE
 -> AUTO_PREP (-14 LUFS / -2.5 dBTP internal anchor)
 -> NEW_LOWEND_COORDINATOR (joint-v46)
 -> HFTC
 -> AUTO_MASTER (user WAV target)
 -> CODEC_QC (user MP3 target)
```

## 7.1 renderer registry

固定registry方式。任意module名をplanからimportしない。

release renderer:

`joint-v46`

関連:
- `joint_lowend_v46.py`
- `physical_add_bridge_v46.py`
- `physical_add_bridge_v50.py`
- `same_f0_permission_v50.py`
- `event_groove_v37.py`

## 7.2 HFTC

`hf_temporal_contrast_lab.py`

低域処理後、最終master前の高域時間コントラスト処理。

ここを変更する場合、低域plannerとは別問題として扱うこと。音質差の原因を混ぜない。

---

# 8. Final Peak / Loudness policy

`auto_peak_v34.py`

version:

`auto-peak-v3.4.0`

固定policy:

```text
GAIN_ONLY
 -> OPPO
 -> LIMITER_FALLBACK only when OPPO raises NotFeasible
```

### 重要

limiter fallbackを使ってよいのは**音響的NotFeasible**だけ。

以下はfallback禁止:
- I/O error
- integrity mismatch
- missing dependency
- invalid receipt
- source modification
- codec error

これらをlimiterで「完成扱い」にしてはならない。

### technical gate

WAV:
- LUFS target ±0.03
- TP ceiling以下
- frames / sample rate / channels一致

MP3:
- 320 kbps encode
- decode後にLUFS/TP再測定
- geometry確認
- bounded retry最大6pass
- master hashはcodec branchで不変

---

# 9. Safe Publication / Recovery

## 9.1 product publication wrapper

`product_processed_v52.py`

P07で受入したsafe publisher/recovery/capacity modelを再利用し、rendererだけaccepted `joint-v46` に固定する。

## 9.2 processed integration

`processed_integration.py`

主な安全契約:
- work rootを元音源/processed folderから分離
- symlink/redirect拒否
- source hash固定
- request identity固定
- rerender差分がある場合は上書きせず停止
- publication evidenceと出力hash一致
- 最終cache cleanup確認
- disk capacity preflight

## 9.3 crash recovery

`crash_recovery_v43.py`

version:

`crash-recovery-v1.0.0`

owned workspaceにsealed `OWNER.json` を置く。

回収可能なのは:
- PDRM自身が作ったdirectory
- source/request identityが確認できる
- owner processが生きていない

ものだけ。

他source、他request、live owner、unverified directoryは削除禁止。

---

# 10. Idempotency / Provenance

PDRMは「同じファイル名があるから上書き」という設計ではない。

重要な保存物には以下を使う。

- source SHA256
- request SHA256
- planner identity
- calibration SHA
- module code hashes
- runtime manifest SHA
- output hashes
- receipt seal

再実行時、既存出力とidentityが一致すればidempotent skip可能な箇所がある。一致しなければ未知の既存物として停止する。

将来「便利だから自動上書き」に変更しないこと。PDRMの事故防止設計の核である。

---

# 11. GUI target settings

`target_settings.py`

release:
- `SETTINGS_SCHEMA=2`
- settings location:

```text
%LOCALAPPDATA%/PDRM_Local_Render_Engine_v1/gui_v2_2/settings.json
```

schemaが変わった場合、古い設定値を黙って解釈せず、新defaultへ戻しnoticeを出す。

---

# 12. Build / Distribution

## 12.1 main executable

build script:

`packaging/build_product_v52.py`

main frozen Python:
- Python 3.12

主要dependency:
- numpy 2.3.5
- scipy 1.17.0
- soundfile 0.13.1
- pyloudnorm 0.2.0
- imageio-ffmpeg 0.6.0
- psutil 7.0.0
- PyInstaller 6.16.0

TensorFlow/Spleeterはmain EXEへ入れない。

## 12.2 observer runtime

builder:

`packaging/build_spleeter_capsule_v47.py`

代表version:
- Python 3.11.9
- Spleeter 2.4.2
- TensorFlow 2.12.1
- NumPy 1.23.5
- SciPy 1.10.1
- SoundFile 0.12.1

application-local VC runtimeを同梱。

## 12.3 accepted CI workflow

`.github/workflows/pdrm-p08b-product-bundle.yml`

build-timeで確認するもの:
- isolated Spleeter runtime build/selftest
- GUI telemetry unit test
- Frozen main build
- generated-audio selftest
- precomputed calibration validation
- target contract
- source unchanged
- stem not in master
- artifact upload

### CI既知問題

artifactを別GitHub Windows runnerへ再downloadした後のFrozen main EXE `--self-test` は早期終了する既知事象が残っている。

ただし:
- build-time Frozen selftest PASS
- downloaded native Spleeter runtime selftest PASS
- 唯一の実利用者Windows PCの通常GUI実曲経路 PASS

のためv1.0.0ではnonblocking technical debt。

これを直す場合も、音響DSPと混ぜて変更しない。

---

# 13. 最低限維持すべきHard Invariants

今後の改修で、以下は明示的な再設計承認なしに壊してはならない。

1. 元音源を変更しない
2. stem音声をmasterへ混ぜない
3. runtime model downloadをしない
4. integrity errorを音響fallbackで隠さない
5. calibration/planner/runtime identityをseal/hashで固定する
6. `ABSTAIN` を失敗扱いしない
7. source-onlyで判断が確定した場合に不要なSpleeter inferenceを行わない
8. GUI telemetry errorをDSP failureにしない
9. workerが生存中なら進捗file一時lockで処理を止めない
10. safe publication前にsource/output hashを検証する
11. stale workspace cleanupで未確認directoryを削除しない
12. 同名output collisionをbatch開始前に拒否する
13. WAV/MP3 targetは保存後/codec decode後に実測検証する
14. arbitrary dynamic module importをplanから許可しない
15. user PCにPython/TensorFlow/Spleeterの別installを要求しない

---

# 14. 機能改修時の変更領域マップ

| 要望 | 主に触る場所 | 原則触らない場所 |
|---|---|---|
| LUFS/TP UI変更 | `target_settings.py`, `natural_gui_v34.py` | planner gate |
| progress表示改善 | `natural_gui_v44.py`, `gui_runtime_v44.py` | DSP chain |
| input format追加 | GUI/request/preflight + decode境界 | planner threshold |
| output naming変更 | `processed_finish.py`, publication layer | DSP |
| low-end判断改善 | `automatic_joint_v51.py` 後継 | final peak policy |
| same-f0 synthesis改善 | `joint_lowend_v46.py` / physical bridge | reference calibrationを無断流用しない |
| observer高速化 | adapter/client/runtime | v50/v51 acceptance gate |
| Spleeter更新 | observer runtime + recalibration + parity | 旧calibration identity |
| final loudness algorithm変更 | `auto_peak_v34.py` 後継 | planner |
| runtime容量削減 | capsule builder | model/dependencyを推測削除しない |
| crash recovery改善 | `crash_recovery_v43.py` | source/output safety |

---

# 15. 改修の標準手順

## Step 1: 基準版を固定

必ず `pdrm-release-v1.0.0` と比較する。

「今のmainが動くから」で基準を上書きしない。

## Step 2: 問いを1つに限定

例:

- 「GUI表示を変える」
- 「Spleeter起動を速くする」
- 「WAV TP選択範囲を変える」

同時に音響gateまで変更しない。

## Step 3: 影響領域を宣言

変更するmodule / 変更しないmodule / invariantsを先に書く。

## Step 4: synthetic/CI

まず機械的contractを確認。

ただしCI成功を音質合格に読み替えない。

## Step 5: 実機

唯一の利用者PCで通常GUI経路を確認。

## Step 6: 音に関わる変更だけ本人聴感

DSP/target/codecに影響がある場合のみ本人聴感をrelease gateにする。

## Step 7: 新release identity

受入したら:
- release branch/tag
- source commit
- artifact id/hash
- versioned handoff doc

を固定する。

---

# 16. Regression checklist

## 16.1 非音響改修でも必須

- [ ] PDRM.exe起動
- [ ] source選択
- [ ] target GUI表示
- [ ] reference.zip要求なし
- [ ] request seal valid
- [ ] worker process起動
- [ ] status temporary read failureでworkerを殺さない
- [ ] cancelが安全点で停止
- [ ] 元音源hash不変
- [ ] processed出力
- [ ] diagnostic zipに音声なし

## 16.2 音響改修時に追加

- [ ] planner identity更新が意図通り
- [ ] calibration identity扱いが明示されている
- [ ] 11相当: 必要な作用を通せる
- [ ] 06相当: 境界で止まれる
- [ ] 12相当: 不要なら完全ABSTAINできる
- [ ] stem audio in master=false
- [ ] WAV LUFS ±0.03
- [ ] WAV TP ceiling以下
- [ ] MP3 decode後LUFS/TP PASS
- [ ] source unchanged
- [ ] 本人聴感PASS

---

# 17. Known technical debt / 非blocking課題

## A. observer runtime容量

約1.93GB。削減余地あり。

ただし依存packageを「たぶん不要」で削除しない。削減candidateごとに:
- native import
- Separator initialization
- real inference
- role evidence parity

を確認する。

## B. GitHub artifact roundtrip後Frozen main selftest

別runnerでは早期終了することがある。native observer runtimeはPASS。

製品実機では正常動作済み。

## C. historical naming

ファイル名に `v52`, `v54` 等の開発途中versionが残るが、製品baselineはrelease branch/commit/hashで識別する。保守時に「番号が古いから」という理由だけでrenameしない。

---

# 18. Source inventory — 最重要ファイル

## Product shell
- `product_app_v52.py`
- `product_worker_v52.py`
- `product_gui_runtime_v52.py`
- `product_processed_v52.py`
- `product_selftest_v52.py`

## GUI / request / settings
- `natural_gui_v34.py`
- `natural_gui_v44.py`
- `gui_runtime_v44.py`
- `target_settings.py`

## Calibration / planning
- `accepted_calibration_cache_v53.py`
- `precomputed_calibration_v54.json`
- `automatic_joint_v51.py`
- `automatic_joint_v50.py`
- `automatic_joint_v49.py`
- `automatic_joint_v48.py`
- `relative_low_dominance_v49.py`
- `automatic_lowend_v41.py`
- `source_events_v41.py`
- `same_f0_permission_v50.py`

## Observer
- `spleeter_observer_adapter_v48.py`
- `observer_runtime_client_v47.py`
- `observer_worker_spleeter_v47.py`
- `packaging/build_spleeter_capsule_v47.py`

## Render / DSP
- `joint_lowend_v46.py`
- `joint_lowend_v42.py`
- `physical_add_bridge_v46.py`
- `physical_add_bridge_v50.py`
- `physical_decay_bridge_v42.py`
- `event_groove_v37.py`
- `hf_temporal_contrast_lab.py`
- `integrated_finish_v40.py`

## Final peak / codec
- `auto_peak_v34.py`
- `offline_peak_stream_v34.py`
- `offline_peak_stream_v32.py`
- `offline_peak_lab.py`
- `distribution_peak.py`
- `distribution_finish.py`

## Publication / recovery
- `processed_integration.py`
- `processed_finish.py`
- `crash_recovery_v43.py`
- `integration_contract_v40.py`

## Build / CI
- `packaging/build_product_v52.py`
- `.github/workflows/pdrm-p08b-product-bundle.yml`

### 原則

上記だけを抜粋して改修するより、**release branchの `PDRM_Local_Render_Engine_v1/` 一式を丸ごと共有することを推奨**する。間接依存・tests・過去互換moduleが多く、必要fileを人間が都度選別すると欠落しやすい。

---

# 19. 今後AIへ渡すときの最小セット

最短で文脈復元したい場合:

```text
1. PDRM_MAINTENANCE_HANDOFF_v1.0.0.zip
2. 追加したい要件を1文
3. 障害なら PDRM_DIAGNOSTIC.zip
```

AIへは最初に:

> release baselineを壊さず、変更範囲を限定し、受入済みinvariantsを維持して改修せよ。CI成功だけで音響DONEとせず、音に関わる差分だけ最後に本人聴感へ回せ。

と伝える。

詳細は `AI_RESTART_PROMPT_v1.0.0.md` をそのまま利用する。

---

# 20. v1.0.0を「完成」とみなす境界

v1.0.0は「理論上あらゆるWindows環境で完全に配布可能」と認定したものではない。

認定したのは:

- 唯一の利用者本人Windows PC
- release candidate artifact
- 通常GUI経路
- 実曲処理完走
- reference calibration不要
- WAV/MP3生成
- source safety
- 本人聴感PASS

である。

この境界を保守時にも維持し、未検証事項を既成事実化しないこと。

---

## 最終要約

PDRM v1.0.0の保守で守るべき核心は、DSPの個々のテクニックより次の構造にある。

> **音響判断の必要性を証拠化し、不要なら何もしない。処理・保存・配布の各境界ではidentityをsealし、音響失敗と運用失敗を混同しない。**

この構造を維持する限り、機能追加や高速化は局所変更として安全に進められる。
