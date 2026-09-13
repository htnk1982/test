# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-13 / revision 11  
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`  
親Issue：#2。

## 現在地

**P01〜P07はDONE。P08最終候補は本人Windows実機の通常GUI経路で実曲処理まで正常動作した。残るrelease gateは、今回変更したWAV既定値 `-10 LUFS-I / -0.5 dBTP` の完成音を本人が最終聴感確認することだけ。**

| ID | 状態 | 根拠 / 残ること |
|---|---|---|
| P01 私有実音源・レビュー実行基盤 | **DONE #3** | 私有実曲でmanifest＋本人聴感を回収済み |
| P02 配布用observer | **DONE #8** | isolated Spleeter runtime実推論PASS |
| P03 発音・役割・必要量の自動判断 | **DONE** | 11/06/12で作用・境界停止・完全ABSTAINを本人聴感PASS |
| P04 加算・広域/狭帯域統合 | **DONE** | 必要時1件 / 不要時0件を実曲確認 |
| P05 完成WAV/MP3最終ピーク処理 | **DONE #11** | `auto-peak-v3.4.0` を採用 |
| P06 GUI/進捗/キャンセル | **DONE #6** | 最終GUIへ統合済み |
| P07 保存・退避・復旧・batch | **DONE** | A #4 / B #5 / C #7完了 |
| P08 製品Windows EXEと最終受入 | **FINAL CHECK #12** | 本人PC通常GUI・実曲処理PASS。最終聴感のみ |

## 最終候補の仕様

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

## 本人PCで発見・修正した最終障害

旧候補では、DSP workerが正常に処理継続中でも、Windows上で `status.json` が一瞬ロックされるとGUIが `PermissionError` を致命的障害と誤認していた。

修正：
1. `gui-runtime-v0.2.2` で status readをbounded retry。
2. telemetry読取失敗をDSP失敗と分離。
3. workerが生きている限りGUIは処理継続。
4. worker終了後だけterminal status / exit codeで最終判定。
5. 異常時は `PDRM_DIAGNOSTIC.zip` を生成。

この修正版を本人PCで再実行し、本人報告：

> 問題なく動きました

したがって **実機起動・GUI・worker・precomputed calibration・実曲処理のruntime gateはPASS**。

## final candidate identity

- commit：`f7bc80c35fad8216f52c443e4995f630b4f35619`
- run：`34740096874`
- artifact ID：`10311564114`
- artifact ZIP SHA256：`7d44afdb6e5b24cbc4532748788e4bf7ca100f1a09c4e17f7857601755a40c35`
- observer runtime manifest SHA256：`97189055de8486501cad720562e467af5c97129ce9bfa1dab91813866c6e1d0c`
- product calibration SHA256：`b2c094d02e6da731c9953ea65f7d2c4fcba7b31b588b6049af86aa0e2d97399f`
- historical P01 accepted calibration SHA256：`0e258cf233e07e664f7eb56d5e161c20b270211a322282af88efa494993279e1`

## CI境界

build-time Frozen self-test、Spleeter native runtime self-test、status telemetry retry unit testはPASS。artifact再download後のFrozen main EXE self-testだけは別runnerで早期終了する既知事象が残るが、唯一の利用者本人PCでは通常GUI実曲処理がPASSしたためrelease blockerにはしない。

## 最後の問い

今回WAV defaultを旧 `-12 / -2` から `-10 LUFS-I / -0.5 dBTP` へ変更しているため、**完成WAVを本人が聴いて音も問題ないか**だけはruntime成功と分けて確認する。

- 音も問題なし → P08 DONE / #12 close / 親#2 release-ready close
- 問題あり → P03/P04は触らず、P05最終peak/target境界だけを再検討

これ以外の追加試験は要求しない。
