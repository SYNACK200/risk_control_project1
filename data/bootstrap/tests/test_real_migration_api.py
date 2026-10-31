"""Real installed libraries, MySQL dialect SQL compilation only. No socket or credentials."""
import importlib.util
import io
import pathlib
import types
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
from alembic.runtime.migration import MigrationContext
from alembic.operations import Operations

DATA = pathlib.Path(__file__).resolve().parents[2]
cfg = Config(str(DATA / 'alembic.ini'))
scripts = ScriptDirectory.from_config(cfg)
assert EnvironmentContext(cfg, scripts, destination_rev='0001_core').get_revision_argument() == '0001_core'
assert EnvironmentContext(cfg, scripts, destination_rev='head').get_revision_argument() == '0002_views'
spec = importlib.util.spec_from_file_location('compile_core_only', str(DATA / 'migrations/versions/0001_core.py'))
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)
# The production guard is tested independently; this compiler receives fake metadata only.
revision.guard = lambda: types.SimpleNamespace(execute=lambda sql: types.SimpleNamespace(all=lambda: [('rc_demo_biz','alembic_version')]))
output = io.StringIO()
context = MigrationContext.configure(dialect_name='mysql', opts={'as_sql':True, 'output_buffer':output})
with Operations.context(context):
    revision.upgrade()
sql = output.getvalue()
assert sql.count('CREATE TABLE ') == 11
assert 'PARTITION BY RANGE COLUMNS' in sql and sql.count('CHECK (') == 9
assert not any(word in sql for word in ['GRANT ', 'DROP ', 'CREATE USER', 'CREATE VIEW'])
print('Real Alembic/MySQL dialect: fixed revision and 11 DDL compilations PASS; no connection or SQL execution')
