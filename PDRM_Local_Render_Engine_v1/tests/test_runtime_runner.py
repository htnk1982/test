from __future__ import annotations

from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest import mock

import numpy as np
import soundfile as sf

from pdrm_engine.io_utils import sha256_file, pcm_sha256
from pdrm_runtime.lock import JobLock
from pdrm_runtime.runner import ResilientRunner, ForeignOutputError


def synth(sr=48000, seconds=6.0, amp=0.025):
    t = np.arange(int(sr*seconds), dtype=np.float64)/sr
    mono = amp*(0.8*np.sin(2*np.pi*103*t) + 0.23*np.sin(2*np.pi*1301*t))
    return np.stack([mono, mono*0.99], axis=1).astype(np.float32)


class CountingCore:
    def __init__(self):
        self.calls = 0

    def __call__(self, input_path, output_path, config, runtime_context):
        self.calls += 1
        shutil.copyfile(input_path, output_path)
        return {
            "final_status":"NO_OP_ALREADY_OPTIMAL",
            "output_file_sha256":sha256_file(output_path),
            "output_pcm_sha256":pcm_sha256(output_path),
            "round9_executed":False,
            "max_round_executed":8,
        }


class RuntimeRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root/"work"
        self.inp = self.root/"input.wav"
        sf.write(self.inp, synth(), 48000, subtype="FLOAT")
        self.cfg = {
            "target_lufs":-18.0,
            "true_peak_ceiling_dbtp":-1.0,
            "output_subtype":"PCM_24",
            "round9_enabled":False,
            "requested_round":8,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def test_real_core_integration_and_idempotence(self):
        runner = ResilientRunner(self.work)
        out = self.root/"real.wav"
        try:
            first = runner.render(self.inp, out, self.cfg)
            self.assertEqual(first["runtime_status"], "SUCCEEDED")
            self.assertTrue(runner.verify(out)["ok"])
            second = runner.render(self.inp, out, self.cfg)
            self.assertEqual(second["runtime_status"], "IDEMPOTENT_SKIP")
        finally:
            runner.close()

    def test_second_run_suppresses_core_call(self):
        runner = ResilientRunner(self.work)
        core = CountingCore()
        out = self.root/"skip.wav"
        try:
            runner.render(self.inp, out, self.cfg, core_callable=core)
            runner.render(self.inp, out, self.cfg, core_callable=core)
            self.assertEqual(core.calls, 1)
        finally:
            runner.close()

    def test_foreign_output_is_never_overwritten(self):
        out = self.root/"foreign.wav"
        out.write_bytes(b"foreign")
        runner = ResilientRunner(self.work)
        try:
            with self.assertRaises(ForeignOutputError):
                runner.render(self.inp, out, self.cfg, core_callable=CountingCore())
            self.assertEqual(out.read_bytes(), b"foreign")
        finally:
            runner.close()

    def test_pending_commit_recovers_without_rerender(self):
        runner = ResilientRunner(self.work)
        core = CountingCore()
        out = self.root/"pending.wav"
        original_atomic = __import__("pdrm_runtime.runner", fromlist=["atomic_write_json"]).atomic_write_json

        def fail_sidecar(path, obj):
            p = Path(path)
            if p == out.with_name(out.name + ".pdrm.json"):
                raise RuntimeError("injected crash after final publish")
            return original_atomic(path, obj)

        try:
            with mock.patch("pdrm_runtime.runner.atomic_write_json", side_effect=fail_sidecar):
                with self.assertRaises(RuntimeError):
                    runner.render(self.inp, out, self.cfg, core_callable=core)
            self.assertTrue(out.exists())
            self.assertEqual(core.calls, 1)
            recovered = runner.render(self.inp, out, self.cfg, core_callable=core)
            self.assertEqual(recovered["runtime_status"], "RECOVERED")
            self.assertEqual(core.calls, 1)
            self.assertTrue(runner.verify(out)["ok"])
        finally:
            runner.close()

    def test_corrupt_ledger_is_archived_and_rebuilt(self):
        runner = ResilientRunner(self.work)
        runner.close()
        ledger = self.work/"ledger.sqlite3"
        # remove WAL/SHM if left by platform before corrupting the main DB
        for p in (Path(str(ledger)+"-wal"), Path(str(ledger)+"-shm")):
            p.unlink(missing_ok=True)
        ledger.write_bytes(b"not a sqlite database")
        runner2 = ResilientRunner(self.work)
        try:
            self.assertTrue(runner2.doctor()["ok"])
            archived = list(self.work.glob("ledger.sqlite3.corrupt.*"))
            self.assertTrue(archived)
        finally:
            runner2.close()

    def test_stale_dead_pid_lock_is_reclaimed(self):
        lock_path = self.root/"job.lock.json"
        lock_path.write_text(json.dumps({
            "pid":99999999,
            "process_create_time":0.0,
            "token":"old",
        }), encoding="utf-8")
        lock = JobLock(lock_path)
        lock.acquire()
        try:
            self.assertTrue(lock_path.exists())
        finally:
            lock.release()
        self.assertFalse(lock_path.exists())
        self.assertTrue(list(self.root.glob("job.lock.json.stale-lock.*")))


if __name__ == "__main__":
    unittest.main()
