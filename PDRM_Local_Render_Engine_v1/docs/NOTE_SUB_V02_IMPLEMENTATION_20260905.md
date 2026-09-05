# PDRM Note-Sub v0.2 — 実装・回帰試験記録

日付: 2026-09-05
対象branch: `pdrm-note-sub-lab-v1`
実装commit: `496c9c7455768b13830240836813075eab37a67c`
GitHub Actions run: `33959610380`
状態: 実装回帰 PASS。実曲の音質承認ではない。

## 1. 今回変更したもの

`NOTE_SUB_V011_EVENT_AUDIT_20260905.md` の修正条件を実装へ移した。監査の再反復や追加JSON取得は行っていない。

追加・変更範囲:

- `note_sub_lab_v02.py` — v0.2の分析・追跡・生成ロジック
- `tests/test_note_sub_v02.py` — v0.2回帰試験
- `note_sub_launch.py` — v0.2を起動
- `.github/workflows/pdrm-note-sub-ci.yml` — v0.1.1既存試験とv0.2試験を併走

変更していない範囲:

- 採用Cそのもの
- `pdrm_engine/`
- `pdrm_runtime/`
- `pdrm_operator_lab/`
- 既存 `note_sub_lab.py` v0.1.1のベースラインコード

## 2. 責務分離

### 音符追跡

`analyze_pitch_observation()` と `track_notes()` が担当する。

- `track_state` を追加量とは別に保持する。
- 既存低域が十分で追加量が0でも、音符追跡は継続できる。
- SILENCE / UNKNOWN は自動延長せず、音符を閉じる。
- 同音再アタックは短時間のtonal-strength dip→riseまたは明示的境界証拠で分離する。

### 生成先選択

`select_generation_target()` が担当する。

- 推定f0と生成先を別値として保持する。
- f0が約1オクターブ切り替わっても、生成先が同じなら、その切替だけでは音符を閉じない。
- 一律のキー量子化・主音ドローン化は行わない。

### 追加量

`decide_addition_amount()` が担当する。

- 既存target成分、既存sub RMS、desired levelから追加量を決める。
- `KEEP / amount=0` と `音符終了` を別状態にした。
- 既存のpeak・scale・LUFSゲートはv0.1.1側の隔離runtimeを再利用する。

### 波形描画

`event_wave()` が担当する。

- 一つのtracked note内では位相積分を継続する。
- 内部に追加量0の区間があっても位相状態を再開始しない。
- 実際の出力振幅は0のままにできるので、内部状態保持と未知区間への発音を分離している。
- attack/releaseは各音符長に対して適応させ、短い音符を常に60ms+60msで全面フェードする構造を避けた。

## 3. v0.2追加回帰試験

1. f0の1オクターブ切替と生成先選択の分離
2. f0だけが1オクターブ切替・生成先同一の持続音で、音符/位相を再開始しない
3. 音符内の追加量0通過でtrackingと位相積分を終了しない
4. 同音再アタックと実休符は同じ生成先でも別音符にする
5. 既存低域十分のベースを `KEEP` としつつtrackingは維持する
6. 既知82.406889 Hzベースに、低域キック、和音、高域打撃を混ぜた回帰で、誤った生成先へ逸脱しない
7. v0.2 full `run_job()` で入力C/controlを書き換えず、production runtimeをimportしない

## 4. 回帰結果

GitHub Actions run `33959610380`:

| 環境 | 結果 |
|---|---|
| Ubuntu latest / Python 3.12 | PASS |
| Windows latest / Python 3.12 | PASS |
| Windows latest / Python 3.14 | PASS |

Ubuntuログでは既存33件 + v0.2追加7件 = **40 tests / 40 PASS**。Windows両環境も同一test stepがPASSした。

CIの `Prove production files unchanged` も3環境すべてPASS。

## 5. 現時点の判定

v0.2の責務分離と混合合成音の回帰条件は実装済みで、既存v0.1.1の耐障害・no-overwrite・idempotence回帰を壊していない。

ただし、これは**実曲Cの音質承認ではない**。次に意味がある試験は追加監査ではなく、採用Cを入力したv0.2レンダリングを一度実行し、次の三つを同じ試聴単位で比較することである。

- `CONTROL_C.wav`
- `SUB_AUGMENTED.wav`
- `DELTA_SUB_FLOAT.wav`

その際も評価対象は「適用率を増やせたか」ではなく、誤音、休符への追加、短い膨らみ、低域の連続性、キックとの干渉、元Cの魅力を壊していないかとする。

## 6. 今回しなかったこと

- 追加JSONの要求
- 同じイベント監査の再実行
- 採用Cの変更
- 本番runtime/DSPの変更
- 実曲を試していないのに音質合格と宣言すること
