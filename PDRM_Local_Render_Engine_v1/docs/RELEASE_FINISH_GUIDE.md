# PDRM 配信用仕上げ v1.1

日付: 2026-09-05

## 新しい依頼と境界

利用者は、完成WAVを−12 LUFS、True Peak上限−2 dBTPへゲインとピーク処理で揃え、その完成WAVから−14 LUFSのMP3を追加することを明示的に依頼した。
旧入口の「リミッターを使わず音量を下げる」方針を、この新しい配信用入口では変更する。Note-Sub v0.2.1、HFTC v0.1、accepted_finish v1、本番runtimeは変更しない。音源を公開repoへ保存しない。

## 出力

- `FINISHED_-12LUFS_-2dBTP.wav`: 全曲−12 LUFS-I ±0.03 LU、True Peak数値推定は−2 dBTP以下。元のサンプルレート、ステレオ、24-bit PCM、決定的TPDFディザー。
- `FINISHED_-14LUFS_320kbps.mp3`: 上記の完成WAVを読み、一定ゲインで−14 LUFS-I ±0.03 LUへ調整して320kbps MP3化。復号後もLUFS/ピーク/長さを確認。

−2 dBTPは上限。余裕のある音のピークを無理に天井へ近づけない。MP3側は追加リミッターを使わず、WAVが−12なら基本−2 dBの一定ゲインだけ。符号化後の誤差を直す際も同じ定数ゲインだけ変更する。MP3のTPも−2 dBTP以下を検査する。

## 操作

配布ZIPの`pdrm_release.cmd`、`pdrm_export.cmd`、`PDRM_Release_v1_1`フォルダを、既存の`.venv`と`round9_lab.cmd`がある場所へ置く。旧ファイルを置換しない。依存追加・pip・doctor・selftestは不要。

- 元のWAV/FLAC: `pdrm_release.cmd`。Note-Sub→HFTC→音圧仕上げ→WAV/MP3。
- 既にNote-Sub/HFTC済みの完成WAV: `pdrm_export.cmd`。音作りを再適用せず、音圧仕上げ→WAV/MP3のみ。

どちらもダブルクリックで複数ファイルを選択できる。結果は`%LOCALAPPDATA%\PDRM_Local_Render_Engine_v1\release_finish_v1_1`内。`LAST_RUN.md`で各曲の保存先を確認できる。

`release_finish.py --finished input.wav`は同じ完成WAVモード。MP3をマスター入力にしない。書き出した−12 LUFSの同じ出力へ再適用しない。

## 実装

旧accepted_finishの入口準備と2段の音作りはそのまま。後段に次を追加する。

1. 必要ゲインだけで−12 LUFS/TP天井を満たせる音はリミッターをバイパス。
2. 必要な音だけFFmpegの4倍オーバーサンプリング＋先読みalimiter。attack 5 ms、release 50 ms、左右リンク、auto makeup OFF、latency補償ON。内部天井に0.05 dBの余裕。
3. 元レートへ戻してPCM24を保存し、既存4倍と新8倍補間の大きいTP推定値を用いて検査。
4. 最大8回、元の同じリミッター前音源からゲイン・天井だけを再調整。候補に処理を重ねない。両目標が成立しなければ未出力。
5. 完成WAVから定数ゲインでMP3化し、復号して検査。WAVハッシュの不変と変換元の対応を記録。

WAVは44.1/48/88.2/96 kHz対応。MP3のみ、高レートWAVを44.1/48 kHzへ変換する。通常レートの長さは完全一致、高レート変換の丸め差は最大1サンプルまで。

## 保存と検証

元音声非破壊、完了時のみRESULT公開、同じ入力と設定の再実行でハッシュ照合、改変RESULTの上書き拒否、出力PCMの再投入拒否、途中再開を維持する。

既存84件に23件の回帰を追加。新規対象は同時LUFS/TP達成、バイパス、MP3変換元、サンプル間ピーク、遅延と末尾、左右比例、PCM24決定性、異常入力、再実行、途中再開、有限回不成立時の未出力など。試験結果の実行数と成功はCIの結果JSONで確認する。

音圧の新しい仕上げは、ピーク圧縮が必要な曲の波形を変える。聴き疲れが不変だとは保証しない。測定は数値推定であり、全ての認証測定器との完全一致は主張しない。旧3曲比較音源の未知の共通ピーク前処理を再現したものでもない。

技術仕様の根拠: FFmpeg libavfilter/af_alimiter.c、SciPy signal.resample_poly、pyloudnormのBS.1770ラウドネス実装。これらは音質改善の証明ではない。
