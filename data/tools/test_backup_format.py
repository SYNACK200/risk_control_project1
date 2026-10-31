import datetime
import decimal
import json
import unittest
from logical_backup import encode, decode, row_text


class BackupFormatTests(unittest.TestCase):
    def test_lossless_amount_and_binary(self):
        values = [decimal.Decimal('9999999999999999.99'), b'\x00\xff', None, 'DEMO']
        parsed = json.loads(json.dumps(values, default=encode))
        self.assertEqual([decode(v) for v in parsed], values)

    def test_canonical_stream(self):
        row = [1, decimal.Decimal('1.20'), datetime.datetime(2026, 10, 1)]
        restored = [decode(v) for v in json.loads(row_text(row))]
        self.assertEqual(row_text(restored), row_text(row))


if __name__ == '__main__': unittest.main()
