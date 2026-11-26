"""Offline migration and retention safety regressions; no DB connection."""
import copy
import datetime
import json
import unittest
from current_schema import artifacts
from current_migration import plan
from retention_preview import preview


class OperationTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = json.loads(artifacts()['schema.json'])

    def test_current_snapshot_is_noop(self):
        self.assertEqual(plan(self.snapshot)['up'], [])

    def test_nullable_addition_has_reverse(self):
        del self.snapshot['tables']['txn']['extra']
        result = plan(self.snapshot)
        self.assertEqual(result['status'], 'review_required')
        self.assertIn('ADD COLUMN extra JSON', result['up'][0])
        self.assertIn('DROP COLUMN `extra`', result['down'][0])

    def test_required_addition_blocks_all_sql(self):
        del self.snapshot['tables']['app_user']['username']
        result = plan(self.snapshot)
        self.assertTrue(result['blockers'])
        self.assertEqual(result['up'], [])

    def test_changed_type_blocks_all_sql(self):
        self.snapshot['tables']['txn']['amount']['type'] = 'FLOAT'
        self.assertEqual(plan(self.snapshot)['status'], 'blocked')

    def test_new_table_is_ordered_for_rollback(self):
        del self.snapshot['tables']['custom_metric']
        result = plan(self.snapshot)
        self.assertIn('CREATE TABLE custom_metric', result['up'][0])
        self.assertEqual(result['down'], ['DROP TABLE `custom_metric`;'])

    def test_removed_field_blocks(self):
        self.snapshot['tables']['txn']['obsolete'] = {'type': 'TEXT', 'nullable': True}
        self.assertEqual(plan(self.snapshot)['status'], 'blocked')

    def test_retention_keeps_audit_and_requires_policy(self):
        now = datetime.datetime.fromisoformat('2026-11-26T12:00:00+08:00')
        rows = [{'kind': kind, 'id': i, 'created_at': '2020-01-01T00:00:00+08:00'}
                for i, kind in enumerate(['file', 'audit'], 1)]
        self.assertEqual([r['action'] for r in preview(rows, now, {'file': 30})], ['archive_review', 'retain'])
        with self.assertRaises(ValueError):
            preview(rows, now, {})

    def test_retention_rejects_original_text(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        with self.assertRaises(ValueError):
            preview([{'kind': 'file', 'id': 1, 'created_at': now.isoformat(), 'raw_text': 'synthetic'}], now, {'file': 30})


if __name__ == '__main__':
    unittest.main()
