"""Encrypted snapshot failure and type preservation checks, no database."""
import datetime
import decimal
import json
import tempfile
import unittest
from pathlib import Path
from cryptography.fernet import Fernet, InvalidToken
from current_backup import encode, decode, save, restore
from current_schema import artifacts


class Result:
    def mappings(self): return []
    def first(self): return None


class EmptyConnection:
    def execute(self, *args): return Result()


class BackupTests(unittest.TestCase):
    def setUp(self):
        import sys
        artifacts()
        self.metadata = sys.modules['current_data_models'].Base.metadata
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'test.snapshot.enc'
        self.key = Fernet.generate_key()

    def test_exact_types_roundtrip(self):
        row = [decimal.Decimal('1.20'), datetime.datetime(2026, 11, 26, 12), datetime.date(2026, 11, 26), None, {'synthetic': True}]
        self.assertEqual(json.loads(json.dumps(row, default=encode), object_hook=decode), row)

    def test_empty_full_snapshot_roundtrip(self):
        expected = save(EmptyConnection(), self.metadata, self.path, self.key)
        self.assertEqual(restore(EmptyConnection(), self.metadata, self.path, self.key), expected)
        self.assertEqual(len(expected), 16)
        self.assertNotIn(b'app_user', self.path.read_bytes())

    def test_wrong_key_rejected_before_sql(self):
        save(EmptyConnection(), self.metadata, self.path, self.key)
        class NeverConnect:
            def execute(self, *args): raise AssertionError('No SQL before authentication')
        with self.assertRaises(InvalidToken):
            restore(NeverConnect(), self.metadata, self.path, Fernet.generate_key())

    def test_corruption_rejected(self):
        save(EmptyConnection(), self.metadata, self.path, self.key)
        self.path.write_bytes(self.path.read_bytes()[:-10] + b'corrupted!')
        with self.assertRaises(InvalidToken):
            restore(EmptyConnection(), self.metadata, self.path, self.key)

    def test_existing_data_rejected(self):
        save(EmptyConnection(), self.metadata, self.path, self.key)
        class Occupied:
            def execute(self, *args):
                class Row:
                    def first(self): return (1,)
                return Row()
        with self.assertRaises(ValueError):
            restore(Occupied(), self.metadata, self.path, self.key)


if __name__ == '__main__': unittest.main()
