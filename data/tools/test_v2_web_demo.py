"""Existing-database verifier regressions. No database connection or credentials."""
import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from v2.web_demo import verify


class Cursor:
    description = [('key',),('type',)]
    def __init__(self, wrong=False):
        self.sql = ''
        self.calls = []
        self.wrong = wrong
    def __enter__(self): return self
    def __exit__(self,*args): pass
    def execute(self,sql,args=None):
        self.calls.append(sql)
        if not sql.startswith(('SELECT ','SHOW ','EXPLAIN ')):
            raise AssertionError('Verifier must never write')
        self.sql=sql
    def fetchone(self):
        if 'VERSION()' in self.sql: return ('8.4.13',3307,'D:/RiskControlDemo/mysql84/data')
        if 'CURRENT_USER()' in self.sql:
            return ('root@localhost' if self.wrong else 'rc_demo_app@localhost','rc_demo_v2')
        return ('txn','PARTITION BY RANGE COLUMNS (txn_date)')
    def fetchall(self):
        if self.sql=='SHOW TABLES':
            return [(t,) for t in ('file_obj','task','task_file','bank_account','txn','metric_value','report','template','rule','audit_log')]
        if self.sql.startswith('EXPLAIN'): return [('PRIMARY','ref')]
        return [('模***',)]*3


class Tests(unittest.TestCase):
    def test_readonly_verification_and_four_plans(self):
        cursor=Cursor()
        class Connection:
            def cursor(self): return cursor
        result=verify(Connection())
        self.assertTrue(result['four_index_paths_pass'])
        self.assertFalse(result['reader_permissions_tested'])
        self.assertEqual(len(result['explain']),4)
        self.assertTrue(all(sql.startswith(('SELECT ','SHOW ','EXPLAIN ')) for sql in cursor.calls))

    def test_wrong_identity_stops_before_application_queries(self):
        cursor=Cursor(wrong=True)
        class Connection:
            def cursor(self): return cursor
        with self.assertRaises(RuntimeError): verify(Connection())
        self.assertEqual(len(cursor.calls),2)


if __name__=='__main__': unittest.main()
