from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

from pdrm_runtime.ledger import Ledger


class LedgerErrorClassificationTests(unittest.TestCase):
    def test_operational_error_is_not_archived_as_corruption(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            with mock.patch(
                "pdrm_runtime.ledger.sqlite3.connect",
                side_effect=sqlite3.OperationalError("database is locked"),
            ), mock.patch("pdrm_runtime.ledger._archive_db_family") as archive:
                with self.assertRaises(sqlite3.OperationalError):
                    Ledger(path)
                archive.assert_not_called()

    def test_wal_disk_io_can_fallback_to_delete_after_same_directory_probe(self):
        class ForcedWalIoLedger(Ledger):
            def __init__(self, path):
                self._forced_once = False
                super().__init__(path)

            def _connect_mode(self, mode: str):
                if mode.upper() == "WAL" and not self._forced_once:
                    self._forced_once = True
                    raise sqlite3.OperationalError("disk I/O error")
                return super()._connect_mode(mode)

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "ledger.sqlite3"
            ledger = ForcedWalIoLedger(path)
            try:
                self.assertEqual(ledger.journal_mode, "DELETE")
                self.assertIn("WAL_IO_FALLBACK", ledger.degraded_reason or "")
                ledger.upsert("job", "in", "cfg", "out.wav", "RUNNING")
                self.assertEqual(ledger.get("job")["status"], "RUNNING")
            finally:
                ledger.close()


if __name__ == "__main__":
    unittest.main()
