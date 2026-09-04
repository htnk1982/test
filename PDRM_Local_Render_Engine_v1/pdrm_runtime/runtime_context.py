from __future__ import annotations

from pathlib import Path
import os

from .util import atomic_write_json, now_iso


class RuntimeContext:
    max_round_allowed = 8

    def __init__(self, job_dir: str | Path):
        self.job_dir = Path(job_dir)
        self.heartbeat_path = self.job_dir / "heartbeat.json"
        self.cancel_path = self.job_dir / "CANCEL"

    def heartbeat(self, stage=None, progress=None, message=None, **kwargs):
        payload = {
            "ts": now_iso(),
            "pid": os.getpid(),
            "stage": stage,
            "progress": progress,
            "message": message,
        }
        payload.update(kwargs)
        atomic_write_json(self.heartbeat_path, payload)

    def is_cancelled(self):
        return self.cancel_path.exists()
