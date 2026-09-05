# HFTC v0.1 — 高域の時間コントラスト単一実験

日付: 2026-09-05
状態: 実験コード。音質採用ではなく比較候補。

## 目的と境界

採用済み `SUB_AUGMENTED.wav` を不変の対照として、8–16 kHzの弱い時間帯だけを少量減衰させる。Note-Subの再適用、低域追加量変更、全帯域圧縮、1.2–4 kHz処理、M/S処理は行わない。

音声を公開repoへ保存しない。本番 `pdrm_engine/`、`pdrm_runtime/`、`pdrm_operator_lab/` およびNote-Sub各ファイルは変更しない。

## 実装

- `coefficients` / `extract_band`: 20 ms長の奇数タップ線形位相FIR。カットオフは8.3/15.7 kHz、8/16 kHz内側に遷移帯域を置く。整数遅延を補償して原波形へ差分加算する。
- `analyze_control`: 20 msのL/R平均パワー、5 ms高速検出、5 ms制御グリッド。2秒局所窓のP50/P90を使用する。入力サンプルレートは維持する。
- `plan_gain`: 局所P90から3 dB以内と立ち上がり候補を保護し、弱い区間の帯域枝ゲインを最大1 dBだけ減衰。30 msの前後ガードと60 msの平滑化を使用する。
- `render_raw`: 一つの全曲制御曲線とFIRコンテキストを使い、8秒ごとに保存。音声ハッシュでチャンクを検査し、中断後は確定済みチャンクを再利用する。
- 原波形に対し `raw = B + (gain(t)-1)*band(B)`。L/Rで同じゲインを使うがチャンネルは混合しない。正確なデジタル無音位置へFIRの尾を追加しない。
- 最後に候補の全曲LUFSを対照Bへ合わせる。レベル合わせの共通ゲインだけは全帯域へ作用する。

これは理想的な矩形帯域処理ではない。FIRの遷移帯域・時間変調の漏れは測定対象。帯域枝のゲイン上限を、混合音各サンプルの振幅上限や主観的変化量と混同しない。

## 検証するもの

24件のHFTC試験と、既存43件のNote-Sub試験を独立に実行する。

無音、0強度のPCM一致、帯域外純音、一定高域での無処理、弱音減衰と強音保護、立ち上がりガード、L/R比例・逆相、遅延補償、解析/描画分割、チャンク中断再開と破損、元音保持、入力ハッシュ、非有限値、音量・MP3・冪等性、改変結果の上書き拒否を検査する。

チャンク幅を変えたレンダリング比較は最大絶対差1e-7以下、同一設定での中断再開はPCMハッシュ一致を要求する。別OS・ライブラリ間のbit一致までは主張しない。

合成試験PASSは実曲の音質承認ではない。原音の上書きや本番runtimeの変更を正当化しない。

## 再現する場合のみ

既存の動作環境へ `hf_temporal_contrast_lab.py` と `hf_temporal_contrast.cmd` を追加し、既存 `note_sub_lab.py` をそのまま使用する。依存ライブラリの追加はない。

`hf_temporal_contrast.cmd` を起動し、採用済み `SUB_AUGMENTED.wav` を選ぶ。manifestや旧Cを選ばない。入力は既知SHA-256で固定されている。

出力は `%LOCALAPPDATA%\PDRM_Local_Render_Engine_v1\hftc_lab\hftc_...\RESULT`。ソースと同じディレクトリ内への出力は拒否する。音声を外部へ送信する処理はない。

## 聴くもの

`PDRM_HFTC_v01_BLIND_MP3.zip` のX/Yのみを先に比較する。正体は `REVEAL_AFTER_LISTENING.txt` に別保存する。今回は前のA/Bと区別するためX/Yという名前を用い、対応をランダムにしてジョブ単位で保存する。

評価は「Xが良い / Yが良い / 差が分からない / 問題あり」。差を探すための長い反復試聴や音量増加は要求しない。分からない場合は採用済みBを維持する。

## 仮説・限界

1. 参照の時間コントラストとの差は編曲や音色でも生じる。欠陥診断ではない。
2. 強いエネルギーや立ち上がり候補は検出するが、ハイハットや子音を意味的に識別していない。すべてのアタックや定位が知覚的に不変とは保証しない。
3. 前回Bが選ばれたという事実だけで、改善の因果機構までは特定できない。局所低域補完が寄与したという説明は仮説として扱う。
4. 最大1 dBの微小実験で、参照の約6–7 dBのコントラスト差を埋めることは目標にしない。
5. 一定高域には減衰しない設計であり、ノイズ除去器でも恒常的な高域シェルフでもない。
6. 本番runtime統合・Note-Sub default変更は行わない。HFTCが勝つと確定するまでは比較候補のまま保持する。

## 実装APIの一次資料

- SciPy `firwin`: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.firwin.html
- SciPy `oaconvolve`: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.oaconvolve.html
- SciPy `percentile_filter`: https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.percentile_filter.html

これらはAPI動作の根拠であり、本実験の聴感改善を裏付ける資料ではない。
