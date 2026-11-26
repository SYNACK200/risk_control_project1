"""Current contract regression checks against an in-memory SQLite database."""
import json
import unittest
from current_schema import artifacts, ROOT, OUTPUT
from sqlalchemy import create_engine, insert, select


class CurrentSchemaTests(unittest.TestCase):
    def setUp(self):
        self.generated = artifacts()
        import sys
        self.models = sys.modules['current_data_models']
        self.engine = create_engine('sqlite:///:memory:')
        self.models.Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)

    def test_snapshot_matches_current_models(self):
        for name, content in self.generated.items():
            self.assertEqual((OUTPUT / name).read_text(encoding='utf-8'), content)

    def test_same_file_can_be_supplemented_with_a_new_sequence(self):
        table = self.models.TaskFile.__table__
        with self.engine.begin() as conn:
            conn.execute(insert(table), [dict(task_id=1, file_id=1, role='original', seq=1),
                                        dict(task_id=1, file_id=1, role='supplement', seq=2)])
            self.assertEqual(len(conn.execute(select(table)).all()), 2)

    def test_missing_date_and_metric_remain_null(self):
        with self.engine.begin() as conn:
            txn = self.models.Txn.__table__
            metric = self.models.MetricValue.__table__
            conn.execute(insert(txn).values(task_id=1, extra={'custom_field': 'synthetic'}))
            conn.execute(insert(metric).values(task_id=1, metric_code='A01', metric_name='synthetic', value_num=None))
            self.assertIsNone(conn.execute(select(txn.c.txn_date)).scalar_one())
            self.assertIsNone(conn.execute(select(metric.c.value_num)).scalar_one())
            self.assertEqual(conn.execute(select(txn.c.extra)).scalar_one(), {'custom_field': 'synthetic'})

    def test_queued_soft_delete_and_report_history(self):
        from datetime import datetime
        with self.engine.begin() as conn:
            task = self.models.Task.__table__
            report = self.models.Report.__table__
            conn.execute(insert(task).values(biz_no='synthetic', status='QUEUED', deleted_at=datetime(2026, 11, 26)))
            conn.execute(insert(report), [dict(task_id=1, version=1, verification={'status': 'pending'}),
                                          dict(task_id=1, version=2, verification={'status': 'done'})])
            self.assertEqual(conn.execute(select(task.c.status)).scalar_one(), 'QUEUED')
            self.assertIsNotNone(conn.execute(select(task.c.deleted_at)).scalar_one())
            self.assertEqual(conn.execute(select(report.c.version).order_by(report.c.version)).scalars().all(), [1, 2])


if __name__ == '__main__':
    unittest.main()
