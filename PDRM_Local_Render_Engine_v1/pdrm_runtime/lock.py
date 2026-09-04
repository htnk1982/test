from __future__ import annotations

from pathlib import Path
import json
import os
import socket
import uuid

import psutil

from .util import now_iso, read_json, archive_path


class LockBusy(RuntimeError):
    pass


def _same_process(pid: int, create_time: float) -> bool:
    try:
        p = psutil.Process(int(pid))
        if not p.is_running():
            return False
        return abs(float(p.create_time()) - float(create_time)) < 0.02
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError):
        return False


class JobLock:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.token = uuid.uuid4().hex
        self.pid = os.getpid()
        self.create_time = float(psutil.Process(self.pid).create_time())
        self.held = False

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            old = read_json(self.path, {}) or {}
            if _same_process(old.get("pid", -1), old.get("process_create_time", -1.0)):
                raise LockBusy(f"job lock is held by live process {old.get('pid')}")
            archive_path(self.path, "stale-lock")

        payload = {
            "pid": self.pid,
            "process_create_time": self.create_time,
            "token": self.token,
            "hostname": socket.gethostname(),
            "created_at": now_iso(),
        }
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(str(self.path), flags, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                try:
                    os.fsync(f.fileno())
                except OSError:
                    pass
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        self.held = True

    def release(self) -> None:
        if not self.held:
            return
        current = read_json(self.path, {}) or {}
        if current.get("token") == self.token:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
        self.held = False

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False
