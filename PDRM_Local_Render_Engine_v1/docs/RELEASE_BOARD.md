# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 8  
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`  
親Issue：#2。

## 現在地

**P01はDONE。私有実曲11 `Traces` をユーザーPC上で完走し、技術条件と本人聴感の両方で最初の実曲受入を通過した。**

次の問いは「さらに音をいじるか」ではない。11では「耳障りでないところを攻めて、十分ラウド」という目的が成立した一方、旧実装は約53分かかった。したがって、**音響判断を変えずに、最終判断へ寄与しないSpleeter推論を消し、そのうえで06→12へ実曲一般化する**ことを現在のクリティカルパスとする。

現在のクリティカルパス：

**06実曲（v51速度＋境界） → 12実曲 → P03/P04親受入 → P05完成WAV/MP3候補選択 → P08最終Windows EXE**

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **DONE #3** | 11 Tracesのmanifest＋本人聴感回収済み。v51 bundleも配布後roundtrip受入済み |
| P02 配布用observer | **DONE #8** | persistent worker技術受入済み。製品runtime容量最適化はP08 |
| P03 発音・役割・必要量の自動判断 | **PARTIAL：P03-A DONE #10 / 11実曲PASS / v51技術PASS** | 06→12で実曲一般化。v51の実曲速度と判断維持を確認 |
| P04 加算・広域/狭帯域統合 | **PARTIAL：P04-A DONE #9 + 11実曲PASS** | 06→12で共同予算・聴感・境界を確認 |
| P05 完成WAV/MP3での候補選択・実曲回帰 | WAITING | 06/12後。OPPO/limiter後を含め判定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release解禁はP03/P08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7完了 |
| P08 製品Windows EXEと最終受入 | WAITING | runtime圧縮、実曲、GUI、保存、版/hash固定EXEを完走 |

---

## P01：私有実曲11の最終受入

対象：`11 - Traces_demo_44k (delimit).wav`  
source SHA256：`8e7edc625fe8dfb3f153da6eda6759b90f4a521f0f860bb1a91eff359685e3a2`  
canonical reference.zip SHA256：`82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a`  
reference：24 MP3 / 44.1kHz stereo。

実曲manifest：
- accepted P03-A baseline：`50a4592e45b3f810e905041c25cff1c3e35b2a88`
- `accepted_additions = 1`
- `source_unchanged = true`
- `private_audio_uploaded = false`
- `stem_audio_exported = false`
- `stem_audio_in_master = false`
- MASTER：`-12.0050404 LUFS-I` / true peak estimate `-2.0459910 dBTP`
- MP3：`-13.9972045 LUFS-I`
- MASTER SHA256：`ff5527ad80c78d059fa14b4c9b807805fe8adebfa694953e66aea82ed8a2aca9`
- LISTEN MP3 SHA256：`c14c4d159c26d7beaaaa99b6c3abc33e66a1ba1e75748e9d257c59554d6496cc`

本人聴感：

> かなり改善。耳障りでないところを攻めて、十分ラウド。

この聴感を、`lowend_assessment = PARTIAL`だから「もっと処理するべき」と上書きしない。ここでの成功原則は、**全部を直すことではなく、知覚的に安全な余白を利用して十分なラウドネスを得ること**。

P01 Issue #3はこの実曲受入をもってDONEとしてclosed。

---

## 実行時間：症状ではなく呼出し構造を直す

11の旧v50実行は約`3166秒`（約52.8分）。うちほぼ全量が`STEM_OBSERVER`で、約49分を占めた。

実曲manifest＋進捗ログから旧経路を分解すると、概算で：
- v48 legacy/base observer：76 calls
- v49 relative-low observer：12 calls
- v50 same-f0再評価：84 calls
- 合計：約172 neural observer calls

persistent worker化だけでは、TensorFlow/Spleeter初期化費は減るが、172回の分離そのものは残る。よって主問題は「毎回process起動」ではなく、**最終判断を変えない推論まで実行していること**だった。

### v51：evidence-preserving pruning

planner：`automatic-joint-lab-0.4.0`。

v51は音響基準を緩めず、Spleeterを呼ぶ前に確定できるNOを先に落とす。

1. **v48 legacy observer stageを最終v50経路から除去**  
   v50は旧stageの加算結果を採用せず、source-proven same-f0候補を再評価していたため、最終音へ寄与しない旧推論を削除。

2. **relative-low scoreが改善不能ならobserverを呼ばない**  
   scoreは非負。旧受入は`end < start - 0.05`。したがって`start <= 0.05`では数学的に合格不能であり、role observationを行っても結果を変えられない。

3. **source-only vetoをSpleeterより先に評価**  
   original sourceのf0 proof / source spectral shapeだけで確定する veto があれば、その候補はSpleeter結果に関係なくNO。Tracesでは84候補中80候補がこの型だった。

受入条件は「速いこと」より先に、**v50と可聴制御面が一致すること**。

### v51技術受入

run `34697305740`：Ubuntu/Windows unit PASS、real Spleeter parity PASS。

real Spleeter fixture：
- v50 accepted = 1
- v51 accepted = 1
- `audio_semantics_equal = true`
- v50相当 observer calls = 2
- v51 executed = 1
- source unchanged = true
- main processへTensorFlow/Spleeter importなし
- stem audio in master = false

これは**生成fixtureでの技術同値性**であり、私有実曲の音楽的合格や実曲速度を代用しない。

Traces manifestへv51条件を構造的に当てると、約172 calls → 約4 callsまで削減可能と推定される。ただしこれは実曲再実行前の**構造予測**であり、速度実績とは呼ばない。

---

## persistent observer

workerを毎window終了せず、同一Spleeter Separatorをsession内で再利用する経路も受入済み。

run `34696249708`：SUCCESS。
- one-shot：約17.23秒
- persistent startup：約3.12秒
- persistent first：約13.42秒
- persistent second：約12.78秒
- feature arrays同値
- 同一worker PID再利用
- source unchanged
- stem保存・master混入なし

persistent化は補助的高速化。v51 pruningが呼出し回数そのものを減らす主施策。

---

## v51 Windows bundle：配布後バイト列まで受入

canonical main HEAD（v51 promotion）：`7e39e1460d7cba209187fe3d462b15064b7e2782`。

main-branch Frozen/roundtrip CI：run `34698184104` **SUCCESS**。

受入内容：
- PyInstaller Frozen EXE
- user Python不要
- embedded CPython 3.11 + Spleeter 2.4.2 + TensorFlow 2.12.1
- application-local VC runtime
- native extension load / Separator init PASS
- persistent worker available
- `.probe`保持 / AppleDouble metadataなし
- 日本語＋空白pathでartifactを再ダウンロードして再実行
- 24 MP3 ZIP → local temp float-WAV → calibration → v51 → MASTER/MP3 完走
- `planner_implementation = automatic-joint-lab-0.4.0`
- accepted additions = 1
- source unchanged
- global lossless contract relaxed = false
- stem audio in master = false
- private audio = false
- product release = false

canonical v51 artifact：
- bundle artifact ID：`10299492024`
- compressed bytes：`756750947`
- artifact ZIP SHA256：`85f946ae3aee6985e01286bbad89b27207e586126ae499ca5826359881a2dddd`
- run：`34698184104`
- roundtrip evidence artifact ID：`10298789983`

旧v50 bundleはP01/11の受入証拠として保持するが、**06以降の実曲校正にはv51 bundleを使う**。

---

## 次の実曲：06

次は`06`。理由は、11でweak-but-present same-f0を通した後、06は30Hz台のboundary/octave論点を含みやすく、v51が「高速になっただけで誤って新しい低音を作っていないか」を最も早く識別できるため。

v51 manifestには次を自動記録する：
- `performance.elapsed_seconds`：P01 end-to-end実行時間
- `planner_report.observer_optimization`：理論旧calls / 実行calls / 削減理由
- source/reference/outputsのhash
- planner/observer identity

したがって利用者にストップウォッチ計測や進捗ログ転記を要求しない。

06成功時に必要な返却は：
1. `CALIBRATION_MANIFEST.json`
2. 聴感1行：`改善 / 過剰 / 不足 / 違和感あり（時刻）`、または自由記述1行

06で音響判断が維持され速度が改善したら、同じv51 bundleで12へ進む。06で境界破綻があれば、速度施策全体を戻さず、該当するsource veto / role-pitch gateだけへ戻る。

---

## その後

1. **06 v51 private run**：速度＋boundary/octave実曲識別。
2. **12 v51 private run**：候補の少ない曲で過処理しないことを確認。
3. 11/06/12をまとめてP03/P04親の受入を判断。
4. P05でOPPO/limiter後を含む完成WAV/MP3候補順位を判定。
5. P08でruntime容量圧縮、最終GUI、保存・復旧、版/hash固定EXEを最終受入。

## 完了を偽らない運転規則

- 合成/Frozen/CI成功を本人の音楽的合格の代用にしない。
- 私有音源を公開GitHub/CIへ送らない。
- v51は判断基準を緩めて速くしない。**結果を変えられない推論だけを消す。**
- global safety/lossless contractを互換性のために緩めない。boundary adapterで解く。
- 追加最適化は、06の実測で次のボトルネックが現れるまで行わない。
- 同じ証拠・候補・境界のまま再分析を繰り返さない。現実の次の観測へ進む。
