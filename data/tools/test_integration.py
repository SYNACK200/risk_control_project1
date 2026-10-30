import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from unittest.mock import patch
from contextlib import contextmanager
import types
from integration import insert_batches, validated_records, transaction

INSERT = types.SimpleNamespace(is_insert=True)


class Connection:
    def __init__(self): self.batches = []
    def execute(self, statement, rows): self.batches.append(list(rows))


class BatchTests(unittest.TestCase):
    def test_stream_batches_and_tail(self):
        conn = Connection()
        insert_batches(conn, INSERT, ({'id': i} for i in range(2501)))
        self.assertEqual([len(batch) for batch in conn.batches], [1000, 1000, 501])
        self.assertEqual([row['id'] for batch in conn.batches for row in batch], list(range(2501)))

    def test_reject_unbounded_batch(self):
        with self.assertRaises(ValueError): insert_batches(Connection(), INSERT, [], 1001)

    def test_raw_sql_and_invalid_rows_rejected(self):
        with self.assertRaises(ValueError): insert_batches(Connection(), 'INSERT RAW SQL', [])
        self.assertEqual(list(validated_records('bank_account',[{'account_no':'0'*16}]))[0]['account_no'],'0000********0000')
        with self.assertRaises(ValueError): list(validated_records('bank_account',[{'task_id':1},{'task_id':2,'bank_name':'DEMO'}]))

    def test_context_returns_connection_on_success_and_failure(self):
        class Result:
            def one(self): return ('8.4.13',3307,'D:/RiskControlDemo/mysql84/data')
        class Conn:
            def execute(self, statement): return Result()
        class Engine:
            checked_out = 0
            @contextmanager
            def begin(self):
                self.checked_out += 1
                try: yield Conn()
                finally: self.checked_out -= 1
        sa=types.ModuleType('sqlalchemy'); sa.text=lambda value:value
        engine=Engine()
        with patch.dict(sys.modules,{'sqlalchemy':sa}):
            with transaction(engine): self.assertEqual(engine.checked_out,1)
            self.assertEqual(engine.checked_out,0)
            with self.assertRaises(RuntimeError):
                with transaction(engine): raise RuntimeError('synthetic caller failure')
            self.assertEqual(engine.checked_out,0)


if __name__ == '__main__': unittest.main()
