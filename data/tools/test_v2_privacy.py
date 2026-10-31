"""Synthetic business privacy examples only. No customer data or live services."""
import datetime
from decimal import Decimal
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from privacy import prepare_for_storage, audit_metadata
from retention import retention_preview
from integration import validated_records, validated_v2_records
from validation import validate_record
from v2.records import TABLES, prepare_record


class PrivacyTests(unittest.TestCase):
    def test_latest_contract(self):
        self.assertEqual(len(TABLES),11); self.assertEqual(sum(map(len,TABLES.values())),89)
        self.assertIn('task_file',TABLES); self.assertNotIn('appeal',TABLES)
        self.assertIn('confidence',TABLES['txn']); self.assertIn('threshold_version',TABLES['report'])

    def test_mask_before_storage(self):
        row = list(validated_records('bank_account',[{'account_no':'0000000000000000'}]))[0]
        self.assertEqual(row['account_no'],'0000********0000')
        self.assertEqual(prepare_for_storage('staff_user',{'name':'模拟姓名'})['name'],'模***')

    def test_v2_transaction_preserves_business_values(self):
        row = prepare_record('txn',{'amount':'12.30','balance':'21.10','counterparty_name':'模拟对象','coord_x':'2.5','confidence':'0.95','drop_reason':'SYNTHETIC'})
        self.assertEqual(row['amount'],Decimal('12.30')); self.assertEqual(row['counterparty_name'],'模***')
        self.assertEqual(row['confidence'],'0.95')
        self.assertEqual(prepare_record('txn',{'amount':'123456789012.34'})['amount'],Decimal('123456789012.34'))
        with self.assertRaises(ValueError): prepare_record('txn',{'amount':1.25})

    def test_no_password_or_raw_text_in_nested_json(self):
        for payload in [{'password':'SYNTHETIC'}, {'nested':{'raw_text':'SYNTHETIC'}}, {'bytes':b'SYNTHETIC'}]:
            with self.assertRaises(ValueError): prepare_record('report',{'evidence':payload})
            with self.assertRaises(ValueError): validate_record('report',{'evidence':payload})
        with self.assertRaises(ValueError): validate_record('report',{'evidence':'{"password":"SYNTHETIC"}'})

    def test_json_string_uses_same_privacy_rule(self):
        with self.assertRaises(ValueError): prepare_record('report',{'evidence':'{"password":"SYNTHETIC"}'})

    def test_material_and_versions(self):
        row = list(validated_v2_records('task_file',[{'task_id':1,'file_id':2,'role':'supplement','seq':2}]))[0]
        self.assertEqual(row['seq'],2)
        with self.assertRaises(ValueError): prepare_record('task_file',{'role':'wrong'})
        self.assertEqual(prepare_record('report',{'version':2,'metric_set_version':2,'threshold_version':1})['version'],2)

    def test_audit_contains_no_arbitrary_detail(self):
        self.assertEqual(set(audit_metadata('password_attempt',1,'failure')),{'event','object_id','outcome'})
        with self.assertRaises(TypeError): audit_metadata('password_attempt',1,'failure',**{'password':'SYNTHETIC'})

    def test_retention_is_preview_and_audit_stays(self):
        tz = datetime.timezone(datetime.timedelta(hours=8))
        now = datetime.datetime(2026,10,30,tzinfo=tz)
        old = now - datetime.timedelta(days=31)
        rows = [{'kind':k,'id':i,'created_at':old} for i,k in enumerate(('file','txn','report','audit'))]
        result = retention_preview(rows,now,30) # Explicit synthetic period, not production policy.
        self.assertEqual(result[-1]['action'],'retain')
        self.assertTrue(all(r['action']=='archive_review' for r in result[:-1]))
        self.assertTrue(all(set(r)=={'kind','id','action'} for r in result))


if __name__ == '__main__': unittest.main()
