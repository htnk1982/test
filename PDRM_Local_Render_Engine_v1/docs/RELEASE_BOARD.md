# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 9  
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`  
親Issue：#2。

## 現在地

**私有実曲11と06が連続PASS。v51の高速化は06で実曲成立し、30Hz台のboundary候補に対しても不要な低音を加えず、本人聴感は「音は文句なし」。**

06で得られた最重要知見は、`accepted_additions = 0 / final_assessment = ABSTAIN` が失敗ではなく、**不要な処理をしないこと自体が正しい音響判断になり得る**こと。11では必要なsame-f0補強を1件入れ、06では入れない。この対比をP03/P04の成立根拠とする。

現在のクリティカルパス：

**12実曲 → 11/06/12総合でP03/P04親受入 → P05完成WAV/MP3候補選択 → P08最終Windows EXE**

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **DONE #3** | 11実曲受入済み。v51 Frozen/roundtripもPASS |
| P02 配布用observer | **DONE #8** | 製品runtime容量最適化はP08 |
| P03 発音・役割・必要量の自動判断 | **PARTIAL：P03-A DONE #10 / 11 PASS / 06 PASS / v51実曲PASS** | 12で「候補が少ない曲を過処理しない」を確認後、親受入判断 |
| P04 加算・広域/狭帯域統合 | **PARTIAL：P04-A DONE #9 / 11 PASS / 06 PASS** | 12を確認後、共同予算・無処理判断を含め親受入判断 |
| P05 完成WAV/MP3での候補選択・実曲回帰 | WAITING | 12後。OPPO/limiter後を含め判定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release解禁はP03/P08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7完了 |
| P08 製品Windows EXEと最終受入 | WAITING | runtime圧縮、実曲、GUI、保存、版/hash固定EXEを完走 |

---

## 実曲11：必要な処理をする正例

対象：`11 - Traces_demo_44k (delimit).wav`  
source SHA256：`8e7edc625fe8dfb3f153da6eda6759b90f4a521f0f860bb1a91eff359685e3a2`。

旧v50実行：約`3166秒`（約52.8分）。

主要結果：
- `accepted_additions = 1`
- source unchanged = true
- stem audio in master = false
- MASTER：約`-12.005 LUFS-I / -2.046 dBTP`
- MP3：約`-13.997 LUFS-I`

本人聴感：

> かなり改善。耳障りでないところを攻めて、十分ラウド。

ここでの成功原則は、**全部を直すことではなく、知覚的に安全な余白だけを使うこと**。

---

## v51：evidence-preserving pruning

planner：`automatic-joint-lab-0.4.0`。

音響基準はv50のまま、結果を変えられないSpleeter推論だけを削除する。

1. v50で最終採用されないlegacy/base observer stageを削除。
2. relative-low scoreが`<= 0.05`で数学的に改善不能ならrole observerを呼ばない。
3. original sourceだけで確定するf0/source-shape vetoをSpleeterより先に評価する。
4. 必要候補だけpersistent Spleeterへ渡す。

技術parity run `34697305740`：Ubuntu/Windows unit PASS、real Spleeter parity PASS。生成fixtureではv50/v51の可聴制御が一致し、observer callsを2→1へ削減。

canonical v51 Windows bundle：
- main promotion commit：`7e39e1460d7cba209187fe3d462b15064b7e2782`
- Frozen/roundtrip run：`34698184104` SUCCESS
- artifact ID：`10299492024`
- artifact ZIP SHA256：`85f946ae3aee6985e01286bbad89b27207e586126ae499ca5826359881a2dddd`
- roundtrip evidence artifact ID：`10298789983`

---

## 実曲06：高速化＋境界＋「何もしない」判断の正例

対象：`06 - 03 返事は私.wav`  
source SHA256：`739a57c630e7ec3697a33b183723e9fa2768f8062e02e31cdc65dc051fb45031`  
source：48kHz stereo / 12,232,318 frames / 約254.84秒。  
canonical reference.zip SHA256：`82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a`。

### 速度実績

- P01 end-to-end：`624.109秒` = 約`10分24秒`
- source長：約`254.84秒`
- 実時間倍率：約`2.45x`
- theoretical v50 observer calls：`172`
- v51 executed：`3`
- avoided：`169`（約`98.3%`）
  - obsolete base stage：58
  - source veto：64
  - zero reduction score：47

11旧v50の52.8分との単純比較は曲が異なるため厳密な速度比ではない。ただし、**neural observer呼出しそのものが172→3へ縮退したことはmanifestで直接確認済み**。利用者評価は「速度はまずまず早くなった」。

### 音響判断

- automatically discovered events：1290
- tonal same-f0 candidates：67
- accepted additions：`0`
- final assessment：`ABSTAIN`
- reduction assessment：`ABSTAIN`
- relative-low candidateは存在したが、`initial_excess_db = 0.0`のため改善不能としてobserverを呼ばず停止
- 67候補のうち64件はpre-observer source veto
- 残る3件だけSpleeter評価し、3件ともdenied
- old Note-Sub called：false
- new octave creation：なし

30Hz台には約30.20 / 30.76 / 30.78 / 30.84 / 30.90 / 31.04Hzの候補が存在した。特に約30.20Hz・30.84Hzの候補はsource-only vetoだけでは決めずSpleeterまで送ったが、`ABSTAIN_INSUFFICIENT_INTERIOR_FRAMES / ABSTAIN_FALLBACK_ROLE_OR_PITCH`で拒否した。**速度向上のために30Hz台を雑に通す設計にはなっていない。**

### 完成音

- MASTER：`-12.00198 LUFS-I`
- MASTER TP estimate：`-2.01620 dBTP`
- MP3：`-13.99538 LUFS-I`
- MP3 TP estimate：`-3.75789 dBTP`
- MASTER SHA256：`f1fcc824ed3a3b4c8fdeb2e2696d93701252df084bff8539979e783c8822d481`
- LISTEN MP3 SHA256：`d5714b7a3835b350ca10e2bc161f9ab0aec04b1dac0d76654f5939741c9c82f2`
- source unchanged：true
- private audio uploaded：false
- stem audio exported：false
- stem audio in master：false

本人聴感：

> 速度はまずまず早くなった。音は文句なし。

### 06から確定する原則

**`ABSTAIN`は未完成を意味しない。必要性が証明できなければ低域処理を足さず、それでも完成音が本人基準を満たすなら、それが正解。**

したがって06では「accepted additionが0だから閾値を緩める」という改修は行わない。むしろ、11では1件通し06では0件に止めた選択性を維持する。

---

## 次の唯一の実曲：12

同じv51 bundleをそのまま使う。コード変更・再ビルドはしない。

12で確認する問いは一つだけ：

> **候補の少ない曲に対して、PDRMが何かをするために無理に理由を作らず、必要なら処理し、不要なら正しく何もしないか。**

返却は06と同じく：
1. `CALIBRATION_MANIFEST.json`
2. 聴感1行

12が本人聴感でPASSし、安全条件も満たせば、11/06/12をまとめてP03/P04親の実曲受入を判断し、次の主タスクをP05へ移す。

---

## 完了を偽らない運転規則

- 合成/Frozen/CI成功を本人の音楽的合格の代用にしない。
- `ABSTAIN`や`0 additions`を自動的に失敗扱いしない。本人聴感と安全条件を含む目的達成で判定する。
- 私有音源を公開GitHub/CIへ送らない。
- v51は判断基準を緩めて速くしない。結果を変えられない推論だけを消す。
- global safety/lossless contractを互換性のために緩めない。
- 06がPASSしたので、速度をさらに弄る前に12という次の現実観測へ進む。
- 同じ証拠を再分析し続けず、クリティカルパスを前へ送る。
