# PDRM Integration42 — Windows QA EXE実行までの確定結果

日付: 2026-09-10
状態: 共通予算・物理再確認・完成チェーン・QA専用Windows EXEを実装/実行。製品版EXEの出荷承認ではない。
この記録は`INTEGRATION42_JOINT_STATUS_20260910.md`第7節の「進行中」を更新する確定記録。

## 1. 実装と実行の範囲

`joint_lowend_v42.py`は、従来の広域FIRカットと新しい狭帯域尾部カットを同じ物理音声から描画し、重複する要求を単純加算しない。個々の狭帯域処理は固有の発音範囲と内部の未支持区間を守る。狭帯域要求なしでは既存広域経路へ直接委譲し、全KEEPでは低域段の入力ファイルを全バイト保存する。

`physical_decay_bridge_v42.py`は原音で支持された尾部候補をHE/AUTO後の音で再確認する。原音に欠点があっても物理音声で解消済みなら追加減算しない。原音の観測hashを前処理音へ付け替えず、元音/物理音/時計対応を保持する。

フレーム応答上の共通上限2dB、狭帯域最大要求1.5dBは工学的な制御予算である。完成波形の全局所スペクトル・TP・主観品質に対する厳密な保証とは異なる。元の発音の頭や対象外の保護は低域描画段で確認し、最終音量調整まで一切変わらないという主張はしない。

既存HE/HFTC/OPPO/AUTO・GUI・processed保存・本番EXEは未変更。変更した既存ファイルはLAB入口`integrated_finish_v40.py`で、明示した`joint-v42`を選べるようにした。旧Note-Subを後ろに残す構成ではない。

## 2. ソフトウェア・音声試験

基準: `1b651fbb5f752a99dfff3c49791df0ad2154c4bc`。
DSP/試験確認commit: `0aedb53d057012a958407dedec579ec6b116c267`。
Windows/Ubuntu CI: `34421677729`、両方成功。

既存277件+新規38件=315件。失敗0、エラー0、スキップ0。
重複カット、分割描画一致、原音/出力保護、発音の頭、内部の未支持区間、前処理で解消済みの候補、サンプルレート時計、キャンセル清掃などを検査した。

4秒・48kHzの合成音について、既知の局所発音と明示的な合成観測を使い、既存HE/HFTC/AUTO/WAV/MP3まで通した。神経モデルや本人音源は使用していない。

完成WAVの固定区間1.6〜3.0秒の320Hz/640Hz比は、無修正11.879316dB、尾部修正10.435185dB、広域+尾部修正10.435161dB。これは対象成分と関連成分の比であって、不快さの尺度ではない。低域修正後に最終AUTO経路も変わるため、差約1.444dBを狭帯域単独の純粋な効果とは扱わない。

無修正はOPPO、修正後と欠陥なし原版はLIMITER_FALLBACKになった。保存後のLUFS/TPは指定範囲内だった。リミッター移行を隠さず、また移行したことだけで音質悪化と断定もしない。最終的な採否はこの相互作用を含む音声で決める必要がある。

## 3. 実際のWindows EXEを作成・起動した

QA build commit: `3c779edadfd0718cae9ca4afc6c57a301a2286ff`。
CI: `34421846123`、job `102698772540`、成功。
PyInstaller6.22.2、hooks-contrib2026.7、Windows Server2022、Python3.12.10。

QA専用の`PDRM_JOINT_QA.exe`をonedir形式でビルドし、checkout外の日本語・空白を含むフォルダへコピーした。空の別作業ディレクトリから起動し、PATHからPython/外部FFmpegを外した条件で、同梱ランタイムと同梱FFmpegによる5ケースを完走した。

同じWindows環境でソース版も実行し、各ケースの完成WAVの復号PCM hash、MP3全バイトhash、FFmpeg hash、前段/最終/codec経路を比較。以下の全5ケースで全項目が一致した。

| ケース | WAV復号PCM | MP3全バイト | 処理経路 |
|---|---|---|---|
| 無修正 | 一致 | 一致 | 一致 |
| 尾部のみ修正 | 一致 | 一致 | 一致 |
| 広域+尾部 | 一致 | 一致 | 一致 |
| 欠陥なし原版の低域KEEP | 一致 | 一致 | 一致 |
| 共同処理・-10LUFS負荷条件 | 一致 | 一致 | 一致 |

これは、Pythonをホストからアンインストールした試験やOSによるネットワーク遮断試験ではない。モデル推論・全曲の自動成分関連付け・製品GUI・長時間バッチの合格ではない。

exe SHA256: `d48eb6378a1d10e3bde7cebe7e7e37446bb2aef4e1ec4eedb72ba4487a2ada3f`。
exe10291202bytes、フォルダ全体221037690bytes。QAバイナリは実行後にジョブ内で削除し、製品版として配布しない。

## 4. 成果物

最終artifact `pdrm-joint42-windows-frozen-evidence`、ID10131264312。
ZIP428723bytes、SHA256 `0302ddcebd4e6c75d20564c6a6fcfda637dce9ad6949c1365da0a8c15e99fa8f`。

含むもの：日本語Markdown2本、315件の結果、5ケースの完成音測定、ソース対EXE比較、ビルドspec、依存版、実行ログ、コード/試験。
含まないもの：製品EXE、モデル重み、本人の音源/Excel/参照atlas。

音声側主要版はnumpy2.3.5、scipy1.17.0、soundfile0.13.1、pyloudnorm0.2.0、imageio-ffmpeg0.6.0、psutil7.0.0。build側の依存を含む実解決版を成果物のENVIRONMENT_LOCKへ保持した。将来の無固定更新を同じビルドとみなさない。

## 5. 残る中心課題

実曲での対象成分の自動関連付けと、レビューに対応した量校正は未完了。局所発音・校正・支持を与えれば動く今回の修復枝と、前回の自動広域plannerがあることをもって、すべての実曲を音楽的に判断できたとはしない。

同一基音の加算は共通予算へ未接続。用途を確認した観測モデルの選定とWindows実推論、最終音候補の採否、GUI/processed/強制終了再開/長時間バッチの製品統合が残る。

今回の実行環境はGitHub Actions。ローカル環境は応答せず、本人音源は外部へ送らなかった。実曲改善・主観合格・新しいマスタリングEXE完成は主張しない。

検討上の焦点：修正単体の指標だけではなく、最終段で必要なピーク処理がどう変わり、その結果として音楽的な利益が残るか。最終AUTOまで通した候補比較を出荷条件から外さない。

## 根拠

このrepoの上記実装・CIログ・生成されたTEST_RESULTS/SUMMARY/FROZEN_RESULTS。
PyInstaller一次資料: https://pyinstaller.org/en/stable/runtime-information.html 、https://pyinstaller.org/en/stable/hooks.html 。
SciPy再構成条件: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.istft.html 。
外部資料は数値手法と配布方式の根拠であり、PDRMの音楽的な品質保証ではない。
