from __future__ import annotations

from pathlib import Path
import json
import os
import shutil

from pdrm_engine import __version__ as CORE_VERSION
from pdrm_engine.engine import run_job as default_run_job
from pdrm_engine.io_utils import pcm_sha256

from .ledger import Ledger
from .lock import JobLock
from .runtime_context import RuntimeContext
from .util import atomic_write_json, read_json, sha256_file, stable_hash, archive_path, now_iso


class ForeignOutputError(RuntimeError):
    pass


class RetryLimitError(RuntimeError):
    pass


class InputChangedError(RuntimeError):
    pass


def _sidecar_path(output_path: Path) -> Path:
    return output_path.with_name(output_path.name + ".pdrm.json")


def _job_id(input_hash: str, config_hash: str, output_path: Path) -> str:
    return stable_hash({
        "input": input_hash,
        "config": config_hash,
        "output": str(output_path.resolve()),
        "core": CORE_VERSION,
    })[:24]


def _safe_publish_no_replace(src: Path, dst: Path) -> None:
    """Publish without ever overwriting a pre-existing destination.

    A crash during copy can leave a partial destination. pending_commit.json
    records ownership so the next run may safely remove/recover that partial.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(str(dst), flags, 0o600)
    try:
        with src.open("rb") as inp, os.fdopen(fd, "wb", closefd=True) as out:
            while True:
                block = inp.read(4 * 1024 * 1024)
                if not block:
                    break
                out.write(block)
            out.flush()
            try:
                os.fsync(out.fileno())
            except OSError:
                pass
    except Exception:
        # Intentionally do not delete dst: pending recovery must decide whether
        # the path is ours before touching it.
        raise


def _matching_sidecar(sidecar: dict, job_id: str, input_hash: str, config_hash: str, output: Path) -> bool:
    if not sidecar:
        return False
    if sidecar.get("job_id") != job_id:
        return False
    if sidecar.get("input_sha256") != input_hash or sidecar.get("config_sha256") != config_hash:
        return False
    if not output.exists():
        return False
    expected = sidecar.get("output_sha256")
    expected_pcm = sidecar.get("output_pcm_sha256")
    if not expected or sha256_file(output) != expected:
        return False
    if expected_pcm and pcm_sha256(output) != expected_pcm:
        return False
    return True


class ResilientRunner:
    def __init__(self, work_root: str | Path):
        self.work_root = Path(work_root).resolve()
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.jobs_root = self.work_root / "jobs"
        self.jobs_root.mkdir(exist_ok=True)
        self.ledger = Ledger(self.work_root / "ledger.sqlite3")

    def close(self):
        self.ledger.close()

    def doctor(self) -> dict:
        import sqlite3
        import psutil
        from pdrm_engine import MAX_ROUND_ALLOWED
        from pdrm_engine.engine import run_job
        probe = self.work_root / ".doctor-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return {
            "ok": True,
            "core_import": callable(run_job),
            "core_version": CORE_VERSION,
            "max_round_allowed": MAX_ROUND_ALLOWED,
            "round9_locked": MAX_ROUND_ALLOWED == 8,
            "sqlite": sqlite3.sqlite_version,
            "sqlite_journal_mode": self.ledger.journal_mode,
            "sqlite_degraded_reason": self.ledger.degraded_reason,
            "psutil": psutil.__version__,
            "work_root": str(self.work_root),
        }

    def _recover_pending(self, job_dir: Path, job_id: str, output: Path) -> dict | None:
        pending_path = job_dir / "pending_commit.json"
        pending = read_json(pending_path, None)
        if not pending or pending.get("job_id") != job_id:
            return None
        staging = Path(pending["staging_path"])
        expected = pending["output_sha256"]
        expected_pcm = pending.get("output_pcm_sha256")

        if output.exists():
            actual = sha256_file(output)
            if actual == expected and (not expected_pcm or pcm_sha256(output) == expected_pcm):
                sidecar = dict(pending["sidecar"])
                atomic_write_json(_sidecar_path(output), sidecar)
                pending_path.unlink(missing_ok=True)
                staging.unlink(missing_ok=True)
                return {"recovered": "FINAL_ALREADY_PUBLISHED", "sidecar": sidecar}
            # pending proves this final path was being published by this job.
            archive_path(output, "partial-owned")

        if not staging.exists() or sha256_file(staging) != expected:
            pending_path.unlink(missing_ok=True)
            return None

        _safe_publish_no_replace(staging, output)
        if sha256_file(output) != expected:
            raise RuntimeError("published output hash mismatch during recovery")
        sidecar = dict(pending["sidecar"])
        atomic_write_json(_sidecar_path(output), sidecar)
        pending_path.unlink(missing_ok=True)
        staging.unlink(missing_ok=True)
        return {"recovered": "PENDING_COMMIT_COMPLETED", "sidecar": sidecar}

    def verify(self, output_path: str | Path) -> dict:
        output = Path(output_path).resolve()
        sidecar_path = _sidecar_path(output)
        sidecar = read_json(sidecar_path, None)
        failures = []
        if not output.exists():
            failures.append("OUTPUT_MISSING")
        if not sidecar:
            failures.append("SIDECAR_MISSING")
        if output.exists() and sidecar:
            if sha256_file(output) != sidecar.get("output_sha256"):
                failures.append("OUTPUT_HASH_MISMATCH")
            expected_pcm = sidecar.get("output_pcm_sha256")
            if expected_pcm and pcm_sha256(output) != expected_pcm:
                failures.append("PCM_HASH_MISMATCH")
            if sidecar.get("round9_executed") is not False:
                failures.append("ROUND9_CONTRACT_VIOLATION")
        return {"ok": not failures, "failures": failures, "sidecar": sidecar}

    def render(self, input_path: str | Path, output_path: str | Path, config: dict,
               core_callable=None, max_attempts: int = 3) -> dict:
        input_path = Path(input_path).resolve()
        output = Path(output_path).resolve()
        if not input_path.exists():
            raise FileNotFoundError(input_path)
        input_hash = sha256_file(input_path)
        config_hash = stable_hash({"config": config, "core_version": CORE_VERSION})
        job_id = _job_id(input_hash, config_hash, output)
        job_dir = self.jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        lock = JobLock(job_dir / "job.lock.json")
        sidecar_path = _sidecar_path(output)
        attempts_path = job_dir / "attempts.json"

        with lock:
            recovered = self._recover_pending(job_dir, job_id, output)
            if recovered:
                sidecar = recovered["sidecar"]
                self.ledger.upsert(job_id, input_hash, config_hash, str(output), "SUCCEEDED",
                                   sidecar.get("output_sha256"), sidecar.get("output_pcm_sha256"))
                return {"runtime_status": "RECOVERED", **recovered}

            sidecar = read_json(sidecar_path, None)
            if output.exists():
                if _matching_sidecar(sidecar or {}, job_id, input_hash, config_hash, output):
                    self.ledger.upsert(job_id, input_hash, config_hash, str(output), "SUCCEEDED",
                                       sidecar.get("output_sha256"), sidecar.get("output_pcm_sha256"))
                    return {"runtime_status": "IDEMPOTENT_SKIP", "sidecar": sidecar}
                if sidecar and sidecar.get("job_id") == job_id and sidecar.get("input_sha256") == input_hash and sidecar.get("config_sha256") == config_hash:
                    archive_path(output, "stale-owned")
                    archive_path(sidecar_path, "stale-owned")
                else:
                    raise ForeignOutputError(f"refusing to overwrite foreign output: {output}")

            manifest = {
                "job_id": job_id,
                "created_at": now_iso(),
                "input_path": str(input_path),
                "input_sha256": input_hash,
                "config": config,
                "config_sha256": config_hash,
                "output_path": str(output),
                "core_version": CORE_VERSION,
                "max_round_allowed": 8,
            }
            atomic_write_json(job_dir / "manifest.json", manifest)

            attempt_state = read_json(attempts_path, {}) or {}
            failures = int(attempt_state.get("failures", 0))
            if failures >= int(max_attempts):
                raise RetryLimitError(f"job failure limit reached: {failures}/{max_attempts}")

            staging = job_dir / "render.wav"
            core_result_path = job_dir / "core_result.json"
            reusable = False
            old_result = read_json(core_result_path, None)
            if staging.exists() and old_result:
                expected = old_result.get("output_file_sha256")
                if expected and sha256_file(staging) == expected and old_result.get("round9_executed") is False:
                    reusable = True
                else:
                    staging.unlink(missing_ok=True)
                    core_result_path.unlink(missing_ok=True)

            self.ledger.upsert(job_id, input_hash, config_hash, str(output), "RUNNING")
            try:
                if reusable:
                    core_result = old_result
                else:
                    staging.unlink(missing_ok=True)
                    ctx = RuntimeContext(job_dir)
                    call = core_callable or default_run_job
                    core_result = call(input_path, staging, config, ctx)
                    if core_result.get("round9_executed") is not False:
                        raise RuntimeError("core reported Round 9 execution")
                    if int(core_result.get("max_round_executed", 99)) > 8:
                        raise RuntimeError("core exceeded round 8 hard lock")
                    if not staging.exists():
                        raise RuntimeError("core returned without staging output")
                    if sha256_file(staging) != core_result.get("output_file_sha256"):
                        raise RuntimeError("core result hash does not match staging output")
                    atomic_write_json(core_result_path, core_result)

                # The source is immutable for a job. A changed source invalidates
                # every cached analysis/render result and must never be committed.
                if not input_path.exists() or sha256_file(input_path) != input_hash:
                    raise InputChangedError("INPUT_CHANGED_DURING_RENDER")

                output_hash = sha256_file(staging)
                output_pcm_hash = pcm_sha256(staging)
                sidecar = {
                    "schema": 1,
                    "job_id": job_id,
                    "input_sha256": input_hash,
                    "config_sha256": config_hash,
                    "core_version": CORE_VERSION,
                    "output_sha256": output_hash,
                    "output_pcm_sha256": output_pcm_hash,
                    "final_status": core_result.get("final_status"),
                    "round9_executed": False,
                    "max_round_executed": core_result.get("max_round_executed", 8),
                    "committed_at": now_iso(),
                }
                pending = {
                    "job_id": job_id,
                    "staging_path": str(staging),
                    "final_path": str(output),
                    "output_sha256": output_hash,
                    "output_pcm_sha256": output_pcm_hash,
                    "sidecar": sidecar,
                }
                atomic_write_json(job_dir / "pending_commit.json", pending)
                _safe_publish_no_replace(staging, output)
                if sha256_file(output) != output_hash or pcm_sha256(output) != output_pcm_hash:
                    raise RuntimeError("post-publish hash verification failed")
                atomic_write_json(sidecar_path, sidecar)
                (job_dir / "pending_commit.json").unlink(missing_ok=True)
                staging.unlink(missing_ok=True)
                self.ledger.upsert(job_id, input_hash, config_hash, str(output), "SUCCEEDED", output_hash, output_pcm_hash)
                atomic_write_json(attempts_path, {"failures": failures, "last_status": "SUCCEEDED"})
                return {"runtime_status": "SUCCEEDED", "sidecar": sidecar, "core_result": core_result}
            except Exception as exc:
                failures += 1
                atomic_write_json(attempts_path, {"failures": failures, "last_status": "FAILED", "error": repr(exc)})
                self.ledger.upsert(job_id, input_hash, config_hash, str(output), "FAILED")
                raise
