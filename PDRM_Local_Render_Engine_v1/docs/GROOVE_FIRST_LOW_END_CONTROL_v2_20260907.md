# PDRM Groove-First Low-End Control v2

## User acceptance target

低域は「ずっと太い」ことを価値としない。出る時は出て、引っ込む時は引っ込み、キック／ベースの動きと一体になってグルーブを作ることを価値とする。

PRIMARY_OBJECTIVE := low-frequency temporal contrast + rhythmic role + musical restraint
NOT_OBJECTIVE := maximum low-frequency RMS / continuous sub weight / spectral flattening

## Core model

低域を単一の量ではなく、以下へ分解する。

- BALANCE: セクション全体の低域量
- ATTACK/PUNCH: 音符・キック開始時の低域アクセント
- SUSTAIN: 開始後の低域保持量と減衰
- VALLEY: ヒット間・休符でどこまで低域が戻るか
- FLUX: 低域の時間的変化量
- DUTY: 低域が前景に居続ける時間率
- PEAK: 瞬間ピーク安全性
- ROLE: kick / bass-note / sustained-bed / ambiguous

参照ターゲットは単一スペクトル曲線でなく、同種セクションのこれら特徴量の許容範囲とする。

## Analysis

25–120Hzのエネルギー包絡をfast/medium/slowの複数時定数で観測し、低域onset、局所peak、decay、inter-event valley、低域spectral flux、event density、周期性、pitch trajectoryを抽出する。必要に応じ90–250Hzの上位倍音／輪郭帯域も併用する。

セクションはVerse/Chorus等の名称を推定する必要はなく、音量・密度・スペクトル・event rateのchange pointで局所定常領域へ分ける。全曲一つの低域量へ均さない。

## Authorization before amount

音程検出と追加許可を分離する。

SUB_ADDを許可するには全て必要:
1. 既存bass-role eventの時間位置が確定している。
2. 追加音程が既存の演奏の補修と説明できる。
3. f0/2を作る場合、observed-fundamental hypothesisよりmissing-fundamental hypothesisが十分強い。
4. onset/decayの時間包絡を既存演奏から取得できる。
5. 追加後もVALLEYとDUTYがターゲット範囲を悪化させない。

音程が分かっただけではSUB_ADDを許可しない。110Hzを検出したことだけを理由に55Hzを生成しない。

## Candidate actions

各セクション／eventでDRYを必ず候補に含め、次から必要なものだけ生成する。

- KEEP: 無処理
- SUB_ACCENT: 既存bass eventのattack〜early sustainだけを同一役割のsubで補強
- FUNDAMENTAL_REPAIR: missing-fundamentalが高信頼の時だけ基音を補修
- SUSTAIN_TRIM: onsetを保持し、後半sustainのみ低域を減衰
- VALLEY_RESTORE: event間へ残り続ける低域をdownward expansion/dynamic attenuationで戻す
- RESONANCE_CONTROL: 特定低域の長い共鳴のみ抑制
- HARMONIC_DEFINE: subを増やさず90–250Hz付近の輪郭を必要eventだけ補う

新しい低音フレーズを作るOCTAVE_DOWN_SYNTHは通常の自動マスタリングでは禁止する。

## Event-shaped rendering

生成subは連続サイン波をnote lifetime全体へ流すことを標準にしない。元のbass-role envelopeをキャリアにする。

- attack位置は元eventから取得
- sub peakは元event peakに同期
- decay/releaseは元のdecayと次eventまでのIOIを基準に設定
- 明示的なsustain根拠がなければearly sustain後に低下
- 休符／inter-event valleyへ入る前にターゲットfloorへ戻す
- phaseは既存低域との合成peakと相関を見て決定

同じpitchが続いていても、reattackまたはgroove gapは別eventとして扱えることを優先する。

## Groove feature targets

参照ライブラリから同種セクションごとに以下の分布を作る。

- LOW_LEVEL: 25–120Hzのrobust level
- ATTACK_TO_SUSTAIN_DB
- EVENT_TO_VALLEY_DB
- DECAY_TIME / IOI
- LOW_FREQ_SPECTRAL_FLUX
- LOW_END_DUTY_CYCLE
- LOW_END_CREST
- 25–55 / 55–90 / 90–140Hz balance
- kick/bass overlap timing

目標値は一点でなくpercentile bandとする。参照曲を模写せず、魅力的な低域挙動の範囲を学ぶ。

## Candidate selection

最終候補は、無処理を含む候補の中から、参照feature bandへ改善し、かつ変更量が最小のものを選ぶ。

優先順位:
1. 不要音を作らない
2. VALLEYを残す
3. onset/punchを壊さない
4. sustain過多を避ける
5. 低域balanceを許容範囲へ
6. 最小変更

ピーク／LUFSを通る最大追加量を採用しない。

## Joint sub / harmonic budget

subとharmonicを別々に最大化しない。低域の一つの知覚budgetとして競合させる。

- subが既に十分ならHARMONIC_DEFINEを優先できる
- sustainが過剰ならsub追加禁止＋SUSTAIN_TRIM
- transient不足だがvalley良好ならSUB_ACCENT
- harmonic追加もbass-role event envelopeに従い、休符では戻す

## Three negative examples

08 微熱サーモグラフィ:
全体低域が既に重い場合、SUB_ADDではなくKEEPまたはSUSTAIN_TRIM/RESONANCE_CONTROLを候補にする。局所的に不足していてもVALLEY/DUTYを悪化させる追加は拒否。

11 Traces:
静かな終盤で110Hz周期を検出しても55Hz missing-fundamentalの証拠が弱ければSUB_ADD禁止。bass-role/onsetとmissing-fundamentalの両方が揃わないためDRYを選ぶ。

12 私=AI-MY:
後半でsection low-end floorとdutyが上昇する場合、追加を停止し、onsetを残したSUSTAIN_TRIM/VALLEY_RESTOREを候補にする。前半と同じ量へ静的EQで均さない。

## Validation contract

人間試聴前に正例・負例コーパスで以下を満たす。

- Tracesの既知誤生成を0にする
- 正しく有効だったNote-Sub正例を一律バイパスしない
- 08/12のような元低域過多で追加量が増えない
- rest/outro/sparse区間でinvented subを作らない
- 同じbass noteでもreattack/gapのメリハリを維持
- reference targetを変えた時の判断根拠をreportへ保存
- DRYが最良なら無処理を選ぶ
- final peak処理後にもVALLEY/DUTY/attack-to-sustainを再検査

## Research alignment

商用SOTAの公開設計でも低域を単一levelではなくBalance/Punch/Sustain/Peakへ分解して扱う。groove研究でも低域の静的RMSだけでなく、dynamic bass activityやlow-frequency spectral fluxがgrooveと関連する。PDRMではこれを「量」より「時間的コントラスト」を主目的にする根拠として使い、特定製品の非公開アルゴリズムの再現は主張しない。

STATUS := DESIGN_LOCKED_FOR_NEXT_LAB; production DSP unchanged by this document.
