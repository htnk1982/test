from __future__ import annotations

from pathlib import Path
import sqlite3

from .util import archive_path, now_iso


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    input_sha256 TEXT NOT NULL,
    config_sha256 TEXT NOT NULL,
    output_path TEXT NOT NULL,
    output_sha256 TEXT,
    output_pcm_sha256 TEXT,
    status TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_output_path_idx ON jobs(output_path);
"""


CORRUPTION_MARKERS = (
    "database disk image is malformed",
    "file is not a database",
    "database corruption",
    "malformed database schema",
)


def _archive_db_family(path: Path) -> None:
    for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        if p.exists():
            archive_path(p, "corrupt")


def _is_corruption_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CORRUPTION_MARKERS)


class Ledger:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = self._open_or_rebuild()

    def _connect(self):
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=FULL")
        return conn

    def _new_clean(self):
        conn = self._connect()
        conn.executescript(SCHEMA)
        conn.commit()
        return conn

    def _open_or_rebuild(self):
        conn = None
        try:
            conn = self._connect()
            row = conn.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                conn.close()
                conn = None
                _archive_db_family(self.path)
                return self._new_clean()
            conn.executescript(SCHEMA)
            conn.commit()
            return conn
        except sqlite3.DatabaseError as exc:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            # A locked, read-only, permission-denied, I/O, disk-full, etc.
            # condition is operational and must not be mislabeled as corruption.
            if not _is_corruption_error(exc):
                raise
            _archive_db_family(self.path)
            return self._new_clean()

    def close(self):
        self.conn.close()

    def upsert(self, job_id: str, input_hash: str, config_hash: str, output_path: str, status: str,
               output_hash: str | None = None, output_pcm_hash: str | None = None):
        self.conn.execute(
            """INSERT INTO jobs(job_id,input_sha256,config_sha256,output_path,output_sha256,output_pcm_sha256,status,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(job_id) DO UPDATE SET
                 input_sha256=excluded.input_sha256,
                 config_sha256=excluded.config_sha256,
                 output_path=excluded.output_path,
                 output_sha256=excluded.output_sha256,
                 output_pcm_sha256=excluded.output_pcm_sha256,
                 status=excluded.status,
                 updated_at=excluded.updated_at""",
            (job_id, input_hash, config_hash, output_path, output_hash, output_pcm_hash, status, now_iso()),
        )
        self.conn.commit()

    def get(self, job_id: str):
        row = self.conn.execute(
            "SELECT job_id,input_sha256,config_sha256,output_path,output_sha256,output_pcm_sha256,status,updated_at FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        keys = ["job_id","input_sha256","config_sha256","output_path","output_sha256","output_pcm_sha256","status","updated_at"]
        return dict(zip(keys, row))
