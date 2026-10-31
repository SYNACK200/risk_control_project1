"""Safety-path tests with fake connections; never imports a live DB driver."""
import importlib.util
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class Result:
    def __init__(self, value): self.value = value
    def one(self): return self.value
    def scalar(self): return self.value
    def all(self): return self.value


class Connection:
    def __init__(self, target=('8.4.13', 3307, 'D:/RiskControlDemo/mysql84/data/'), nonempty=False, extra_grant=False, existing=False):
        self.target = target; self.nonempty = nonempty; self.extra_grant = extra_grant; self.statements = []; self.existing = existing
    def execute(self, sql):
        self.statements.append(sql)
        if sql.startswith('SELECT VERSION()'): return Result(self.target)
        if sql.startswith('SELECT COUNT(*)'): return Result(int(self.nonempty))
        if sql.startswith('SHOW GRANTS'):
            rows = [('GRANT USAGE ON *.* TO role',)]
            if self.extra_grant: rows.append(('GRANT SELECT ON *.* TO role',))
            return Result(rows)
        if sql.startswith('SELECT table_schema'): return Result([('rc_demo_biz','task')] if self.existing else [('rc_demo_biz','alembic_version')])
        return Result(None)


def load_revision(name, connection):
    fake_op = types.SimpleNamespace(get_bind=lambda: connection, execute=connection.execute)
    fake_alembic = types.ModuleType('alembic'); fake_alembic.op = fake_op
    fake_sa = types.ModuleType('sqlalchemy'); fake_sa.text = lambda value: value
    path = Path(__file__).resolve().parents[1] / 'migrations/versions' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, str(path))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {'alembic': fake_alembic, 'sqlalchemy': fake_sa}): spec.loader.exec_module(module)
    return module


class MigrationSafetyTests(unittest.TestCase):
    def test_wrong_targets_stop_before_ddl(self):
        for target in [('8.0.44',3307,'D:/RiskControlDemo/mysql84/data'), ('8.4.13',3306,'D:/RiskControlDemo/mysql84/data'), ('8.4.13',3307,'C:/old/data')]:
            conn = Connection(target)
            with self.assertRaises(RuntimeError): load_revision('0001_core', conn).upgrade()
            self.assertEqual(len(conn.statements), 1)

    def test_down_requires_authorization(self):
        conn = Connection()
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError): load_revision('0001_core', conn).downgrade()
        self.assertFalse(any(sql.startswith('DROP ') for sql in conn.statements))

    def test_nonempty_down_never_drops(self):
        conn = Connection(nonempty=True)
        with patch.dict(os.environ, {'RC_ALLOW_EMPTY_CORE_DOWN':'YES'}):
            with self.assertRaises(RuntimeError): load_revision('0001_core', conn).downgrade()
        self.assertFalse(any(sql.startswith('DROP ') for sql in conn.statements))

    def test_existing_broad_role_stops_before_grants(self):
        conn = Connection(extra_grant=True)
        with self.assertRaises(RuntimeError): load_revision('0002_views', conn).upgrade()
        self.assertTrue(all(sql.startswith('SHOW GRANTS') for sql in conn.statements))

    def test_existing_core_object_refuses_upgrade(self):
        conn = Connection(existing=True)
        with self.assertRaises(RuntimeError): load_revision('0001_core', conn).upgrade()
        self.assertFalse(any(sql.startswith('CREATE ') for sql in conn.statements))

    def test_version_table_only_allows_eleven_creates(self):
        conn = Connection()
        load_revision('0001_core', conn).upgrade()
        self.assertEqual(sum(sql.strip().startswith('CREATE TABLE ') for sql in conn.statements), 11)
        self.assertFalse(any(sql.strip().startswith(('GRANT ','DROP ','INSERT ')) for sql in conn.statements))


if __name__ == '__main__': unittest.main()
