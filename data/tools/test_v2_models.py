"""Real SQLAlchemy models and events; no connection or SQL execution."""
import pathlib
import sys
import unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]))
from v2.models import build_ddl, load_backend_models
from v2.session import install_privacy
from sqlalchemy.orm import Session
from sqlalchemy.exc import UnboundExecutionError
from v2.migration import upgrade
from v2.deploy import grant_role, GRANTS

ROOT = pathlib.Path('C:/Users/姜佳庆/AppData/Local/Temp/risk_control_project1-v2-e9baadf')


class ModelTests(unittest.TestCase):
    def test_reviewed_ddl_is_stable_across_processes(self):
        import subprocess
        program = ('import sys,pathlib; sys.path.insert(0,"data"); '
                   'from v2.models import build_ddl; '
                   '_,ddl=build_ddl(pathlib.Path(sys.argv[1])); '
                   'assert ddl==pathlib.Path("data/v2/schema.sql").read_text(encoding="utf-8")')
        for _ in range(5):
            result = subprocess.run([sys.executable,'-B','-c',program,str(ROOT)],
                                    cwd=pathlib.Path(__file__).resolve().parents[2],
                                    capture_output=True)
            self.assertEqual(result.returncode,0,'DDL must match in every fresh process')

    def test_approved_role_grants_are_object_scoped(self):
        calls=[]
        class Cursor:
            def execute(self,sql): calls.append(sql)
            def fetchall(self):
                return tuple(('GRANT '+', '.join(sorted(p))+' ON `rc_demo_v2`.`'+t+'` TO `rc_role_app`@`localhost`',) for t,p in GRANTS.items())
        grant_role(Cursor())
        self.assertEqual(len([q for q in calls if q.startswith('GRANT ')]),10)
        self.assertEqual(GRANTS['audit_log'],{'INSERT'})
        self.assertNotIn('staff_user',GRANTS)
        self.assertFalse(any('DELETE' in q or 'GRANT OPTION' in q for q in calls))

    def test_broad_grant_never_counts_as_accepted(self):
        class Cursor:
            def execute(self,sql): pass
            def fetchall(self): return (('GRANT ALL PRIVILEGES ON *.* TO `rc_role_app`@`localhost`',),)
        with self.assertRaises(RuntimeError): grant_role(Cursor())

    def test_no_approval_never_opens_database(self):
        class NeverConnect:
            def cursor(self): raise AssertionError('Database must not be accessed')
        with self.assertRaises(RuntimeError): upgrade(NeverConnect())

    def test_existing_v2_database_stops_without_writes(self):
        queries = []
        class Cursor:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def execute(self,sql,args=None): queries.append(sql)
            def fetchone(self): return ('8.4.13',3307,'D:/RiskControlDemo/mysql84/data/') if len(queries)==1 else ('rc_demo_v2',)
        class Connection:
            def cursor(self): return Cursor()
        with self.assertRaises(RuntimeError): upgrade(Connection(),approved=True)
        self.assertTrue(all(q.startswith('SELECT ') for q in queries))

    def test_ddl_uses_latest_models_and_partition_rules(self):
        metadata, sql = build_ddl(ROOT)
        self.assertEqual(len(metadata.tables),11)
        self.assertIn('task_file',metadata.tables); self.assertNotIn('appeal',metadata.tables)
        self.assertEqual(list(metadata.tables['txn'].primary_key.columns.keys()),['id','txn_date'])
        self.assertEqual(len(metadata.tables['txn'].foreign_key_constraints),0)
        self.assertIn('PARTITION BY RANGE COLUMNS',sql)
        self.assertIn('uq_task_file',sql)

    def test_real_flush_event_masks_pending_backend_rows(self):
        models = load_backend_models(ROOT)
        class ProtectedSession(Session): pass
        install_privacy(ProtectedSession)
        with ProtectedSession() as session:
            row = models.BankAccount(task_id=1,account_no='0000000000000000')
            audit = models.AuditLog(action='create_task_failed',detail='SYNTHETIC RAW DETAIL')
            session.add_all([row,audit])
            # Flush invokes our actual event before stopping for absence of a DB bind.
            with self.assertRaises(UnboundExecutionError): session.flush()
            self.assertEqual(row.account_no,'0000********0000')
            self.assertEqual(audit.detail,'event=create_task_failed')

    def test_report_payload_maps_versions_and_actual_material(self):
        models=load_backend_models(ROOT)
        class ProtectedSession(Session): pass
        install_privacy(ProtectedSession)
        with ProtectedSession() as session:
            file=models.FileObj(id=2,sha256='0'*64,pages=1)
            link=models.TaskFile(task_id=1,file_id=2,role='original',seq=1)
            report=models.Report(task_id=1,version=1,payload={'metric_set_version':2,'threshold_version':3,'materials':[{'file_id':0}]})
            session.add_all([file,link,report])
            with self.assertRaises(UnboundExecutionError): session.flush()
            self.assertEqual(report.metric_set_version,2)
            self.assertEqual(report.threshold_version,3)
            self.assertEqual(report.payload['materials'][0]['file_id'],2)


if __name__ == '__main__': unittest.main()
