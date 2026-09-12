# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-12 / revision 10  
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`  
親Issue：#2。

## 現在地

**私有実曲11・06・12がすべて本人聴感PASS。P03/P04は、必要な曲だけ処理し、不要な曲では処理を作らない選択性まで実曲で確認したためDONE。次はP05 #11。**

3曲の対比が重要：
- 11 `Traces`：weak-but-present same-f0を1件だけ補強。本人聴感「かなり改善。耳障りでないところを攻めて、十分ラウド。」
- 06 `返事は私`：30Hz台を含む候補を検出したが追加0。本人聴感「音は文句なし。」
- 12 `私=AI-MY`：48 same-f0候補をすべてsource側で拒否し、neural observerを1回も呼ばず追加0。本人聴感「かなり聴きやすくなったと思います。」

したがってP03/P04の成功条件は「何かを足すこと」ではなく、**音響的必要性が証明できる場合だけ作用し、それ以外はABSTAINすること**と確定する。

現在のクリティカルパス：

**P05完成WAV/MP3の最終ピーク処理・候補選択 #11 → P08最終Windows EXE**

| ID | 状態 | 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **DONE #3** | 私有実曲でmanifest＋本人聴感を回収済み |
| P02 配布用observer | **DONE #8** | runtime容量最適化はP08 |
| P03 発音・役割・必要量の自動判断 | **DONE** | P03-A #10 + 11/06/12実曲一般化PASS |
| P04 加算・広域/狭帯域統合 | **DONE** | P04-A #9 + 必要時1件/不要時0件を実曲で確認 |
| P05 完成WAV/MP3での候補選択・実曲回帰 | **ACTIVE #11** | 最終ピーク処理後の完成WAV/MP3を有限候補で比較し1案へ固定 |
| P06 GUI/進捗/キャンセル | **P06-A DONE #6** | product-release統合はP08 |
| P07 保存・退避・復旧・多曲/掃除 | **DONE** | A #4 / B #5 / C #7完了 |
| P08 製品Windows EXEと最終受入 | WAITING | P05採用設定、runtime圧縮、GUI、保存、版/hash固定EXE |

---

## 実曲11：必要な処理をする正例

対象：`11 - Traces_demo_44k (delimit).wav`  
source SHA256：`8e7edc625fe8dfb3f153da6eda6759b90f4a521f0f860bb1a91eff359685e3a2`。

主要結果：
- accepted additions：`1`
- source unchanged：true
- stem audio in master：false
- MASTER：約`-12.005 LUFS-I / -2.046 dBTP`
- MP3：約`-13.997 LUFS-I`

本人聴感：

> かなり改善。耳障りでないところを攻めて、十分ラウド。

---

## v51：evidence-preserving pruning

planner：`automatic-joint-lab-0.4.0`。

音響gateを緩めず、結果を変えられないSpleeter推論だけを削除した。

1. v50最終経路で使わないlegacy/base observer stageを除去。
2. relative-low scoreが改善不能ならobserverを呼ばない。
3. original sourceだけで拒否できるsame-f0候補をSpleeter前に落とす。
4. それでも決まらない候補だけpersistent Spleeterへ送る。

技術parity run `34697305740`：Ubuntu/Windows unit PASS、real Spleeter parity PASS。  
canonical v51 Windows bundle：
- promotion commit：`7e39e1460d7cba209187fe3d462b15064b7e2782`
- Frozen/roundtrip run：`34698184104` SUCCESS
- artifact ID：`10299492024`
- artifact ZIP SHA256：`85f946ae3aee6985e01286bbad89b27207e586126ae499ca5826359881a2dddd`

---

## 実曲06：境界で止める正例

対象：`06 - 03 返事は私.wav`  
source SHA256：`739a57c630e7ec3697a33b183723e9fa2768f8062e02e31cdc65dc051fb45031`。

- P01 end-to-end：`624.109秒`（約10分24秒）
- theoretical v50 observer calls：172
- v51 executed：3
- avoided：169
- tonal same-f0 candidates：67
- accepted additions：`0`
- final assessment：`ABSTAIN`
- MASTER：約`-12.002 LUFS-I / -2.016 dBTP`
- MP3：約`-13.995 LUFS-I`
- source unchanged / private uploadなし / stem混入なし

30Hz台の候補も、source vetoまたはrole/pitch/interior-frame条件で拒否。速度向上のために境界を緩めていない。

本人聴感：

> 速度はまずまず早くなった。音は文句なし。

---

## 実曲12：sourceだけで「何もしない」を確定する正例

対象：`12 - 私=AI-MY v4_edit delimit.wav`  
source SHA256：`896ea7ee36c13ad39355e8d46fd73c73eaceeb8c6b828b247e7f426f1958ced7`  
source：48kHz stereo / 9,991,063 frames / 約208.15秒。  
canonical reference.zip SHA256：`82d130a13a07db1c33e802b7286f507a65b4667972f974693bb4c229ff08773a`。

### 速度

- P01 end-to-end：`475.047秒` = 約`7分55秒`
- 実時間倍率：約`2.28x`
- theoretical v50 observer calls：`115`
- v51 executed：`0`
- avoided：`115`（100%）
  - obsolete base stage：48
  - source veto：48
  - zero reduction score：19

12ではneural observerを一度も呼んでいない。これは精度を捨てた省略ではなく、115件すべてがobserver結果によって最終判断を反転できないと事前に確定した結果。

### 音響判断

- automatically discovered events：966
- tonal same-f0 candidates：48
- accepted additions：`0`
- fallback accepted：0
- final assessment：`ABSTAIN`
- reduction assessment：`ABSTAIN`
- relative-low raw candidate：1.92秒
- `initial_excess_db = 0.0`
- `selected_strength = 0.0`
- zero-score short circuit：true
- old Note-Sub called：false

32〜39Hz台を含む弱基音候補も存在したが、`ABSTAIN_SOURCE_TOO_HARMONICALLY_BRIGHT_FOR_SUB_REPAIR` または `ABSTAIN_F0_NOT_WEAK_ENOUGH_FOR_REPAIR` でpre-observer拒否。不要なsubを生成しなかった。

### 完成音

- MASTER：`-12.00081 LUFS-I`
- MASTER TP estimate：`-2.02282 dBTP`
- MP3：`-13.99665 LUFS-I`
- MP3 TP estimate：`-3.73750 dBTP`
- MASTER SHA256：`e67839f4975030ceb131ee538ca4c07c92e56e5360fcba814103f7628bc188a1`
- LISTEN MP3 SHA256：`6064e87df781abd4c74306b0dce85546ea5ef75ce091c04998e1b9a3a31315f8`
- source unchanged：true
- private audio uploaded：false
- stem audio exported：false
- stem audio in master：false

本人聴感：

> かなり聴きやすくなったと思います。

### 12で確定したこと

12の改善感を「低域追加が効いた」と誤認しない。P03/P04は追加0・減算0であり、低域経路は**余計なことをしないことで完成音を守った**。完成音全体の改善は上流/下流を含むPDRM全体として評価する。

---

## P03/P04親受入

3曲で異なる状態を通した：

| 実曲 | 必要性 | P03/P04判断 | 本人聴感 |
|---|---|---|---|
| 11 | weak same-f0補強あり | 1件だけ作用 | PASS |
| 06 | 境界候補あり、証拠不足 | 0件 / ABSTAIN | PASS |
| 12 | 候補多数だがsourceで拒否可能 | 0件 / ABSTAIN、observer 0回 | PASS |

この3点で「作用する正例」「境界で止まる例」「完全に何もしない例」が揃った。合成試験だけではなく本人聴感もすべてPASSしたため、P03/P04親をDONEとする。

---

## 次：P05 #11

次の問いは低域gateをさらに調整することではない。

> **確定したP03/P04を一切いじらず、完成WAV/MP3の最終ピーク処理後でも『大きいが嫌味がない／聴きやすい』を維持できる最終候補を1つに固定できるか。**

P05では既存 `release_finish.py` / offline peak / OPPO系資産を棚卸しし、重複した処理経路を増やさない。最終ピーク処理以外の差を混ぜず、有限候補にしてから本人聴感を1回だけ求める。

利用者には現時点で追加操作を求めない。候補生成・技術gate・配布方法までこちらで先に整える。

---

## 完了を偽らない運転規則

- 合成/Frozen/CI成功を本人の音楽的合格の代用にしない。
- `ABSTAIN`や`0 additions`を失敗扱いしない。
- P03/P04のgateはP05都合で再調整しない。
- 私有音源を公開GitHub/CIへ送らない。
- sourceを変更しない。stem音声を完成音へ混ぜない。
- 次の判断を変えない追加分析はしない。
- P05は最終ピーク処理と完成ファイルの採否に限定し、通ればP08へ送る。
