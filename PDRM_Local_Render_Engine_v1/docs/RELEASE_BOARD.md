# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 7
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`
親Issue：#2。

## 現在地

**P01の技術ボトルネックは解消。Private Calibration Bundleは実在referenceと同じ「24本MP3 ZIP」経路までFrozen Windowsで受入済み。P01を閉じる残件は、ユーザーPC上で私有実曲11を1件実行し、manifest＋最小聴感を返すことだけ。**

現在のクリティカルパスは **P01実曲11 → P03/P04実曲校正 → P05完成WAV/MP3候補選択 → P08最終Windows EXE**。ChatGPT側Transport復旧は依存条件から除去した。

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **READY FOR LOCAL RUN #3** | bundleで`11 - Traces`を1件実行し、`CALIBRATION_MANIFEST.json`＋最小聴感を回収 |
| P02 配布用observer | **DONE #8** | 製品EXEの容量最適化はP08 |
| P03 発音・役割・必要量の自動判断 | **PARTIAL：P03-A DONE #10 / 実曲待ち** | 11→06→12で量・発動タイミングを校正 |
| P04 加算・広域/狭帯域統合 | **PARTIAL：P04-A DONE #9 + P03-A接続DONE** | 私有実曲で共同予算・聴感を確認 |
| P05 完成WAV/MP3での候補選択・実曲回帰 | WAITING | P01/P03後。OPPO/limiter後を含め判定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release解禁はP03/P08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7完了 |
| P08 製品Windows EXEと最終受入 | WAITING | runtime圧縮、実曲、GUI、保存、版/hash固定EXEを完走 |

## P01：問いを変えてボトルネックを解いた

### 旧い問い
「ChatGPT側ローカル実行の`TransportTimeoutError`をどう直すか」。

これは手段を目的化していた。P01に本当に必要なのは、**確定P03-Aを私有音源を外へ出さずユーザーPCで動かし、版・hash・planner判断・完成音・聴感を回収すること**。

### 新しい成立条件
公開CIはコード＋runtimeだけを生成し、私有source/referenceはユーザーPCでのみ読む自己完結Windows bundleとした。

- 主処理：PyInstaller Frozen EXE、ユーザーPython不要
- observer：内蔵CPython3.11.9 + Spleeter2.4.2 + TensorFlow2.12.1の別process
- accepted P03-A baseline：`50a4592e45b3f810e905041c25cff1c3e35b2a88`
- source：WAV/FLAC、元ファイル非破壊
- output：sourceフォルダ外のみ、既存結果上書き禁止
- private audio upload pathなし
- stem音声を保存・master混入しない
- 成功時：MASTER.wav / 320kbps MP3 / `CALIBRATION_MANIFEST.json` / REVIEW.md
- 失敗時：音声不要、`P01_FAILURE.json`だけで次の診断へ進める

## プレモーテムで発見したreference形式の穴

revision 6では`reference.zip`経路を自己試験したが、中身は生成WAVだった。実在canonical `reference.zip`は**24本のMP3**。一方、現行`integration_contract_v40.capture()`は校正入力にlossless WAV/FLACを要求する。

実物と同型のMP3 fixtureへ置き換えたrun `34682751245`で、`ValueError: Integration input requires lossless WAV/FLAC`を検出。**global契約をMP3許可へ緩める案は採用しなかった。**

### 解決：P01専用compatibility boundary

`canonical reference.zip (24 MP3)`
→ ユーザーPCの一時領域だけでffmpeg `pcm_f32le` WAVへデコード
→ 既存lossless校正契約へ入力
→ 終了時にdecoded WAVを削除。

保持するものはhash/provenanceだけ。

- global lossless contract relaxed：**false**
- decoded reference audio persisted：**false**
- original MP3 SHA / decoded WAV file SHA / decoded PCM SHAをローカルmanifestへ記録
- canonical archive SHA256：`82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a`
- 24本MP3以外、またはarchive hash不一致は開始前に拒否
- `before.zip` / `after.zip`の誤選択も拒否

実際の私有canonical archiveについても、公開CIとは別の私有環境で24/24本を同じ変換へ通し、全て44.1kHz stereo・decoded PCM 24本独立を確認した。音声は公開GitHub/CIへ送っていない。

## 最終P01 Frozen受入

final HEAD：`6d1d57ad36a9a0efb4e3f3be4186282c12f605d4`

主要commit：
- `03566971f3529be412b1689e8c57fb86447e4c2b` — failure evidence / MP3 premise試験
- `d74d40196a59788b6b81ba89803c2659b88c9742` — MP3→temporary lossless compatibility boundary
- `59434e91e13240af24638932d4cfd265907181a2` — bootstrapをFrozen EXE入口へ接続
- `6d1d57ad36a9a0efb4e3f3be4186282c12f605d4` — bootstrap変更をbundle CI triggerへ追加

最終CI：run `34683190838` / Windows job `103525468186` **SUCCESS**。

自己試験は実物と同じ構造の24本MP3 ZIPを生成し、

`MP3 ZIP → temp pcm_f32le WAV → calibration → isolated real Spleeter → P03-A → MASTER.wav / MP3`

をFrozen EXEから完走。

受入値：
- frozen = true
- source unchanged = true
- reference ZIP exercised = true
- reference codec = MP3
- reference count = 24
- decoder verified = true
- decode method = `LOCAL_TEMP_FFMPEG_PCM_F32LE_WAV`
- decoded audio persisted = false
- global lossless contract relaxed = false
- accepted additions = 1
- observer provider = `spleeter_runtime48`
- stem audio in master = false
- private audio used/upload path = false
- user Python required = false
- product release = false

### 最終artifact
- bundle artifact ID `10294507847`
- bundle URL: `https://github.com/htnk1982/test/actions/runs/34683190838/artifacts/10294507847`
- compressed bytes `745933620`
- artifact ZIP SHA256 `15800bf908f151c537df665de3673811d439e75d9e6e769d607b1ea9feb24db5`
- main EXE SHA256 `dc58f49b64706645ecf6b0e11d4a5068a76944826ffa4c7db520b37f12becf54`
- expanded bundle bytes `2154699010`
- observer runtime bytes `1925110546`
- evidence artifact ID `10294712698`
- evidence ZIP SHA256 `735fc5e3db96ae262fa0631de4ecc4f56b40da07001dfb77ae51b752798e7128`

旧artifact `10294875294` はWAV-reference fixtureまでしか検証しておらず、**superseded。使用禁止。**

容量は大きいが、ここで最適化するとP01を遅らせる。容量圧縮はP08へ明示的に延期する。

## 最初の実曲は11

第一候補：`11 - Traces_demo_44k (delimit).wav`。

私有環境内の事前スキャンでは約155秒付近に、約55Hz・高periodicity・基音が上位倍音に対して非常に弱い候補が複数あり、P03-Aのweak-but-present same-f0修正を最も情報量高く検証できる。

06は30Hz台のboundary/octave論点が混ざりやすく、12は候補が少ないため、順序は **11 → 06 → 12**。これは実験順序選択のための事前スキャンであり、P03の正式音楽受入ではない。

## P01を閉じる最後の1条件

ユーザーPCで最終artifactを展開し：
1. `RUN_P01_CALIBRATION.cmd`
2. `11 - Traces_demo_44k (delimit).wav`
3. canonical `reference.zip`
4. 元音源フォルダ外の保存先

を選択する。

成功時は**音源を再アップロードせず**、`CALIBRATION_MANIFEST.json`だけを返す。聴感は次のどれか1つで十分：

`改善 / 過剰 / 不足 / 違和感あり（時刻）`

失敗時は`P01_FAILURE.json`だけを返す。

この一回が通るまでP01をDONEにはしない。

## P03-A 技術成立の根拠

final P03-A commit `50a4592e45b3f810e905041c25cff1c3e35b2a88`。

- synthetic contract run `34680941299`：Ubuntu / Windows各394 tests PASS
- real Spleeter full-chain run `34680941252` / job `103519335096` success
- manual event times false
- 自動event 4 / tonal candidate 1 / same-f0 addition 1
- source hash不変
- stem master混入なし
- old Note-Sub呼出しなし
- private audio使用なし

実Spleeterでrole support 86.4%、pitch support 78.5%が各75%閾値を満たすのにframewise intersectionだけ72.8%となる設計過剰制約を発見。閾値を緩めず、role/pitchを独立event-level evidenceへ分離済み。

## P02 技術成立の根拠

Deezer Spleeter v1.4.0 4stems asset SHA256 `3adb4a50ad4eb18c7c4d65fcf4cf2367a07d48408a5eb7d03cd20067429dfaa8`。

runtime manifest SHA256 `f97c83aa0619b5c315d1ae54b13fa300e7e35043dd241a1e67a8108060d3d874`。Windows / Ubuntuのローカル推論・隔離runtimeを受入済み。未圧縮runtime 1,925,110,546 bytes / 24,767 files。容量最適化はP08。

## 次の主タスク

1. **P01 final local acceptance**：11をユーザーPCで1件実行。
2. manifest＋最小聴感からP03の量・発動タイミングを更新。
3. 06→12へ拡張しP03/P04親を閉じる。
4. P05でOPPO/limiter後の完成WAV/MP3候補順位を判定。
5. P08でruntime容量圧縮、GUI、保存、実曲、版/hash固定EXEを最終受入。

## 完了を偽らない運転規則

- 1入力に対し有限バッチでDONE / concrete failure / external blockerのいずれかに閉じる。
- 管理資料、試験件数、コード量を完成率へ換算しない。
- 私有音源を公開GitHub/CIへ送らない。
- 既存HE/HFTC/OPPOを不用意に大改造しない。
- 合成/Frozen成功を本人の音楽的合格の代用にしない。
- global safety contractを過去資産互換のために緩めない。boundary adapterで解く。
- P01の容量最適化はP08へ送る。今は実曲受入を優先する。
