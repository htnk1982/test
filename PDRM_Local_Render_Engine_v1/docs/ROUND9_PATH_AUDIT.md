# Round 9 経路監査 — Cを変えずに原因を切り分ける

## 今回行うこと

C=HarmonicElasticityを試聴基準として保持する。Controlだけがオーバーサンプリング経路を通っていなかったため、非線形処理をゼロにした「上げ下げだけ」の対照を補う。これはRound 10の新音作りではない。

機械的に調べる範囲:

- 同じ入力・設定から現在のCとControlを再現できるか（PCM24の2LSB以内。聴感閾値ではない）。
- 4倍の上げ下げだけの作用、およびその経路とCの差。
- Stereo両チャンネルの帯域別エネルギー。mono合成で差を隠さない。
- 実際に試聴した既存A/B/CのMP3を復号したLUFSとTP推定。
- 同一の現在のencoderで比較3経路を再エンコードした場合のレベル差。
- 44.1/48kHzの合成正弦波によるリサンプリング経路の周波数応答。

数値は疲労・艶・好みの直接測定ではない。Cを採用した判断は変えない。残差RMSの比を「改善の何割がフィルタ」と解釈しない。

## 導入 — 再インストールしない

既存の、正常にRound9を生成した `PDRM_Local_Render_Engine_v1` フォルダをそのまま使う。

1. この版の `round9_path_audit.py` と `round9_path_audit.cmd` **2ファイルだけ**を、既存の `round9_lab.cmd` と同じ場所へコピーする。
2. `Round9_Output` 内の、試聴に使った `Round9_...` フォルダ、またはその中の `manifest.json` を `round9_path_audit.cmd` にドラッグする。WAV/MP3ではなく、既存のjobを指定する。
3. 処理終了時に示される `AUDIT_REPORT.json` を共有する。今は追加試聴しなくてよい。

`setup.cmd`、既存selftest、doctor、実音源acceptanceを無条件にやり直す必要はない。
既存ソースを上書きしない。新規の2ファイルだけを追加する。

## 出力先

```text
%LOCALAPPDATA%\PDRM_Local_Render_Engine_v1\round9_path_audit\audit_<fingerprint>\
    AUDIT_REPORT.json
    AUDIT_REPORT.md
    heartbeat.json
    filter_only_matched.wav
    c_reconstruction.wav
    codec\
    chunks_filter\
    chunks_c\
```

Cの既存WAV/MP3には書き込まない。勝者を再エンコード版へ勝手に交換しない。

## 中断と再開

2秒間隔のheartbeatと各chunkの進捗を表示する。未完成ファイルは監査先だけに置く。
入力・設定・ライブラリ・ソースコード・元出力のhashをjob識別に含め、完了済みchunkはhashが合えば再利用する。
同じjobの二重起動はOSファイルロックで拒否する。再実行でロックやDBを強制削除しない。
この監査はSQLiteを使わず、production runtime/Safety Shell/lockを変更しない。

## 異常時

元jobとの不一致、Cの再現不一致、NaN、メモリ不足などは止める。
監査開始後の例外は原則として `AUDIT_REPORT.json` にstageとtracebackを保存する。
指定ファイル不足など監査先確定前のエラー、書込先そのものの障害は画面に表示する。
同じエラーの再試行は連打せず、レポートか画面のエラーを保存する。

## 証拠の限界

- 手元の実音源測定結果はこの手順書には含まない。
- 合成信号テストの結果を、利用者の曲の測定結果と呼ばない。
- 既存MP3の旧encoderバージョンは、過去のmanifestが保存していなければ確定できない。
- 0.10 LUは比較上の再確認フラグであり、聴覚上の普遍的な検知限界ではない。
- この追加ツールのCIテストは別途確認する。既存の35件PASSだけを、新コードの検証証明に流用しない。

## 参照

- SciPy resample_poly: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.resample_poly.html
- 元のRound9 operators blob: 7821843f0ebed04101fc2223b20509fa2107317b
- 試聴決定記録: ROUND9_DECISION_20260905.md
