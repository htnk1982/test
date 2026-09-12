# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 5
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`
親Issue：#2。

## 現在地

**P03-Aのsource-driven joint planner技術受入をDONE。P03親の残件はP01復旧後の私有実曲校正。**
P02、P03-A、P04-A、P06-A、P07は技術条件を満たした。現在のクリティカルパスはP01の私有実曲実行基盤復旧→P03実曲校正→P05完成WAV/MP3選択→P08最終EXE受入。P01不通中もP08の容量圧縮など独立作業は進められるが、実曲の音楽的合格を代用しない。

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **BLOCKED #3** | ローカル実行環境の復旧→既存音源manifest→実曲1件 |
| P02 配布用observer | **DONE #8** | 製品EXEへの配置と容量最適化はP08。私有音源での音楽校正はP03/P05 |
| P03 発音・役割・必要量の自動判断 | **PARTIAL：P03-A DONE #10 / P01待ち** | 08/11/12・reference/before/afterへ同じplannerを適用し、本人レビューで量を校正 |
| P04 加算・広域/狭帯域統合 | **PARTIAL：P04-A DONE #9 + P03-A接続DONE** | 私有実曲で共同予算・聴感を確認後に親を閉じる |
| P05 完成WAV/MP3での候補選択・実曲回帰 | WAITING | P01/P03実曲校正後。OPPO/limiter経路変化込みで判定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release runtimeの解禁はP03/P08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7 完了 |
| P08 製品Windows EXEと最終受入 | WAITING | 実モデルruntime配置、容量圧縮、実曲、GUI、保存を版/hash固定EXEで完走 |

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

追加回帰では、role support約80%、pitch support約80%、両者のframewise intersection約60%という非重複jitterを作り、独立event-level証拠が成立する場合のみ許可することを固定した。既存のkick/vocal/octave-down/rest等の拒否回帰も維持。

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

この受入はP03-Aの技術成立を証明するが、本人の私有実曲に対する音楽的適合・最終量校正は評価していない。そこはP01復旧後のP03/P05に残す。

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

比較artifact ID `10272729312`、ZIP SHA256 `571e3a7b36c8c4997132bf0f951a24e471db5b47a96a1c5e37f912744cc5bc40`。HDEMUCS checkpointはCI終了前に削除し配布物へ含めていない。

## 次の主タスク

1. **P01復旧がクリティカルパス。** 私有実曲を公開GitHub/CIへ送らず、ローカル実行環境を復旧する。
2. P01復旧後、既存08/11/12・reference/before/after・レビューへP03-A plannerをそのまま適用する。
3. 実曲で、広域減算・same-f0補強・既存HE/HFTC/OPPOを含む完成WAV/MP3を比較し、必要量と発動タイミングを校正する。
4. その結果でP03/P04親を閉じ、P05候補選択へ進む。
5. P01不通中は、P08のruntime容量圧縮など実曲評価と独立な作業だけを進めてよい。

## 完了を偽らない運転規則

- 1入力に対し有限バッチを実行し、DONE / concrete failure / external blockerのいずれかで必ず回答を閉じる。
- 管理資料、試験件数、コード量を進捗率にしない。
- 既存HE/HFTC/OPPOを不用意に大改造しない。
- 私有音源を公開GitHub/CIへ送ってP01を迂回しない。
- 新しい判断器は、どの既存課題を閉じるかを明示してから実装する。
- 合成/CI成功を本人の音楽的合格の代用にしない。
