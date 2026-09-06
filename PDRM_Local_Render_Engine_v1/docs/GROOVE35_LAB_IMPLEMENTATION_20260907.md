# PDRM Groove-First Low-End LAB v3.5 — 実装・初回検証

Date: 2026-09-07
Status: LAB_IMPLEMENTED / PRODUCTION_UNCHANGED / LISTENING_PENDING

## 1. 実装目的

低域の静的な量ではなく、発音イベントとevent-to-valleyの時間的コントラストを制御する。自動masteringで根拠のないoctave-downを作らず、必要なsame-fundamental補強だけを元演奏の包絡に従わせる。既存低域が過剰な場合はattackを保護しつつtail/floorを元2mix上で限定的に抑える。

## 2. 音声経路

Observerは解析専用。stem/proxy音声を出力へ混ぜない。

SOURCE 2MIX
- semantic observer: bass/drum attribution and confidence only
- physical path: HarmonicElasticity -> AUTO prep -> Groove Low-End -> HFTC -> final AUTO/OPPO

今回のLABでは真のseparatorモデルは同梱していない。`analyze_precomputed_stems()`は外部分離したbass/drum stemを受け取れるが、初回比較では保守的な2mix HPSS proxy observerを使用する。separator候補は別途、bass onset/offset・kick leakage・sparse-outro false bassで選定する。

## 3. 発音許可

- observer無し / confidence不十分: KEEP
- automatic octave-down: 禁止
- 0.8秒超の持続イベント: automatic sub禁止
- event-to-valley contrast不足: KEEP
- deep fundamental already sufficient: KEEP
- same-fundamental + bass confidence + event contrast + deep need: SUB_ACCENT候補

missing-fundamental repairは未実装。octave-downをKEEPにしているだけで、将来の厳格なrepair許可と混同しない。

## 4. 減算側

20–120Hzのstereo-linked低域を元2mix上で処理する。attack/strong peakを保護し、stable tail / low-floorでのみ最大3dBのtrim候補を生成する。exact digital silenceは維持する。

## 5. 量決定

旧Note-Subの固定比率だけで最大量を選ばない。same-fundamental追加は物理2mixでdeep/body不足とevent-to-valleyを測り、旧イベント振幅の最大35%以内に制限。さらに全体25–65Hz RMS増加を+0.12dB以内に制限する。

## 6. 既知負例・正例の初回比較

比較経路は、HE + front AUTOまでは共通。その後だけ old current Note-Sub と new Groove Low-End に分岐し、両方を定数ゲインで -16 LUFSへ合わせた。HFTCとfinal OPPOは両方で共通かつ今回変更していないため、比較から除外した。

固定区間:
- 08 微熱サーモグラフィ: 180–192s
- 11 Traces: 151–160s
- 12 私=AI-MY: 190–208s
- 06 返事は私: 40–52s（正例回帰候補）

Engineering metrics (listening approvalではない):

| case | old low/mid median dB | new | old temporal contrast | new |
|---|---:|---:|---:|---:|
| 08 | -2.2243 | -2.3426 | 16.1307 | 16.1870 |
| 11 | -7.9584 | -8.1002 | 17.1745 | 17.7024 |
| 12 | +4.8385 | +4.3329 | 7.5582 | 7.8207 |
| 06 | -3.35717 | -3.35717 | 18.05185 | 18.05185 |

Tracesの既知false event (absolute 155.42–156.06s) は、旧制御の約110Hz→55Hz octave-down生成を新制御が `automatic_octave_down_prohibited` でKEEP。-16 LUFS比較音の30–65Hzは old約-39.37 dBFS → new約-84.23 dBFSとなり、元の静けさに近い状態へ戻った。

11 new decisions:
- 153.80–154.08s: same-fundamental約49Hz、SUB_ACCENT scale約0.349
- 155.42–156.06s: 110→55Hz、KEEP octave-down prohibited
- 158.48–158.68s: 87.5→43.8Hz、KEEP octave-down prohibited

12:
- old 2 events → new 0 events
- trim mean 0.316dB, max 2.253dB
- same-fundamental候補はevent-to-valley -4.54dBのためKEEP

08:
- old 2 events → new 0 events
- trim mean約0.109dB。全体を痩せさせる処理ではなく軽いtail/floor修正。

06 positive control:
- old 1 octave-down event → new 0 event
- trim mean 0.0084dB
- global low/midとtemporal contrastはほぼ不変。聴感上のregressionがないか盲検で確認する。

## 7. 回帰試験

新規10件:
- octave-down禁止
- observer無しはKEEP
- low confidenceはKEEP
- same-fundamental transientは条件を満たせば補強可能
- sustained eventはautomatic sub禁止
- trim planのconstant-gain invariance
- attack保護とtail trim
- exact digital silence
- precomputed stem shape mismatch拒否
- stem observerは解析値のみ・source不変

ローカル curated regression: 66 tests PASS。対象は新Groove、Note-Sub v0.2/v0.2.1、HFTC、AUTO policy、corrected context-ms contract。

## 8. 未完了 / production昇格条件

- actual separatorはまだactiveではない。
- proxy observerはsemantic truthではない。
- 4ケースのblind listening approval前にproductionを置き換えない。
- separator導入時はSDRではなくbass onset/offset、kick leakage、false bass、f0 trajectoryでbenchmarkする。
- HFTC/HE/OPPOのDSP核は今回変更しない。

Production昇格条件: 08/11/12で改善、06正例でregressionなし、その後5–10本の既存良好曲に拡張して同時検証する。
