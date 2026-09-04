from __future__ import annotations

from pathlib import Path
import os
import sqlite3
import tempfile

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

WAL_OPERATIONAL_MARKERS = (
    "disk i/o error",
    "locking protocol",
    "database is locked",
)


def _archive_db_family(path: Path, label: str = "corrupt") -> None:
    for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm"), Path(str(path) + "-journal")):
        if p.exists():
            archive_path(p, label)


def _is_corruption_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in CORRUPTION_MARKERS)


def _is_wal_operational_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in WAL_OPERATIONAL_MARKERS)


class Ledger:
    """Small rebuildable operational ledger.

    WAL is preferred. On some Windows mapped/removable/cloud-backed volumes an
    abrupt process kill can leave WAL/SHM recovery unusable even though normal
    file I/O still works. The ledger is not the authority for published audio;
    sidecars + hashes are. Therefore, after proving that a fresh DELETE-journal
    transaction works in the same directory, we may archive the unusable WAL
    family and rebuild the ledger in DELETE/FULL mode rather than strand the
    whole renderer. The fallback is explicit and observable via journal_mode and
    degraded_reason; actual media/output safety is still enforced elsewhere.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.journal_mode = "UNKNOWN"
        self.degraded_reason: str | None = None
        self.conn = self._open_or_rebuild()

    def _connect_mode(self, mode: str):
        conn = sqlite3.connect(str(self.path), timeout=10.0)
        try:
            conn.execute("PRAGMA busy_timeout=10000")
            row = conn.execute(f"PRAGMA journal_mode={mode}").fetchone()
            actual = str(row[0]).upper() if row else "UNKNOWN"
            conn.execute("PRAGMA synchronous=FULL")
            if mode.upper() == "WAL" and actual != "WAL":
                raise sqlite3.OperationalError(f"WAL journal mode unavailable (actual={actual})")
            self.journal_mode = actual
            return conn
        except Exception:
            conn.close()
            raise

    def _delete_mode_probe(self) -> bool:
        """Prove basic durable SQLite transactions work in this directory.

        This prevents a true read-only/disk-full/storage failure from being
        silently reclassified as a harmless WAL incompatibility.
        """
        fd, raw = tempfile.mkstemp(prefix=".pdrm_sqlite_probe_", suffix=".sqlite3", dir=str(self.path.parent))
        os.close(fd)
        probe = Path(raw)
        conn = None
        try:
            conn = sqlite3.connect(str(probe), timeout=5.0)
            row = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
            actual = str(row[0]).upper() if row else "UNKNOWN"
            if actual != "DELETE":
                return False
            conn.execute("PRAGMA synchronous=FULL")
            conn.execute("CREATE TABLE probe(v INTEGER NOT NULL)")
            conn.execute("INSERT INTO probe(v) VALUES(1)")
            conn.commit()
            check = conn.execute("PRAGMA quick_check").fetchone()
            return bool(check and str(check[0]).lower() == "ok")
        except sqlite3.Error:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            for p in (probe, Path(str(probe) + "-journal"), Path(str(probe) + "-wal"), Path(str(probe) + "-shm")):
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass

    def _new_clean(self, preferred_mode: str = "WAL"):
        conn = self._connect_mode(preferred_mode)
        conn.executescript(SCHEMA)
        conn.commit()
        return conn

    def _wal_fallback_or_raise(self, original_exc: BaseException):
        if not _is_wal_operational_error(original_exc):
            raise original_exc
        if not self._delete_mode_probe():
            raise original_exc

        # Preserve the entire failed family as evidence. This is operational
        # recovery, not corruption classification. Sidecars remain authoritative
        # for already-published outputs, so rebuilding this cache is safe.
        _archive_db_family(self.path, "wal-io-recovery")
        self.degraded_reason = f"WAL_IO_FALLBACK: {original_exc}"
        return self._new_clean("DELETE")

    def _open_or_rebuild(self):
        conn = None
        try:
            try:
                conn = self._connect_mode("WAL")
            except sqlite3.DatabaseError as exc:
                return self._wal_fallback_or_raise(exc)

            row = conn.execute("PRAGMA quick_check").fetchone()
            if not row or str(row[0]).lower() != "ok":
                conn.close()
                conn = None
                _archive_db_family(self.path, "corrupt")
                return self._new_clean("WAL")
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
            if _is_wal_operational_error(exc):
                return self._wal_fallback_or_raise(exc)
            if not _is_corruption_error(exc):
                raise
            _archive_db_family(self.path, "corrupt")
            try:
                return self._new_clean("WAL")
            except sqlite3.DatabaseError as wal_exc:
                return self._wal_fallback_or_raise(wal_exc)

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
