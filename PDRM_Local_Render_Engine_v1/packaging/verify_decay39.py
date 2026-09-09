"""Run contracts and paired audio tests. No private user audio or learned model.

The restoration evaluator sees the clean waveform; the processing code never
receives it. Calibration waveforms and evaluation waveforms have separate groups.
These synthetic groups do not stand in for independent real-music validation.
"""
from pathlib import Path
import hashlib,importlib.metadata,json,platform,subprocess,sys,unittest,zipfile
import numpy as np
import soundfile as sf
from scipy import signal
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import event_decay_v39 as ed
import spectral_persistence_lab as spectral
from decay39_fixtures import audio_atlas,audio_fixture,oracle
BASE='72cbe2b9faae40be32a90ef780b0c5e240db8674'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    out=ROOT/'DECAY39_EVIDENCE';out.mkdir(exist_ok=True)
    frozen=['distribution_finish.py','hf_temporal_contrast_lab.py','offline_peak_lab.py',
        'offline_peak_stream_v34.py','auto_peak_v34.py','natural_finish_v34.py',
        'processed_finish.py','relative_spectral_v38.py','role_observer_v38.py']
    for path in frozen:
        old=subprocess.check_output(['git','show',BASE+':PDRM_Local_Render_Engine_v1/'+path])
        assert old.replace(b'\r\n',b'\n')==(ROOT/path).read_bytes().replace(b'\r\n',b'\n'),path
    old_patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py')
    old=unittest.TestSuite()
    for pattern in old_patterns:old.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
    new=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_event_decay39.py')
    old_count,new_count=old.countTestCases(),new.countTestCases()
    assert old_count==120 and new_count>=50,(old_count,new_count)
    suite=unittest.TestSuite([old,new]);result=unittest.TextTestRunner(verbosity=2).run(suite)
    report=dict(scope='Synthetic software and paired-waveform tests only; no personal audio or neural inference',
        tests=result.testsRun,previous_tests=old_count,new_tests=new_count,ok=result.wasSuccessful(),
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        frozen_core='MATCH',base_commit=BASE,code_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
        platform=platform.platform(),python=sys.version,
        versions={name:importlib.metadata.version(name) for name in ('numpy','scipy','soundfile','pyloudnorm')})
    (out/'TEST_RESULTS.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if not result.wasSuccessful() or result.skipped:raise SystemExit(1)
    atlas=audio_atlas()
    (out/'SYNTHETIC_CALIBRATION.json').write_text(json.dumps(atlas,indent=2),encoding='utf-8')
    work=out/'working';work.mkdir(exist_ok=True)
    cases=[]
    settings=[(32000,.35,.74,0.,False),(44100,1.10,.82,.8,False),
              (48000,2.55,.90,-.7,False),(96000,.52,.80,.3,False),
              (32000,2.00,.80,7.,False),(48000,.47,.0,0.,True)]
    for idx,(sr,phase,decay,color,legato) in enumerate(settings):
        # Last two are timbre-offset and intentional-sustain null controls.
        amounts=(0.,3.,6.,9.) if idx<4 else (0.,)
        for fault_db in amounts:
            clean,bad,event=audio_fixture(sr,phase,decay,color,fault_db,legato=legato)
            src=work/'input.wav';sf.write(src,bad,sr,subtype='DOUBLE');h=ed.file_hash(src)
            features=spectral.extract(bad,sr,0)
            evidence=oracle(features['time'],event,h)
            p=ed.plan(features,event,atlas,h,evidence,allow_test_evidence=True)
            y,rate=ed.render_verified(src,p)
            saved=work/'candidate.wav';sf.write(saved,y,rate,subtype='DOUBLE')
            actual,rate=sf.read(saved,dtype='float64',always_2d=True)
            t=np.arange(len(bad))/sr
            protected=(t<=event.anchor_end_seconds+ed.Config().post_anchor_guard_seconds)|(t>=event.end_seconds)
            initial=float(np.sum((bad-clean)**2));remaining=float(np.sum((actual-clean)**2))
            ratio=remaining/initial if initial>1e-25 else None
            delta=actual-bad
            sos=signal.butter(6,1500,fs=sr,btype='highpass',output='sos')
            hf=signal.sosfilt(sos,delta,axis=0)
            hf_db=float(20*np.log10(max(np.sqrt(np.mean(hf*hf)),1e-15)/max(np.sqrt(np.mean(bad*bad)),1e-15)))
            outside=float(np.max(np.abs(delta[protected])))
            case=dict(case=f'group{idx+1}_fault{fault_db:g}',sr=sr,fault_db=fault_db,
                intentional_sustain=legato,constant_timbre_offset_db=color,
                plan_status=p['status'],max_mask_depth_db=float(p['depth_db'].max()),
                candidate_seconds=p.get('candidate_seconds',0.),
                exact_noop=bool(np.array_equal(actual,bad)),
                protected_sample_max_difference=outside,
                error_energy_ratio_to_clean=ratio,
                error_reduction_db=None if ratio is None else float(-10*np.log10(max(ratio,1e-20))),
                highband_residual_db=hf_db,
                source_unchanged=ed.file_hash(src)==h,
                evidence_provider='synthetic_oracle',clean_passed_to_processor=False)
            cases.append(case);print('PAIR_RESULT '+json.dumps(case),flush=True)
            (out/'PAIRED_AUDIO_RESULTS.json').write_text(json.dumps(cases,indent=2),encoding='utf-8')
            if fault_db==0:
                assert case['exact_noop'],case
            if fault_db>=6:
                assert ratio is not None and ratio<.99 and p['status']=='RELATIVE_TAIL_CANDIDATE',case
            assert outside==0 and hf_db<=-60 and case['source_unchanged'],case
            if idx==0 and fault_db==6:
                demo=out/'synthetic_diagnostic';demo.mkdir(exist_ok=True)
                for name,audio in [('CLEAN_GROUND_TRUTH',clean),('FAULT_INPUT',bad),('PROCESSED_CANDIDATE',actual)]:
                    sf.write(demo/(name+'.wav'),audio,sr,subtype='PCM_24')
    for path in work.iterdir():path.unlink()
    work.rmdir()
    null=[c for c in cases if c['fault_db']==0]
    modified=[c for c in cases if c['fault_db']>0]
    changed=[c for c in modified if not c['exact_noop']]
    improved=[c for c in changed if c['error_energy_ratio_to_clean']<1]
    report.update(audio_pairs=len(cases),null_controls=len(null),null_exact_noop=sum(c['exact_noop'] for c in null),
        altered_controls=len(modified),altered_detected=len(changed),altered_improved=len(improved),
        success=True,subjective_quality='NOT_EVALUATED',private_music_tested_this_round=False,
        production_exe_changed=False)
    (out/'SUMMARY.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    rows='\n'.join('| '+c['case']+' | '+str(c['sr'])+' | '+c['plan_status']+' | '+('—' if c['error_reduction_db'] is None else f"{c['error_reduction_db']:.4f}")+' |' for c in cases)
    md=f'''# PDRM Boundary39 — 相対減衰の実装・対照試験

日付: 2026-09-09
状態: LAB実装・合成対照試験完了。実曲への適用・主観承認・新EXEは未実施。
実行環境: {report['platform']}
コミット: `{report['code_commit']}`

## 実装したこと

既存Boundary38の相対スペクトル処理は変更せず、同じ発音に関係する成分の減衰差を判断するevent_decay_v39.pyを追加した。
対象成分と少なくとも二つの関連成分について、発音の頭の基準区間からのレベル変化を比較する。
全体の音量や対象成分の一定の色付けを、そのまま不要な尾部と呼ばない。
参照の自然な相対減衰を許容範囲として記録し、それを超え、関連成分が実際に引き、局所的な役割の観測が成立した場合だけ差分処理の候補を作る。

役割・現象・評価時刻の一致を明示的に確認する。全曲のベース好評コメントを、同じ曲のホーンやボーカルの全帯域正解に変換しない。
時間範囲がないコメントは弱い役割ラベルとして保持し、局所校正データへ勝手に昇格させない。
未評価、役割違い、観測保留、問題の根拠なしは別状態である。

## 検証結果

- ソフトウェア試験: {report['tests']}件（既存LAB {old_count} + 新規 {new_count}）、失敗0、エラー0、skip 0。
- 原版の無加工: {report['null_exact_noop']}/{len(null)}。大きい音色成分、意図的な持続の対照を含む。
- 既知の尾部増加コピー: {len(changed)}/{len(modified)}に候補、うち{len(improved)}件で既知の原版に対する波形誤差が減った。
- 操作区間外・保護した発音の頭の最大サンプル差: 全ケース0。
- 1.5kHz以上の差分検査: 全ケース -60 dB相対以下。ただし不可聴性を保証する指標ではない。
- 原音非破壊を保存後にも照合。合成試験の一時WAVは後片付け済み。

校正は四つの合成元グループ、評価は位相・減衰・サンプルレート・色付けを変えた別設定。
検知器・描画器へ、評価用の無欠陥原版は渡していない。比較評価だけが既知の原版を見る。
これは合成分布内の再現検証であり、実楽曲や未知楽器での一般化ではない。

| 合成ケース | Hz | 判定 | 既知の原版に対する誤差低下 dB |
|---|---:|---|---:|
{rows}

## オーディオの条件と限界

音声は4秒の合成関連成分と独立した高域成分。既知の不具合コピーは、発音の頭を変えず、一成分の尾部へ3/6/9dBの段階的増加を加えた。
処理は元ミックスへ最大1.5dBの限定スペクトル差分を加え、端部は滑らかにつなぐ。参照へ完全復元した、好みが再現できたとは主張しない。
今回の役割観測は明示的なsynthetic_oracleで、デフォルトAPIでは受け入れない。試験用許可でのみ使用する。
実際のv38ステム観測へ接続するアダプターは追加したが、この実行で神経モデルは動かしていない。
同じ役割・共通の立ち上がりも、同じ楽器や一音であることの証明ではない。実曲での音の関連付けと、局所的な参照校正は未完了。

## 不変更と次の条件

既存HE・HFTC・OPPO・保存処理とBoundary38を基準コミットから比較し、未変更。
本番EXEへ入れていない。個人音源、Excel、コメント原文、モデル重みをCIに送っていない。
次に必要なのは、実曲の関係推定をこの条件へ接続することと、その区間での保存・改善の確認。
今回の結果をNo.24の修復成功、No.6/14の実曲無加工、あるいは全曲の処理量校正済みという結果へ読み替えない。

## 一次資料と設計提案の区別

- ユーザー提供の「音源提供・評価・分析・処理方針の整理.md」: コメントを役割・現象・文脈へ対応させ、原2mixを保持する要求。
- repoのBoundary38実装・状態記録: この改修の実行基準。
- 今回のソース、TEST_RESULTS.json、PAIRED_AUDIO_RESULTS.json: 今回実行した根拠。
- 相対減衰による境界と数値予算は本LABの設計仮説で、普遍的な聴感しきい値ではない。
- STFT重ね合わせの数値条件: https://docs.scipy.org/doc/scipy/reference/generated/scipy.signal.check_NOLA.html
- 部分音と音色: https://www.audiolabs-erlangen.de/resources/MIR/FMP/C1/C1S3_Timbre.html

外部資料は数値手法・音響概念の根拠であり、PDRMの音質改善を証明していない。
'''
    (out/'PDRM_Boundary39_相対減衰_実装と対照試験_20260909.md').write_text(md,encoding='utf-8')
    source=out/'code';source.mkdir(exist_ok=True)
    files=['event_decay_v39.py','relative_spectral_v38.py','spectral_persistence_lab.py','stem_observer_lab.py',
           'tests/decay39_fixtures.py','tests/test_event_decay39.py','packaging/verify_decay39.py']
    for name in files:
        dest=source/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes((ROOT/name).read_bytes())
    (source/'requirements.txt').write_text('numpy\nscipy\nsoundfile\npyloudnorm\n',encoding='utf-8')
    sums=[sha(p)+'  '+p.relative_to(out).as_posix() for p in sorted(out.rglob('*')) if p.is_file()]
    (out/'SHA256SUMS.txt').write_text('\n'.join(sums)+'\n',encoding='utf-8')
    print('DECAY39_SUMMARY '+json.dumps(report),flush=True)

if __name__=='__main__':main()
