from __future__ import annotations

from pathlib import Path
import hashlib
import json
import os
import tempfile
import time
from typing import Any


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def stable_hash(obj: Any) -> str:
    data = json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, chunk_size: int = 4 * 1024 * 1024) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        while True:
            block = f.read(chunk_size)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def atomic_write_json(path: str | Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, sort_keys=True)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_name, path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        except OSError:
            pass


def read_json(path: str | Path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def archive_path(path: str | Path, suffix: str) -> Path:
    path = Path(path)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dst = path.with_name(path.name + f".{suffix}.{stamp}")
    index = 1
    while dst.exists():
        dst = path.with_name(path.name + f".{suffix}.{stamp}.{index}")
        index += 1
    os.replace(path, dst)
    return dst
