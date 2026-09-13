# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-13 / revision 12  
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`  
親Issue：#2。

## 結論

**P01〜P08すべてDONE。最終Windows EXEは、唯一の利用者本人PCで通常GUI経路の実曲処理を完走し、完成音も本人聴感PASSした。PDRM更新EXEはrelease-ready。**

最終本人報告：

> 問題なく動きました

> 音も問題なし

| ID | 状態 | 最終根拠 |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **DONE #3** | 私有実曲でmanifest＋本人聴感回収 |
| P02 配布用observer | **DONE #8** | isolated Spleeter runtime実推論PASS |
| P03 発音・役割・必要量の自動判断 | **DONE** | 11/06/12で作用・境界停止・完全ABSTAINを本人聴感PASS |
| P04 加算・広域/狭帯域統合 | **DONE** | 必要時1件 / 不要時0件を実曲確認 |
| P05 完成WAV/MP3最終ピーク処理 | **DONE #11** | `auto-peak-v3.4.0` policyを採用 |
| P06 GUI/進捗/キャンセル | **DONE #6** | 最終GUIへ統合・実機PASS |
| P07 保存・退避・復旧・batch | **DONE** | A #4 / B #5 / C #7完了 |
| P08 製品Windows EXEと最終受入 | **DONE #12** | 本人PC通常GUI実曲完走＋完成音本人聴感PASS |

## 最終製品仕様

- planner：`automatic-joint-lab-0.4.0`
- renderer：`joint-v46`
- finalizer：`auto-peak-v3.4.0`
- finalizer policy：`GAIN_ONLY -> OPPO -> LIMITER_IF_OPPO_NOT_FEASIBLE`
- observer：isolated Spleeter 4stems。stemは解析証拠のみでmasterへ混ぜない
- reference calibration：canonical 24曲を開発側で事前計算し、derived numerical metadataだけ同梱。利用者PCで `reference.zip` / `REFERENCE_CALIBRATION` は不要
- WAV default：`-10.0 LUFS-I / -0.5 dBTP`
- MP3 default：`-14.0 LUFS-I / -1.0 dBTP`
- LUFS / TP：0.5 dB刻み、TP上限 `-0.5 dBTP`
- source上書き禁止
- runtime model download禁止
- user側Python/TensorFlow/Spleeter導入不要
- 異常時：`PDRM_DIAGNOSTIC.zip` を生成

## 最終候補 identity

- commit：`f7bc80c35fad8216f52c443e4995f630b4f35619`
- run：`34740096874`
- artifact ID：`10311564114`
- artifact ZIP SHA256：`7d44afdb6e5b24cbc4532748788e4bf7ca100f1a09c4e17f7857601755a40c35`
- observer runtime manifest SHA256：`97189055de8486501cad720562e467af5c97129ce9bfa1dab91813866c6e1d0c`
- product calibration SHA256：`b2c094d02e6da731c9953ea65f7d2c4fcba7b31b588b6049af86aa0e2d97399f`
- historical P01 accepted calibration SHA256：`0e258cf233e07e664f7eb56d5e161c20b270211a322282af88efa494993279e1`

## 最終実機障害と解消

前候補では、DSP workerが処理継続中でもWindowsが `status.json` を一時ロックすると、GUIが `PermissionError` を致命的失敗と誤認していた。

`gui-runtime-v0.2.2` で以下を実装：
1. status readのbounded retry
2. telemetry failureとDSP failureの分離
3. workerが生きている限り処理継続
4. worker終了後だけterminal status / exit codeで最終判定
5. 異常時診断ZIP生成

修正版を本人PCで再実行し、通常GUI・実曲処理・完成音をすべて本人がPASSした。

## CI境界 / 非blocking技術債務

build-time Frozen self-test、Spleeter native runtime self-test、status telemetry retry unit testはPASS。artifact再download後の別GitHub Windows runner上でFrozen main EXE self-testが早期終了する既知事象は残る。

ただし利用者は1名で、その本人PCの実使用経路がPASSしたためrelease blockerにはしない。runtime約1.93GBの削減とfresh-runner一般化は将来の最適化課題であり、現releaseの完了条件ではない。

## 最終判定

**RELEASE READY / P08 DONE / 親#2 DONE**

今後の変更は、この受入済みartifactを基準版として、明確な新要件または実使用上の反証が出た場合のみ別課題として扱う。