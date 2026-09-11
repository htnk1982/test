# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 4
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`
親Issue：#2。

## 現在地

**P02をDONE。次の主タスクはP03「実曲の発音・役割・適用量の自動判断」。**
運用系P06-A/P07、同一基音の物理処理接続P04-Aも完了済み。残る製品中核はP01/P03/P05/P08で、P01の私有実曲環境が復旧し次第、実曲校正を最優先する。

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **BLOCKED #3** | ローカル実行環境の復旧→既存音源manifest→実曲1件 |
| P02 配布用observer | **DONE #8** | 製品EXEへの配置と容量最適化はP08。私有音源での音楽校正はP03/P05 |
| P03 発音・役割・必要量の自動判断 | **IN PROGRESS** | SpleeterRuntimeObserverをsource-driven plannerへ接続し、手入力時刻なしで加算/減算を決める |
| P04 加算・広域/狭帯域統合 | **PARTIAL：P04-A DONE #9** | P03の自動判断との接続後に親を閉じる |
| P05 完成WAV/MP3での候補選択・実曲回帰 | WAITING | P01/P03後。OPPO/limiter経路変化込みで判定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release runtimeの解禁はP03/P08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7 完了 |
| P08 製品Windows EXEと最終受入 | WAITING | 実モデルruntime配置、容量圧縮、実曲、GUI、保存を版/hash固定EXEで完走 |

## P02を閉じた根拠

### 公式asset・Windows実推論
Deezer Spleeter v1.4.0 `4stems.tar.gz`を公式checksumで固定。asset SHA256 `3adb4a50ad4eb18c7c4d65fcf4cf2367a07d48408a5eb7d03cd20067429dfaa8`。Windows Server 2022 / Ubuntuで44.1kHz `vocals/drums/bass/other`のローカル推論に成功。

### Python/TensorFlowを利用者に要求しない隔離runtime
主PDRM Python3.12/Numpy2系から、内蔵CPython3.11.9 + Spleeter2.4.2 + TensorFlow2.12.1を別processで起動。日本語/空白pathから2回連続推論し、`sys.executable`/`sys.prefix`が同梱runtime内であること、元音源hash不変、stem WAV非保存、完成音へstem非混入、曲処理時model download禁止、一時IPC清掃を確認。

runtime manifest SHA256 `f97c83aa0619b5c315d1ae54b13fa300e7e35043dd241a1e67a8108060d3d874`。CI run `34622532092` / Windows job `103339719885` success。証拠artifact ID `10273107830`、ZIP SHA256 `ff5d9566adb8f1c8aa7ee7743cc54211772a6c403dec4bff181e28be9e393c4a`。runtime本体/model重みはartifactへ保存していない。

未圧縮runtimeは1,925,110,546 bytes / 24,767 files。これは最終配布には大きいためP08で依存削減/配布圧縮を行う。ただし、hostへのPython/TensorFlow導入不要・offline local推論というP02の機能条件は満たした。

### PDRM用途のrole safety比較
初回比較は低い歌声fixtureを正しく`vocals` stemへ分類できることを要求し、Spleeter/HDEMUCSとも失敗した。この条件はPDRMの操作許可と一致しないため、その失敗を消さず、2回目は既存PDRMの実permission gateそのものを使用した。

最終比較CI run `34623196785` / job `103341899355` success。生成counterexample 4種：
- bass_event：低域減算を許可し、同一基音55Hz補強も許可
- kick_only：drum由来低域減算は許可するが、bass同一基音補強は拒否
- vocal_low：低域減算・counterfactual 55Hz補強を拒否、165→55Hz octave-downも拒否
- rest_gap：左右のbass eventを許可し、中央休符の低域操作許可0

Spleeter 4/4、HDEMUCS research baseline 3/4。vocal_lowでHDEMUCSはbassとして広域減算を1.0許可しcounterfactual 55Hz補強も許可した一方、Spleeterは対象を主に`other`へ割当て、PDRMの広域減算許可0、同一基音補強も拒否した。これは一般的source-separation優越性や私有実曲精度の証明ではなく、PDRMの操作安全counterexampleに対する結果。

比較artifact ID `10272729312`、SHA256 `571e3a7b36c8c4997132bf0f951a24e471db5b47a96a1c5e37f912744cc5bc40`。HDEMUCS checkpointはCI終了前に削除し配布物へ含めていない。

## 次の主タスク P03

1. `SpleeterRuntimeObserver`のsealed feature契約をsource-driven plannerへ接続。
2. 元2mixからイベントを自動発見し、observer windowを自動配置。手入力時刻を製品判断へ残さない。
3. 広域low/lowmid減算とP04-Aのsame-fundamental補強を同じplannerで選択し、同時刻の自己相殺を拒否。
4. kick/vocal/rest/weak-fundamental/overweight-lowを合成counterexampleで回帰。
5. P01復旧後、既存08/11/12・reference/before/after・レビューへ同じplannerを適用し、私有実曲で量を校正。

P03の合成試験成功だけで本人の音楽的適合をDONEにしない。逆にP01不通を理由に、接続可能な自動判断コードまで止めない。

## 完了を偽らない運転規則

- 1入力に対し有限バッチを実行し、DONE / concrete failure / external blockerのいずれかで必ず回答を閉じる。
- 管理資料、試験件数、コード量を進捗率にしない。
- 既存HE/HFTC/OPPOを不用意に大改造しない。
- 私有音源を公開GitHub/CIへ送ってP01を迂回しない。
- 新しい判断器は、どの既存課題を閉じるかを明示してから実装する。
