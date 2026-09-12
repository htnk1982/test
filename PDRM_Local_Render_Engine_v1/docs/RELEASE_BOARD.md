# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 6
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`
親Issue：#2。

## 現在地

**P01の「ローカルTransport復旧待ち」を解消。自己完結Private Calibration Bundleが成立し、残件はユーザーPC上で私有実曲1件を実行・聴感することだけ。**

P02、P03-A、P04-A、P06-A、P07は技術条件を満たした。現在のクリティカルパスは **P01私有実曲1件のローカル実行 → P03/P04実曲校正 → P05完成WAV/MP3選択 → P08最終EXE受入**。ChatGPT側のTransport復旧は今後の依存条件ではない。

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **READY FOR LOCAL RUN #3** | Private Calibration Bundleで`11 - Traces`を1件実行し、manifest＋最小聴感を回収 |
| P02 配布用observer | **DONE #8** | 製品EXEへの配置と容量最適化はP08。私有音源での音楽校正はP03/P05 |
| P03 発音・役割・必要量の自動判断 | **PARTIAL：P03-A DONE #10 / 実曲待ち** | まず11、次に06→12へ同じplannerを適用し、本人レビューで量を校正 |
| P04 加算・広域/狭帯域統合 | **PARTIAL：P04-A DONE #9 + P03-A接続DONE** | 私有実曲で共同予算・聴感を確認後に親を閉じる |
| P05 完成WAV/MP3での候補選択・実曲回帰 | WAITING | P01/P03実曲校正後。OPPO/limiter経路変化込みで判定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release runtimeの解禁はP03/P08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7 完了 |
| P08 製品Windows EXEと最終受入 | WAITING | 実モデルruntime配置、容量圧縮、実曲、GUI、保存を版/hash固定EXEで完走 |

## P01ボトルネック再定義と解消

### 問いの変形
旧P01は「ChatGPTローカル実行の`TransportTimeoutError`を復旧する」が事実上のクリティカルパスになっていた。しかし目的はTransportを直すことではない。必要なのは、**確定したP03-Aを、私有音源を外部へ出さずユーザーPC上で実行し、版・hash・planner判断・完成音・聴感を回収できること**である。

この目的へ戻し、Transportを依存関係から除去した。公開CIは実行器だけを生成し、私有source/referenceはユーザーPCでのみ読み込む。

### Private Calibration Bundle
実装commit列：
- `ca613c9874560441e68d786ebe67da0dbc70b4f4` — private calibration runner
- `feb21b9d0f08c3d10774f42843d987509699db32` — self-contained bundle builder
- `1894c814d93e8ddf89739d4b76ae27e86f3e2419` — Windows workflow
- `182e066ab34cc12372dba03b69ba547aeb4bde3b` — source/output分離＋`reference.zip`実経路self-test

構成：
- 主処理：Frozen Windows EXE。ユーザーPython不要。
- observer：兄弟ディレクトリの内蔵CPython3.11.9 + Spleeter2.4.2 + TensorFlow2.12.1隔離runtime。
- P03-A baseline：`50a4592e45b3f810e905041c25cff1c3e35b2a88`。
- source：WAV/FLACをユーザーPCで選択。
- reference：既存`reference.zip`をユーザーPCで選択。bundleへ音源を同梱しない。
- output：sourceフォルダ外のみ。既存結果上書き禁止。
- 出力：`MASTER.wav` / `LISTEN_320kbps.mp3` / `CALIBRATION_MANIFEST.json` / `REVIEW.md`ほか。
- private audioをGitHub/CIへ送るコード経路を持たない。stem音声を保存・完成音へ混入しない。

### Frozen自己試験
最終CI run `34682265217` / Windows job `103522952660` success。

生成fixture 4本を`reference.zip`化し、日本語/空白path相当のFrozen EXEから、**reference ZIP読込 → calibration → 実Spleeter隔離runtime → P03-A → MASTER.wav / MP3**まで完走。

自己試験結果：
- `frozen=true`
- `source_unchanged=true`
- `reference_zip_exercised=true`
- `accepted_additions=1`
- `observer_provider=spleeter_runtime48`
- `stem_audio_in_master=false`
- `private_audio=false`
- `user_python_required=false`
- `product_release=false`

主EXE SHA256：`298cc29f8d3834ae7789122c329574330a9bd10075be9da1e7219b95749774b5`。
展開bundle：2,154,675,475 bytes。うちobserver runtime 1,925,110,546 bytes。圧縮artifact 745,923,979 bytes。

成果物：
- bundle artifact ID `10294875294`, ZIP SHA256 `41dc173c37d4a32a9decfbaec385644ca860c23516b0cf11184441c03ce6bb46`
- evidence artifact ID `10293344807`, ZIP SHA256 `6325e72aa031c4c743803b79deb99fc66dbe4f376c1e235e503925cffeaf0fce`
- run `34682265217`

初回run `34682007702`は、self-testでsourceとoutputを同じ親へ置いたため「source folder配下へ結果を書かない」安全ゲートが拒否した。安全条件は外さず、self-testを本番同様に別領域へ修正して再実行した。

### 私有資産の再発見
既存資産を再アップロード・再ラベルせず確認済み：
- 元WAV：06 / 11 / 12
- `reference.zip`：24本
- `before.zip` / `after.zip`：各21本（08/11/12を含む）

公開GitHub/CIへこれらの音声は送っていない。

### 最初の実曲
第一候補を`11 - Traces_demo_44k (delimit).wav`とする。私有環境内の事前スキャンで約155秒付近に、約55Hz・高periodicity・基音が上位倍音に対して非常に弱い候補が複数あり、P03-Aで修正したweak-but-present same-f0の実曲検証として情報利得が最も高い。

06は30Hz台の境界/octave論点が混ざりやすく、12は候補が少ないため、順序は **11 → 06 → 12** とする。

### P01を閉じる残り1条件
ユーザーPC上でbundleを用い、11を元音源非破壊で1件完走する。返す情報は音源ではなく`CALIBRATION_MANIFEST.json`と、聴感の **改善 / 過剰 / 不足 / 違和感あり（時刻）** のいずれかでよい。

これが通るまでP01をDONEにはしない。

## P03-Aを閉じた根拠

### source-driven planner
`source_events_v41`で元2mixからイベントを自動発見し、manual event timeをplannerへ渡さない。`SpleeterRuntimeObserver`のsealed identity/hash/preprocessingを検証し、observer windowを自動配置。広域low/lowmid減算とP04-A same-fundamental補強を同じjoint planへ統合し、同時刻・帯域での自己相殺は減算優先で拒否する。

### weak-f0 fallbackの実Spleeter差分
実Spleeterでは、同じ55Hzイベントでもstem意味割当てがフレーム単位で揺れ、role support 86.4%、bass-pitch support 78.5%はそれぞれ既存75%閾値を満たす一方、その同時刻intersectionだけ72.8%となっていた。これは一つのseparator jitterをroleとpitchの両方で二重に時間一致要求する設計だった。

final commit `50a4592e45b3f810e905041c25cff1c3e35b2a88` で、閾値を緩和せず、role supportとpitch supportを独立event-level evidenceとしてそれぞれ75%以上要求するよう修正。framewise intersectionは診断値へ降格し、render maskはnon-drum/non-vocalかつbass+other energyを持つrole側だけを使用する。元2mixのf0実在証明、source brightness veto、octave-down禁止、kick/vocal拒否、bass pitch/periodicity条件は保持した。

### 合成contract回帰
CI run `34680941299`。
- Ubuntu：394 tests PASS
- Windows Server 2022：394 tests PASS
- manual event times：false
- private music：false

### Windows実Spleeter full-chain
CI run `34680941252` / job `103519335096` success。内蔵CPython3.11.9 + Spleeter2.4.2 + TensorFlow2.12.1の隔離runtimeを主PDRM Python3.12から呼び出した。

受入結果：
- `manual_event_times_used=false`
- 自動発見event 4件 / tonal candidate 1件
- same-f0 addition 1件受入 / v50受入1件 / fallback受入1件
- permission path `EXISTING_WEAK_F0_FALLBACK`
- 元2mix hash不変
- stem音声のmaster混入なし
- 旧Note-Sub呼出しなし
- TensorFlow/Spleeterを主processへimportしない
- private audio使用なし
- WAV/MP3まで完走

この受入はP03-Aの技術成立を証明するが、本人の私有実曲に対する音楽的適合・最終量校正は評価していない。

## P02を閉じた根拠

Deezer Spleeter v1.4.0 `4stems.tar.gz`を公式checksumで固定。asset SHA256 `3adb4a50ad4eb18c7c4d65fcf4cf2367a07d48408a5eb7d03cd20067429dfaa8`。Windows Server 2022 / Ubuntuで44.1kHz `vocals/drums/bass/other`のローカル推論に成功。

runtime manifest SHA256 `f97c83aa0619b5c315d1ae54b13fa300e7e35043dd241a1e67a8108060d3d874`。CI run `34622532092` / Windows job `103339719885` success。未圧縮runtimeは1,925,110,546 bytes / 24,767 files。容量最適化はP08へ残す。

PDRM permission gateによるcounterexample比較はSpleeter 4/4、HDEMUCS research baseline 3/4。これは一般的source-separation優越性や私有実曲精度の証明ではなく、PDRM操作安全の限定結果である。

## 次の主タスク

1. **P01 final local acceptance**：Private Calibration Bundleで`11 - Traces`をユーザーPC上で実行。
2. `CALIBRATION_MANIFEST.json`と最小聴感を基に、P03の量・発動タイミングを校正。
3. その結果を06→12へ拡張し、P03/P04親を閉じる。
4. P05でOPPO/limiter後の完成WAV/MP3候補順位を判定。
5. P08で製品版runtime容量圧縮、GUI、保存、実曲、版/hash固定EXEを最終受入。

## 完了を偽らない運転規則

- 1入力に対し有限バッチを実行し、DONE / concrete failure / external blockerのいずれかで必ず回答を閉じる。
- 管理資料、試験件数、コード量を進捗率にしない。
- 既存HE/HFTC/OPPOを不用意に大改造しない。
- 私有音源を公開GitHub/CIへ送ってP01を迂回しない。
- 新しい判断器は、どの既存課題を閉じるかを明示してから実装する。
- 合成/CI成功を本人の音楽的合格の代用にしない。
- P01のbundle容量最適化を、P01の実曲受入より先に行わない。容量最適化はP08で扱う。
