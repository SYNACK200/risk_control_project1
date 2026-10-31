"""Real env.py execution against fake Alembic/SQLAlchemy; no driver or database."""
import contextlib
import pathlib
import runpy
import sys
import types
import unittest
from unittest.mock import patch

PATH = pathlib.Path(__file__).resolve().parents[2] / 'migrations/env.py'


class Connection:
    def __init__(self, port=3307): self.port, self.queries = port, []
    def execute(self, sql):
        self.queries.append(sql)
        return types.SimpleNamespace(one=lambda: ('8.4.13', self.port, 'D:/RiskControlDemo/mysql84/data/'))


def execute_env(connection=None, target='0001_core', offline=False):
    called = []
    context = types.SimpleNamespace(is_offline_mode=lambda: offline,
        config=types.SimpleNamespace(attributes={'connection': connection, 'approved_revision': '0001_core'}),
        get_revision_argument=lambda: target, configure=lambda **kwargs: called.append('configure'),
        begin_transaction=contextlib.nullcontext, run_migrations=lambda: called.append('run'))
    alembic = types.ModuleType('alembic'); alembic.context = context
    sa = types.ModuleType('sqlalchemy'); sa.text = lambda value: value
    with patch.dict(sys.modules, {'alembic':alembic, 'sqlalchemy':sa}):
        runpy.run_path(str(PATH), run_name='synthetic_env')
    return called


class MigrationEnvTests(unittest.TestCase):
    def test_connection_injection_runs_fixed_revision(self):
        connection = Connection()
        self.assertEqual(execute_env(connection), ['configure','run'])
        self.assertEqual(len(connection.queries), 2)

    def test_no_injected_connection_is_rejected(self):
        with self.assertRaises(RuntimeError): execute_env()

    def test_head_and_views_target_rejected_before_sql(self):
        for target in ['head','0002_views',None]:
            connection = Connection()
            with self.assertRaises(RuntimeError): execute_env(connection,target)
            self.assertEqual(connection.queries, [])

    def test_wrong_port_and_offline_rejected(self):
        with self.assertRaises(RuntimeError): execute_env(Connection(3306))
        with self.assertRaises(RuntimeError): execute_env(Connection(), offline=True)


if __name__ == '__main__': unittest.main()
