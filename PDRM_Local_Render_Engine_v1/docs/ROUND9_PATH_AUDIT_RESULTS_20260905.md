# Round 9 経路監査 — 実装・合成信号測定結果

日付: 2026-09-05
状態: 監査ツール実装・CI確認済み／利用者の実音源の監査は未実施
検証対象コードcommit: `629670b57a0220081758394c2977e27b6059afe4`

## 結論

C=HarmonicElasticityを勝者として保持する。Cの音、元のRound9出力、本番DSP、耐障害runtimeは変更していない。

「4倍の上げ下げだけでも信号が変わる」は合成正弦波で確認した。ただし、これだけでCの疲れなさをフィルタに帰属することはできない。現時点で実施したのは、公開実装の経路測定と監査ツールのテストであり、利用者の楽曲の測定ではない。

## 合成信号によるリサンプリング往復測定

条件: 1秒の単一正弦波、振幅0.1、非線形写像なし、4倍アップ／ダウンサンプリング、Kaiser beta=10.5、前後100msを除外してRMS比を算出。LUFS再正規化はしない。

| 周波数 | 44.1kHz入力の往復gain dB | 48kHz入力の往復gain dB |
|---|---:|---:|
| 100Hz | 0.000000 | 0.000000 |
| 1kHz | -0.000019 | -0.000016 |
| 8kHz | +0.000017 | -0.000039 |
| 12kHz | +0.000083 | -0.000065 |
| 16kHz | -0.026815 | -0.000192 |
| 18kHz | -0.577750 | -0.076150 |
| 20kHz | -3.107043 | -0.856344 |
| 21kHz | -5.003951 | -1.917292 |
| 22kHz | 未測定 | -3.511738 |

Windows/Python3.14.7の実行ログで上記数値を確認。初回Ubuntu/Python3.12の計算でも表示した6桁精度で同じ値だった。

解釈を限定する:

- 48kHzでは、測定した100Hz〜16kHzの定常正弦波レベルはほぼ不変。高域端の変化は測定できた。
- 44.1kHzでは同じ絶対周波数でも高域端の変化が大きい。
- これは任意の曲のハイハット、ボーカル、疲れなさを直接測定したものではない。
- 「広い帯域を削っただけでCが良くなった」「フィルタは無関係」のどちらもまだ断定しない。
- 今のCにさらに高域カットを足したり、フィルタを高性能版へ取り替えたりしない。

## 新しい監査ツール

追加するのは次の2ファイルのみ。

```text
round9_path_audit.py
round9_path_audit.cmd
```

既存jobのmanifest、state、各WAVのSHA-256、blind対応を照合する。保存されたbaselineと設定からControlとCを再現し、現在のWAVとの差を調べる。再現差がPCM24の2LSBを超える場合は、違う音へ原因を帰属しないよう停止する。この許容値は数値再現の検査値であり、聴覚の閾値ではない。

比較する3経路:

1. 既存Control（Round9 B）
2. 4倍の上げ下げだけ、非線形写像なし、同じLUFSへ調整
3. 既存HarmonicElasticity（Round9 C）

計測: PCMレベル、TP推定、帯域別エネルギー、各差分RMS、既存試聴MP3の復号後レベル、同一encoderで再生成した3経路の復号後レベル。

差分RMSは好みの点数ではない。また、差分同士には相関・交差項があるため、「何割の改善がどの処理」といった足し算には使わない。

## 運用

- 元の音源・CのWAV/MP3・本番core・runtimeへ書き込まない。
- 2秒heartbeat、chunkごとの進捗、hash付きchunk再利用。
- 別プロセスの同時実行をOSロックで拒否。
- SQLiteを使わず、作業先は原則LOCALAPPDATA配下。
- Cの再現確認用WAVは監査フォルダ内だけに保存し、採用済みCを置き換えない。
- 既存MP3を再び次世代masterの入力にしない。
- 監査用の一時音声が複数生成されるため、LOCALAPPDATA側に余裕を持った空き容量を用意する。4分程度の48kHzステレオでは1GB程度が目安（入力長とcodec生成物で変わる）。

## CIの確認

実行: https://github.com/htnk1982/test/actions/runs/33939194601

| 実行環境 | Unit tests | 合成信号計測 | 追加ツールZIP生成 |
|---|---|---|---|
| Ubuntu / Python3.12 | success | success | success |
| Windows / Python3.12 | success | success | success |
| Windows / Python3.14 | success | success | success |

スイートは既存35件＋新規10件。Windows/Python3.14ログは `Ran 45 tests in 53.674s / OK`。

追加検証は、元経路との一致、中断後のchunk再利用、改変chunkの再計算、0強度がfilter-onlyと一致すること、合成信号の識別、元job不変、二回目の再計算抑制、改変ソース拒否、出力先分離、MP3復号後計測、OSロックを含む。複数の検証項目を含むテストがある。

初回CIでWindowsの監査用一時WAVのfsyncに不適切なread-only handleを使っていた不具合を検出。監査先の一時ファイルをread/write handleで開くよう修正し、上記の再試験でsuccessを確認した。利用者へ試行を依頼する前に修正済み。

CIはWindows Server環境であり、利用者のWindows11＋実音源での監査完走を代替する証拠ではない。

## 取得と実行

追加ツールartifact（GitHubログインが必要な場合がある。保存期限は2026-10-05）:
https://github.com/htnk1982/test/actions/runs/33939194601/artifacts/9961231365

外側のartifact ZIP内に `PDRM_Round9_Path_Audit_AddOn.zip` がある。それを展開し、上記2ファイルだけを、既存の動作済み `round9_lab.cmd` と同じ場所へコピーする。

既存の `Round9_Output` 内の試聴した `Round9_...` フォルダ、またはその `manifest.json` を `round9_path_audit.cmd` へドラッグする。WAV/MP3をドラッグするのではない。

`setup.cmd`、selftest、doctor、実音源acceptanceをやり直す必要はない。既存の仮想環境を使う。

レポートは原則として以下に出る。

```text
%LOCALAPPDATA%\PDRM_Local_Render_Engine_v1\round9_path_audit\audit_<fingerprint>\AUDIT_REPORT.json
```

現在は追加試聴を依頼しない。まずこのJSONだけで、フィルタ経路差、非線形処理を含む残差、実際の試聴MP3の音量差を確認する。

## 今回完了／未完了

完了: 追加ツール、回帰テスト、合成正弦波測定、追加ファイルのみの配布。
未完了: 利用者の実音源における経路差分・MP3復号後計測。その結果を捏造していない。
継続: Cを試聴基準として保持する。大きさ・張り・艶・抜け・低域の底・疲れなさの両立という目標は変更しない。
