from pathlib import Path
import json,os,tempfile,time,unittest
from unittest.mock import patch
import psutil
import crash_recovery_v43 as r
import processed_integration as p
from integration_contract_v40 import digest

SRC='a'*64
REQ='b'*64

class RecoveryContracts(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def marker(self,name='job',source=SRC,request=REQ,pid=99999999,created=1.0):
        d=self.root/(r.PREFIX+name);d.mkdir();body=dict(schema=r.SCHEMA,version=r.VERSION,owner='PDRM_PROCESSED_INTEGRATION',source_sha256=source,request_sha256=request,pid=pid,process_create_time=created,created_unix=time.time(),token='x')
        (d/r.MARKER).write_text(json.dumps(r._sealed(body)),encoding='utf-8');(d/'large.bin').write_bytes(b'x'*1024*1024);return d
    def test_dead_owner_removed(self):
        d=self.marker();out=r.recover(self.root,source_sha256=SRC);self.assertFalse(d.exists());self.assertGreaterEqual(out['bytes_freed'],1024*1024)
    def test_other_source_preserved(self):
        d=self.marker(source='c'*64);out=r.recover(self.root,source_sha256=SRC);self.assertTrue(d.exists());self.assertEqual(out['removed'],[])
    def test_other_request_preserved_when_scoped(self):
        d=self.marker(request='d'*64);out=r.recover(self.root,source_sha256=SRC,request_sha256=REQ);self.assertTrue(d.exists())
    def test_old_request_same_source_can_be_recovered_unscoped(self):
        d=self.marker(request='d'*64);r.recover(self.root,source_sha256=SRC);self.assertFalse(d.exists())
    def test_unverified_folder_preserved(self):
        d=self.root/(r.PREFIX+'unknown');d.mkdir();(d/'x').write_text('x');r.recover(self.root,source_sha256=SRC);self.assertTrue(d.exists())
    def test_tampered_marker_preserved(self):
        d=self.marker();j=json.loads((d/r.MARKER).read_text());j['source_sha256']='e'*64;(d/r.MARKER).write_text(json.dumps(j));r.recover(self.root,source_sha256=SRC);self.assertTrue(d.exists())
    def test_live_current_process_preserved(self):
        with r.owned_workspace(self.root,source_sha256=SRC,request_sha256=REQ) as d:
            out=r.recover(self.root,source_sha256=SRC);self.assertTrue(d.exists());self.assertTrue(any(v['reason']=='CURRENT_PROCESS' for v in out['kept']))
        self.assertFalse(d.exists())
    def test_pid_reuse_mismatch_is_stale(self):
        d=self.marker(pid=os.getpid(),created=psutil.Process().create_time()-100);r.recover(self.root,source_sha256=SRC);self.assertFalse(d.exists())
    def test_missing_root_is_noop(self):
        missing=self.root/'missing';self.assertEqual(r.recover(missing,source_sha256=SRC)['removed'],[])
    def test_invalid_owned_hash_rejected(self):
        with self.assertRaises(ValueError):
            with r.owned_workspace(self.root,source_sha256='bad',request_sha256=REQ):pass
    def test_normal_exception_still_cleans(self):
        path=None
        with self.assertRaisesRegex(RuntimeError,'boom'):
            with r.owned_workspace(self.root,source_sha256=SRC,request_sha256=REQ) as d:
                path=d;(d/'large').write_bytes(b'x'*100000);raise RuntimeError('boom')
        self.assertFalse(path.exists())

class CapacityContracts(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.source=self.root/'x.wav'
        import numpy as np,soundfile as sf
        sf.write(self.source,np.zeros((48000,2)),48000,subtype='FLOAT');self.out=self.root/'processed';self.out.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def test_insufficient_work_space_fails(self):
        usage=type('U',(),dict(total=10**9,used=10**9-1,free=1))()
        with patch.object(p.shutil,'disk_usage',return_value=usage):
            with self.assertRaisesRegex(OSError,'working space'):p.preflight_space(self.root,self.source,self.out)
    def test_insufficient_output_space_fails_independently(self):
        good=type('U',(),dict(total=10**10,used=0,free=10**10))();bad=type('U',(),dict(total=10**9,used=10**9-1,free=1))()
        with patch.object(p.shutil,'disk_usage',side_effect=[good,bad]):
            with self.assertRaisesRegex(OSError,'output space'):p.preflight_space(self.root,self.source,self.out)
    def test_preflight_returns_explicit_budget(self):
        out=p.preflight_space(self.root,self.source,self.out);self.assertGreater(out['work_required_bytes'],0);self.assertGreater(out['output_required_bytes'],0)

if __name__=='__main__':unittest.main(verbosity=2)
