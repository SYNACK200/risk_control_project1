"""Execute restore control flow against a fake SQL sink, never a MySQL service."""
import datetime
from contextlib import redirect_stdout
import io
from decimal import Decimal
from pathlib import Path
import re
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from logical_backup import restore
from test_snapshots import snapshot, task


class Cursor:
    def __init__(self,conn): self.conn=conn; self.result=[]
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def execute(self,sql,args=None):
        self.conn.sql.append(sql)
        if sql.startswith('SELECT COUNT(*) FROM information_schema.schemata'):
            self.result=[(int(self.conn.existing),)]
        elif sql.startswith('CREATE TABLE '):
            name=re.search(r'CREATE TABLE `([a-z_]+)`',sql)[1]
            self.conn.tables[name]=[]
        elif sql.startswith('SELECT '):
            name=re.search(r'FROM `rc_restore_[a-z]+`\.`([a-z_]+)`',sql)[1]
            self.result=list(self.conn.tables[name])
            if self.conn.damage and name=='task': self.result=[]
        return len(self.result)
    def executemany(self,sql,batch):
        self.conn.sql.append(sql)
        name=re.search(r'INSERT INTO `([a-z_]+)`',sql)[1]
        self.conn.tables[name].extend(batch)
    def fetchone(self): return self.result[0]
    def __iter__(self): return iter(self.result)


class Connection:
    def __init__(self,existing=False,damage=False):
        self.existing=existing; self.damage=damage; self.sql=[]; self.tables={}; self.committed=False
    def cursor(self,*args): return Cursor(self)
    def commit(self): self.committed=True


class RestoreFlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.folder=Path(self.tmp.name)/'snapshot'
        row=[1,1,1,datetime.datetime(2026,10,1),'in',Decimal('1.20'),Decimal('10001.20'),'SYNTHETIC','D***',1]
        snapshot(self.folder,{'task':[task(1,'PENDING')],'txn':[row]})
        cursors=types.ModuleType('pymysql.cursors'); cursors.SSCursor=object
        self.patch=patch.dict(sys.modules,{'pymysql.cursors':cursors}); self.patch.start()
    def tearDown(self): self.patch.stop(); self.tmp.cleanup()

    def test_roundtrip_fresh_schemas_and_exact_rows(self):
        conn=Connection()
        with patch('builtins.input',return_value='CREATE FRESH RESTORE SCHEMAS'), redirect_stdout(io.StringIO()):
            restore(conn,self.folder)
        self.assertTrue(conn.committed)
        self.assertEqual(len(conn.tables['txn']),1)
        self.assertEqual(len(conn.tables),11)
        self.assertTrue(all('rc_restore_' in sql for sql in conn.sql if sql.startswith('CREATE DATABASE')))
        self.assertFalse(any(sql.startswith(('DROP ','DELETE ','TRUNCATE ')) for sql in conn.sql))

    def test_existing_schema_stops_before_creation(self):
        conn=Connection(existing=True)
        with self.assertRaises(RuntimeError): restore(conn,self.folder)
        self.assertTrue(all(sql.startswith('SELECT ') for sql in conn.sql))

    def test_bad_source_stops_before_any_database_operation(self):
        (self.folder/'task.jsonl').write_text('[]\n')
        conn=Connection()
        with self.assertRaises(ValueError): restore(conn,self.folder)
        self.assertEqual(conn.sql,[])

    def test_restored_checksum_mismatch_never_claims_success(self):
        conn=Connection(damage=True)
        with patch('builtins.input',return_value='CREATE FRESH RESTORE SCHEMAS'):
            with self.assertRaises(RuntimeError): restore(conn,self.folder)


if __name__ == '__main__': unittest.main()
