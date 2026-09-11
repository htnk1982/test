# PDRM 更新EXE：課題台帳・進捗の正本

更新：2026-09-11 / revision 3
repo：`htnk1982/test` / branch：`pdrm-note-sub-lab-v1`
親Issue：#2。

## 現在地

**運用基盤P07は完了、GUI基盤P06-Aは完了、同一基音の技術接続P04-Aは完了。出荷の主戦場はP02/P03/P05/P08へ移った。P01の私有実曲実行環境は引き続きBLOCKED。**

管理資料・試験件数そのものを進捗に数えない。下表の受入条件を閉じたものだけDONEとする。

| ID | 出荷に必要な成果 | 状態 | 実行根拠 / 次の一点 |
|---|---|---|---|
| **P01** | 私有実音源・レビューを非公開環境で新経路に通す | **BLOCKED / #3** | ローカルPython/containerのTransportTimeout。復旧時に既存素材manifest→実曲1件を最優先 |
| **P02** | 配布条件の明確な解析observer＋Windows実推論 | **IN PROGRESS / #8** | Spleeter公式v1.4.0 4stemsを候補化。Ubuntu公式asset推論成功。Windows依存差を明示して実推論を再試験中 |
| **P03** | 実曲の発音・役割・関連成分・必要量の自動判断 | **PARTIAL / P01待ち** | 合成/参照設計は実装済み。実曲の好例保存・負例修復が未受入 |
| **P04** | 加算・広域・狭帯域を共同判断・共同量管理で実行 | **PARTIAL** | **P04-A #9 DONE**：同一基音のみをjoint-v46へ接続、377件両OS成功。残りはP03の自動role/eventからこの経路へつなぐこと |
| **P05** | 最終OPPO/limiter・MP3後にも利益が残る候補選択と実曲回帰 | **PARTIAL / P01待ち** | 完成チェーン相互作用は合成音で確認。実曲の完成音比較は未完 |
| **P06** | GUI設定・進捗・キャンセルで新workerを運用 | **PARTIAL：P06-A DONE / #6** | Windows frozen GUI→別worker→完走/処理中cancel成功。product_release runtimeはP02/P03/P04の受入まで閉鎖 |
| **P07** | 同名保存・退避・復旧・掃除・多曲連続処理 | **DONE** | P07-A #4 / P07-B #5 / P07-C #7 全てDONE。Windows/Ubuntu実行根拠あり |
| **P08** | 更新Windows EXEを実モデル・実曲・GUI・保存まで通し最終受入 | **WAITING** | P02/P03/P04/P05を閉じた後にproduct_releaseを開け、版/hash固定で最終受入 |

## 今回までに閉じた主要課題

### P07 DONE — 運用基盤
- P07-A #4：`processed`同名WAV/MP3、設定変更時backup、通常中断再実行、曲単位cleanup。
- P07-B #5：PID/create-time/source/request seal付き所有manifest、実process kill後のstale回収、容量不足preflight。
- P07-C #7：WAV/FLAC同stem衝突の開始前拒否、複数folder/多曲、失敗曲を記録して継続、再実行skip、終了時大容量残留0。

P07-C最終CI `34491438266`、Windows/Ubuntu success。P07-B最終CI `34489650678`、Windows/Ubuntu success。

### P06-A DONE — GUI/worker基盤
Issue #6。既存4目標とreplace-managed UIを維持し、Tk main threadから別workerへDSPを分離。status IPC・cancel・一曲失敗後の継続を実装。

Windows frozen GUI最終run `34492251802`、job `102921677167` success。途中でWindowsのstatus.json readと`os.replace()`競合によるAccess Deniedを実バグとして検出し、PermissionErrorだけを有限retryして解消。Tk自己試験の時間待ち・CP1252診断出力も修正。

**product_release runtimeは未承認のため閉鎖中。** GUI基盤DONEを更新EXE出荷DONEへ読み替えない。

### P04-A DONE — 同一基音補強の技術接続
Issue #9。`joint-v46`で、原音observerのrole/pitch/event支持とHE/AUTO後の実音声の不足を双方要求し、同一基音のみを補強する。

- 110→55Hzなど新octaveは禁止。
- 既に十分、誤音程、休符/不確実区間は無加算。
- 広域low-cutと同時の加算は自己相殺として拒否。
- 重なる加算はplanner解決なしに足し上げない。
- stem samplesは成果物に混ぜない。
- HFTC→最終AUTO→WAV/MP3まで接続。

最終commit `d26ac2c4390b20cb21e7667bf3f191075bee2520`、CI `34602396977`、Windows/Ubuntuで377件すべて成功。

## 現在実行中：P02

候補はDeezer Spleeter公式v1.4.0の`4stems.tar.gz`。公式release assetをchecksum付きで取得する。著者論文はソースコードとpretrained modelsのMIT配布を明記。4stems設定は44.1kHz、`vocals/drums/bass/other`。

Spleeter 2.4.2のPython依存は現PDRMのPython3.12/Numpy2系と競合するため、同一processへ混ぜず隔離worker/runtimeを前提にする。

Windowsではpackage metadataが`tensorflow-io-gcs-filesystem==0.32.0`を固定する一方、0.32.0 Windows wheelが存在しない。TensorFlow 2.12.1は利用可能な0.31.0を導入する。既知のこの差だけを記録し、その他の依存不整合はfatal、**実際の公式4stemsローカル推論を合否条件**として再試験中。

Spleeterを採用確定する条件は、ライセンスだけでなく、bass/rest/vocal protection/role evidenceで現在の観測契約に足ること、Windowsで利用者にPython/TensorFlow手動導入を要求しないこと。単なるSDRや一回の合成推論ではP02を閉じない。

## ゴールへ進む順序

主経路：**P02 → P03 → P04残件 → P05 → P08**。
P01が復旧した瞬間は、運用改修より**P03/P05の私有実曲検証を最優先**する。

P06/P07はこれ以上の研究対象にしない。製品化で新しい実バグが出た場合だけ再開する。

## 停止条件

会話1往復の開発は、以下のいずれかで必ず区切って返答する。
1. 課題IDをDONEへ閉じた。
2. 実バグを特定し、修正中または再現条件まで確定した。
3. 外部阻害要因で止まり、回避してはいけない理由と次の独立作業が確定した。

「さらに検証できる」「説明を追加できる」だけではツール実行を継続しない。

## 機密・評価境界

個人音源・レビュー・実参照atlasを公開GitHub/CIへ送らない。合成音やpublic modelのCI結果を本人作品の音質合格へ昇格しない。空欄レビューをpositive labelへ変えない。KEEPとABSTAINを分ける。

中高域のHE/HFTCは現行の良い線を維持し、低域統合を理由に大改造しない。最終合否はユーザーの聴感だが、設計・機械・実曲回帰を先にできるだけ閉じ、ユーザーへ当てずっぽうのA/B反復を転嫁しない。
