import datetime
from decimal import Decimal
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import unittest
from validation import money, timestamp, validate_record, mask_phone, identity_digest


class ValidationTests(unittest.TestCase):
    def test_money_bounds_and_no_float(self):
        self.assertEqual(money('9999999999999999.99'),Decimal('9999999999999999.99'))
        for value in (1.2,True,'NaN','1.001','1e2','10000000000000000'):
            with self.assertRaises(ValueError): money(value)
        with self.assertRaises(ValueError): money('0',positive=True)

    def test_timestamp_offset_required(self):
        self.assertEqual(timestamp('2026-10-01T00:00:00+08:00'),datetime.datetime(2026,10,1))
        for value in ('2026-10-01T00:00:00','2026-10-01T00:00:00+00:00'):
            with self.assertRaises(ValueError): timestamp(value)

    def test_masked_storage_and_unknown_field_rejected(self):
        self.assertEqual(validate_record('bank_account',{'account_no':'0000********0000'})['account_no'],'0000********0000')
        with self.assertRaises(ValueError): validate_record('bank_account',{'account_no':'0'*16})
        with self.assertRaises(ValueError): validate_record('staff_user',{'name':'SYNTHETIC RAW NAME'})
        with self.assertRaises(ValueError): validate_record('task',{'biz_no':'DEMO','new_column':1})

    def test_required_fields_and_unsigned_bounds(self):
        with self.assertRaises(ValueError): validate_record('txn',{'amount':'1.00'})
        for value in (-1,True,2**64):
            with self.assertRaises(ValueError): validate_record('bank_account',{'task_id':value})

    def test_json_scan_and_exact_metric(self):
        with self.assertRaises(ValueError): validate_record('report',{'evidence':{'raw_identifier':'0'*18}})
        self.assertEqual(validate_record('metric_value',{'value_num':'1.12345678'})['value_num'],Decimal('1.12345678'))
        with self.assertRaises(ValueError): validate_record('metric_value',{'value_num':'1.123456789'})

    def test_phone_mask_and_keyed_identity_hash(self):
        self.assertEqual(mask_phone('0'*11),'000****0000')
        key=bytes(range(32))  # Deterministic synthetic test material, never a deployed secret.
        digest=identity_digest('SYNTHETIC_IDENTIFIER',key)
        self.assertEqual(len(digest),64)
        self.assertNotEqual(digest,identity_digest('SYNTHETIC_IDENTIFIER',bytes(reversed(range(32)))))
        with self.assertRaises(ValueError): identity_digest('SYNTHETIC_IDENTIFIER',b'')


if __name__ == '__main__': unittest.main()
