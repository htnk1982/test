# PDRM AUTO v3.4 — 長文脈OPPO高速化版

## 変更しないもの

利用者はWAV/MP3のLUFSとTrue Peak上限だけを指定する。各ピーク制御段の順序はv3.3と同じ。

1. GAIN_ONLY
2. OPPO
3. OPPOが `NotFeasible` を明示した時だけ LIMITER_FALLBACK
4. I/O、破損、非有限値、ソース変更、整合性異常、キャンセル等はSTOP

Note-Subの判断shadow、HarmonicElasticity、Note-Sub、HFTC、通常リミッター本体、v3.2/v3.3の既存モジュールは変更していない。

## v3.4で変えたもの

v3.2の長文脈Rescueは、128/256/512/1024msの文脈全体を320反復のFFT最適化へ入れていた。しかし同じ制約式を見ると、差分波形を変更可能なのはピーク周辺の狭いsupportだけであり、それ以外は下限=上限=0に固定される。

v3.4は、このゼロ固定変数を最適化問題から除外する。周波数重み付き二次項について、元の全長FFT Hessianの該当principal blockをToeplitz作用素として構成する。したがって「FFTを短くした別の近似目的関数」ではなく、変更可能区間に対する同じ二次作用を計算する。

- 全文脈から周波数重みを作る点は維持。
- 時間重み、ステレオ方向ペナルティ、ピークbox、locked sample、自然さgate、envelope energy redistributionを維持。
- 反復上限320、収束判定、projected-gradient gateを維持。
- 旧v0.1ソルバーで成立する窓は従来経路のまま。
- 長文脈救済が不要な曲はv3.2の同経路とsample-identicalになる回帰を持つ。

1024ms / 4x格子のような場合でも、単一ピークなら最適化FFTの対象はピーク周辺supportを含む小区間だけになる。実際の縮約率はピーク配置によって変わるため、全曲に固定倍率の高速化は保証しない。

## 進捗表示

長文脈ソルバー中は、従来の `OPPO_CHUNK_COMMITTED` が延々残る代わりに、例えば次を表示する。

`[OPPO_CONTEXT_SOLVE_256MS_P2] 96/320`

- `256MS`: 現在評価している文脈長
- `P2`: その曲の長文脈ソルバー呼出し番号
- `96/320`: 反復進捗。収束すれば320より前に終了する。

この更新経路でもCANCELを確認するため、長い最適化中のキャンセル応答も改善する。

## 安全性

高速化のために以下は行わない。

- 自然さ閾値を緩める
- 反復上限を削って成功扱いする
- TP ceilingを勝手に緩める
- OPPO失敗を黙って成功扱いする
- operational errorをlimiter fallbackへ変換する

長文脈OPPOが安全制約内で成立しない場合は、AUTOポリシーに戻り通常リミッターを使う。通常リミッターが不要な曲には掛からない。

## GUI / 保存

GUIはv3.3同様、WAV/MP3のLUFS・TPと管理済み出力置換だけ。方式選択はない。

出力は元音源と同じフォルダの `processed` に同名WAV/MP3。成功後はその曲のLOCALAPPDATA大容量作業音声を削除し、通常失敗時も小さい診断だけを残す。v3.4開始時、同じsource hashに紐づくv3.0〜v3.3の旧作業キャッシュを回収する。

## 検証の意味

ソース回帰では、FFT principal-block作用の数値一致、旧dense solverとの同一候補近似、1024ms文脈のworkset縮約、live progress、旧feasible経路のsample identity、AUTO operational-error境界を検査する。

これは利用者の実25曲すべての処理時間や聴感を保証するものではない。実バッチで、長文脈Rescueが何回発生するかと各文脈長が最終的な識別観測になる。
