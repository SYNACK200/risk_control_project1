"""No sockets or real DDL: schema metadata, guards and migration API fakes."""
import contextlib
import importlib.util
import io
import json
import pathlib
import re
import sys
import tempfile
import types
import unittest
from unittest import mock
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import core_schema as core

SCHEMA, DDL, DIGEST = core.artifacts()


class Cursor:
    description = [('key',)]
    def __init__(self, owner): self.owner, self.rows = owner, ()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def close(self): pass
    def fetchall(self): return self.rows
    def fetchone(self): return self.rows[0]
    def execute(self, sql, args=None):
        self.owner.queries.append(sql)
        self.rows = ()
        if sql.startswith('SELECT VERSION()'):
            self.rows = (('8.4.13', self.owner.port, 'D:/RiskControlDemo/mysql84/data/', 'root@localhost'),)
        elif sql.startswith('SELECT schema_name,'):
            self.rows = tuple((d, 'utf8mb4', 'utf8mb4_0900_ai_ci') for d in core.DATABASES)
        elif sql.startswith('SELECT table_schema,table_name,engine'):
            self.rows = tuple((core.database_for(t),t,'InnoDB','utf8mb4_0900_ai_ci','BASE TABLE') for t in SCHEMA)
        elif sql.startswith('SELECT table_schema,'):
            self.rows = tuple(self.owner.objects)
        elif sql.startswith('SELECT COUNT(*)'):
            self.rows = ((0,),)
        elif sql.startswith('SELECT column_name,'):
            table = args[1]
            rows = []
            for name, definition in SCHEMA[table].items():
                kind = re.match(r'^([A-Z]+(?:\([0-9,]+\))?(?: UNSIGNED)?)', definition)[1].lower()
                if kind == 'boolean': kind = 'tinyint(1)'
                if self.owner.bad_field and table == 'txn' and name == 'amount': kind = 'decimal(20,2)'
                textual = kind.startswith(('char(', 'varchar(', 'text'))
                ascii_col = 'CHARACTER SET ascii' in definition
                rows.append((name, kind, 'NO' if 'NOT NULL' in definition else 'YES',
                    'auto_increment' if 'AUTO_INCREMENT' in definition else '',
                    ('ascii' if ascii_col else 'utf8mb4') if textual else None,
                    ('ascii_bin' if ascii_col else 'utf8mb4_0900_ai_ci') if textual else None, None))
            self.rows = tuple(rows)
        elif sql.startswith('SELECT index_name,'):
            table = args[1]
            block = re.search(r'CREATE TABLE `[^`]+`\.`' + table + r'` \((.*?)\n\) ENGINE', DDL, re.S)[1]
            rows = []
            for line in block.splitlines():
                if 'PRIMARY KEY' in line:
                    rows += [('PRIMARY', c, 0) for c in re.findall('`([^`]+)`', line)]
                elif re.match(r'\s*(?:UNIQUE )?KEY ', line):
                    name = re.search(r'KEY ([a-z0-9_]+)', line)[1]
                    rows += [(name, c, 0 if 'UNIQUE KEY' in line else 1) for c in re.findall('`([^`]+)`', line)]
            self.rows = tuple(rows)
        elif sql.startswith('SELECT tc.table_name'):
            rows = []
            for table in SCHEMA:
                block = re.search(r'CREATE TABLE `[^`]+`\.`' + table + r'` \((.*?)\n\) ENGINE', DDL, re.S)[1]
                rows += [(table, c, 'YES') for c in re.findall(r'^  CHECK \((.*)\),?$', block, re.M)]
            self.rows = tuple(rows)
        elif sql.startswith('SELECT partition_name'):
            self.rows = tuple((n, 'RANGE COLUMNS', '`txn_date`', "'" + v + "'") for n, v in
                [('p_before','2026-10-01'),('p202610','2026-11-01'),('p202611','2026-12-01'),('p202612','2027-01-01'),('p_future','MAXVALUE')])
        elif sql.startswith('SELECT version_num'):
            self.rows = (('0001_core',),)
        elif sql.startswith('SHOW CREATE TABLE'):
            self.rows = (('txn', DDL),)
        elif sql.startswith('EXPLAIN '):
            path = 'task' if 'biz.task ' in sql else 'txn' if 'biz.txn ' in sql else 'metric_value' if 'metric_value ' in sql else 'report'
            self.rows = (({'task':'ix_task_status','txn':'ix_txn_task_date','metric_value':'ix_metric_task_code','report':'ix_report_task_version'}[path],),)


class Driver:
    def __init__(self):
        self.queries = []; self.objects = []; self.port = 3307; self.bad_field = False; self._closed = False
    def cursor(self): return Cursor(self)
    def connect(self, **kwargs):
        assert kwargs['host'] == '127.0.0.1' and kwargs['port'] == 3307
        assert isinstance(kwargs['password'], bytes)
        return self
    def commit(self): pass
    def close(self): self._closed = True


class CoreSchemaTests(unittest.TestCase):
    def test_contract_artifacts(self):
        self.assertEqual(len(SCHEMA), 11); self.assertEqual(sum(map(len, SCHEMA.values())), 82)
        self.assertEqual(len(DIGEST), 64)

    def test_da01_receipt_exists_and_passes(self):
        self.assertTrue(core.require_da01().startswith('da01-live-'))

    def test_fresh_existing_and_partial_classification(self):
        self.assertEqual(core.classify([], SCHEMA), 'fresh')
        objects = [(core.database_for(t), t, 'BASE TABLE') for t in SCHEMA] + [('rc_demo_biz','alembic_version','BASE TABLE')]
        self.assertEqual(core.classify(objects, SCHEMA), 'existing')
        for bad in [objects[:-1], objects[:2], objects + [('rc_demo_biz','extra','VIEW')]]:
            with self.assertRaises(core.SafeFailure): core.classify(bad, SCHEMA)

    def test_check_normalization(self):
        self.assertEqual(core.normalized_check("(`role` IN (_utf8mb4'审批人'))"), core.normalized_check("role IN ('审批人')"))

    def test_all_metadata_checks_and_actual_explain(self):
        driver = Driver()
        result = core.verify(driver.cursor(), SCHEMA, DDL)
        self.assertEqual(result['field_count'], 82)
        self.assertEqual(result['explain_matches'], 4)
        for key in ['tables_ok','fields_ok','primary_keys_ok','indexes_ok','constraints_ok','partitions_ok','foreign_keys_absent','revision_ok']:
            self.assertTrue(result[key], key)
        self.assertFalse(result['boundary_dml_tested'] or result['downgrade_tested'])
        self.assertFalse(any(q.startswith(('CREATE','DROP','INSERT','ALTER','GRANT')) for q in driver.queries))

    def test_type_drift_detected(self):
        driver = Driver(); driver.bad_field = True
        self.assertFalse(core.verify(driver.cursor(), SCHEMA, DDL)['fields_ok'])

    def test_plan_is_read_only_and_asks_once(self):
        driver = Driver()
        with mock.patch.object(core, 'dependencies', return_value=driver), mock.patch.object(core, 'request_secret', return_value='Synthetic-root-42!') as ask:
            result = core.run('CorePlan', 'root')
        self.assertTrue(result['ok']); self.assertEqual(result['core_report']['phase'], 'fresh')
        ask.assert_called_once()
        self.assertFalse(any(q.startswith(('CREATE','DROP','INSERT','ALTER','GRANT')) for q in driver.queries))

    def test_apply_mismatch_stops_before_input(self):
        with mock.patch.object(core, 'request_secret') as ask:
            with self.assertRaises(core.SafeFailure): core.run('CoreApply', 'root', False, DIGEST)
            with self.assertRaises(core.SafeFailure): core.run('CoreApply', 'root', True, '0' * 64)
        ask.assert_not_called()

    def test_wrong_instance_stops_before_writes(self):
        driver = Driver(); driver.port = 3306
        with self.assertRaises(core.SafeFailure): core.guard(driver.cursor(), 'root')
        self.assertEqual(len(driver.queries), 1)

    def test_apply_stops_on_complete_existing_objects_under_latest_authorization(self):
        driver = Driver()
        driver.objects = [(core.database_for(t),t,'BASE TABLE') for t in SCHEMA] + [('rc_demo_biz','alembic_version','BASE TABLE')]
        with mock.patch.object(core, 'dependencies', return_value=driver), \
             mock.patch.object(core, 'request_secret', return_value='Synthetic-fixture-42!'), \
             mock.patch.object(core, 'migration_dependencies_ready', return_value=True), \
             mock.patch.object(core, 'migration_upgrade') as upgrade:
            with self.assertRaisesRegex(core.SafeFailure, '^EXISTING_OBJECTS_STOP$'):
                core.run('CoreApply','root',True,DIGEST)
        upgrade.assert_not_called()
        self.assertFalse(core.state['writes_started'])

    def test_direct_migration_has_no_legacy_input(self):
        source = (core.DATA / 'migrations/env.py').read_text(encoding='utf-8')
        self.assertNotIn('getpass.getpass', source)
        self.assertIn("attributes.get('connection')", source)
        self.assertIn("context.get_revision_argument() != '0001_core'", source)

    def test_apply_uses_temp_baseline_and_fixed_migration_only(self):
        driver = Driver()
        verified = core.verify(driver.cursor(), SCHEMA, DDL)
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory); (root / 'evidence').mkdir()
            for name in ('core/schema.sql','core/schema.json','migrations/env.py','migrations/versions/0001_core.py'):
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((core.DATA / name).read_bytes())
            with mock.patch.object(core, 'DATA', root), mock.patch.object(core, 'artifacts', return_value=(SCHEMA, DDL, DIGEST)), \
                 mock.patch.object(core, 'require_da01', return_value='synthetic-receipt'), \
                 mock.patch.object(core, 'dependencies', return_value=driver), \
                 mock.patch.object(core, 'request_secret', return_value='Synthetic-root-42!'), \
                 mock.patch.object(core, 'read_response', return_value=core.PHRASE), \
                 mock.patch.object(core, 'migration_dependencies_ready', return_value=True), \
                 mock.patch.object(core, 'migration_upgrade', return_value=verified) as upgrade, \
                 contextlib.redirect_stdout(io.StringIO()):
                result = core.run('CoreApply', 'root', True, DIGEST)
            self.assertEqual(result['core_report']['phase'], 'applied')
            self.assertEqual(len(list((root / 'evidence').glob('core-before-*.json'))), 1)
            upgrade.assert_called_once_with(driver)


if __name__ == '__main__': unittest.main()
