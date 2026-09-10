"""P07-B acceptance: hard-kill a real new-chain call, recover, rerun, verify."""
from pathlib import Path
import sys,os,json,time,subprocess,tempfile,unittest,platform
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
OUT=ROOT/'P07B_EVIDENCE'
BASE='a0c93d3366ab313ff638ed3dc3cff32f81c516df'

def dump(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def acceptance():
    import numpy as np,soundfile as sf
    import processed_integration as subject
    import crash_recovery_v43 as recovery
    from joint42_selftest import FixturePlanner
    from decay39_fixtures import audio_fixture
    from integration_contract_v40 import capture
    records=[]
    with tempfile.TemporaryDirectory(prefix='pdrm_p07b_') as tmp:
        root=Path(tmp);inp=root/'inputs';inp.mkdir();work=root/'work';work.mkdir()
        _,bad,_=audio_fixture(48000,phase=.35,decay=.74,fault_db=6.)
        # Repeat the 4 s fixture so the worker cannot finish between marker poll
        # and kill on a fast CI host; the parent later performs a real complete run.
        x=np.tile(bad,(5,1));source=inp/'hard kill.wav';sf.write(source,x,48000,subtype='DOUBLE');original=capture(source)
        cmd=[sys.executable,str(ROOT/'packaging'/'p07b_crash_worker.py'),str(source),str(work)]
        proc=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        owner=None;deadline=time.monotonic()+45
        while time.monotonic()<deadline:
            items=list(work.glob(recovery.PREFIX+'*/'+recovery.MARKER))
            if items:owner=items[0].parent;break
            if proc.poll() is not None:break
            time.sleep(.02)
        if owner is None:
            proc.kill();proc.wait(timeout=10);raise RuntimeError('Hard-kill worker created no sealed owned workspace')
        marker=json.loads((owner/recovery.MARKER).read_text(encoding='utf-8'))
        live=recovery.recover(work,source_sha256=original.file_sha256)
        assert owner.exists() and any(v['reason']=='LIVE_OWNER' for v in live['kept'])
        proc.kill();proc.wait(timeout=15)
        assert proc.returncode!=0 and owner.exists()
        stale_bytes=sum(p.stat().st_size for p in owner.rglob('*') if p.is_file())
        result,folder=subject.run_file(source,work,planner=FixturePlanner('tail'),enable_lab=True)
        assert original==capture(source)
        assert not owner.exists() and not list(work.glob(recovery.PREFIX+'*'))
        assert str(owner) in result['recovery']['removed']
        assert result['recovery']['bytes_freed']>=stale_bytes
        assert (folder/'hard kill.wav').is_file() and (folder/'hard kill.mp3').is_file()
        assert abs(result['master_metrics']['lufs_i']+12)<.03 and result['master_metrics']['true_peak_max_dbtp_estimate']<=-2
        assert abs(result['codec_metrics']['lufs_i']+14)<.03 and result['codec_metrics']['true_peak_max_dbtp_estimate']<=-2
        records.append(dict(case='REAL_PROCESS_KILL_RECOVER_RERUN',worker_returncode=proc.returncode,
            stale_bytes=stale_bytes,recovered_bytes=result['recovery']['bytes_freed'],live_owner_was_preserved=True,
            stale_owner_removed=True,rerun_completed=True,source_unchanged=True,wav_lufs=result['master_metrics']['lufs_i'],
            mp3_lufs=result['codec_metrics']['lufs_i']))
        # Capacity must fail before DSP. Test through the public wrapper, not only
        # the helper, and assert no public audio is created for this second source.
        source2=inp/'capacity.wav';source2.write_bytes(source.read_bytes())
        tiny=type('Usage',(),dict(total=1000,used=999,free=1))()
        with patch.object(subject.shutil,'disk_usage',return_value=tiny),patch.object(subject.finish,'run_lab',side_effect=AssertionError('DSP should not start')):
            try:subject.run_file(source2,work,planner=FixturePlanner('tail'),enable_lab=True)
            except OSError as exc:assert 'space' in str(exc)
            else:raise AssertionError('Low-space preflight did not stop')
        processed=inp/'processed'
        assert not (processed/'capacity.wav').exists() and not (processed/'capacity.mp3').exists()
        records.append(dict(case='CAPACITY_PREFLIGHT_BEFORE_DSP',dsp_started=False,public_audio_created=False))
        # Recovery for one source must not collect a sealed stale workspace for another.
        other='f'*64
        with recovery.owned_workspace(work,source_sha256=other,request_sha256='e'*64) as foreign:
            out=recovery.recover(work,source_sha256=original.file_sha256)
            assert foreign.exists() and not out['removed']
        records.append(dict(case='OTHER_SOURCE_PROTECTED',preserved=True))
    return records

def main():
    OUT.mkdir(exist_ok=True)
    patterns=('test_lowend_boundary_lab.py','test_context_observer_lab.py','test_boundary37.py','test_relative38.py','test_event_decay39.py','test_integration40.py','test_integrated_chain40.py','test_automatic41.py','test_joint42.py','test_processed_integration.py')
    suite=unittest.TestSuite()
    for p in patterns:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=p))
    old=suite.countTestCases();assert old==336,old
    new=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_crash_recovery_v43.py');added=new.countTestCases();suite.addTests(new)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    summary=dict(task='P07-B',tests=result.testsRun,previous=old,new=added,success=result.wasSuccessful(),
        failures=[str(v) for v in result.failures],errors=[str(v) for v in result.errors],skipped=result.skipped,
        platform=platform.platform(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip())
    if not result.wasSuccessful() or result.skipped:
        dump(OUT/'SUMMARY.json',summary);raise SystemExit(1)
    summary['acceptance']=acceptance();summary.update(product_release=False,private_music=False,physical_power_loss_tested=False,
        process_kill_tested=True,capacity_failure_tested=True,parent_P07_done=False)
    dump(OUT/'SUMMARY.json',summary)
    md=f'''# PDRM P07-B — 強制終了・容量障害の回収 実行記録\n\n日付: 2026-09-10。Issue #5。commit `{summary['commit']}`。\n環境: {summary['platform']}。\n\n実プロセスで新しいprocessed統合経路を開始し、所有manifestが作成された後にOSの強制kill APIで終了させた。生存中はrecoveryがその領域を削除しないこと、kill後には残留領域が実際に残ること、次の通常実行で死亡ownerだけを回収して同じ曲をWAV/MP3まで完走することを確認した。\n\n所有判定はsource hash、request hash、PID、process create time、sealを使う。PIDだけでは判定しない。別source、live owner、seal不成立folderは削除対象にしない。これは悪意あるローカル攻撃に対する暗号学的sandboxではなく、誤削除防止の運用境界である。\n\n容量不足はwrapper経由でfree=1byteを注入し、DSP開始関数を呼ぶと失敗する仕掛けで、DSP前にOSErrorとなることと公開WAV/MP3が作られないことを確認した。物理ディスクを実際に満杯にした試験ではない。\n\n通常のコピー/I/O例外、変更済みprocessed、backup保護、通常中断のjournal回復はP07-Aの既存試験を同時に再実行している。\n\nソフトウェア試験 {summary['tests']}件。これを製品完成率や音質受入に換算しない。物理的な電源断、SSD故障、長時間多曲の容量累積は未試験で、P07-C/P08へ残る。\n'''
    (OUT/'PDRM_P07B_強制終了と容量回復_20260910.md').write_text(md,encoding='utf-8')
    print('P07B '+json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
