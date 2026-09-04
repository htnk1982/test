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


if __name__ == "__main__":
    unittest.main()
