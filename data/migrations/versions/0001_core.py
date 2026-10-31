"""Eleven core tables; only a verified isolated Demo instance."""
from pathlib import Path
from alembic import op
from sqlalchemy import text
import os

revision = '0001_core'
down_revision = None
branch_labels = None
depends_on = None


def guard():
    connection = op.get_bind()
    version, port, directory = connection.execute(text('SELECT VERSION(), @@port, @@datadir')).one()
    if not version.startswith('8.4.') or port != 3307 or directory.replace('\\', '/').rstrip('/').lower() != 'd:/riskcontroldemo/mysql84/data':
        raise RuntimeError('Isolated Demo target mismatch')
    return connection


def upgrade():
    connection = guard()
    # Alembic may have created its own version table; every other object must be absent.
    objects = connection.execute(text("SELECT table_schema,table_name FROM information_schema.tables "
        "WHERE table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')")).all()
    if any(tuple(row) != ('rc_demo_biz', 'alembic_version') for row in objects):
        raise RuntimeError('Existing objects: core migration cannot overwrite or resume partial DDL')
    source = Path(__file__).resolve().parents[2] / 'core' / 'schema.sql'
    statements = '\n'.join(line for line in source.read_text(encoding='utf-8').splitlines() if not line.startswith('--'))
    for statement in statements.split(';'):
        if statement.strip():
            op.execute(text(statement))


def downgrade():
    connection = guard()
    if os.environ.get('RC_ALLOW_EMPTY_CORE_DOWN') != 'YES':
        raise RuntimeError('Explicit empty Demo downgrade authorization required')
    import json
    core = Path(__file__).resolve().parents[2] / 'core'
    names = json.loads((core / 'schema.json').read_text())
    objects = [(('rc_demo_audit' if t == 'audit_log' else 'rc_demo_report' if t in ('metric_value', 'report') else 'rc_demo_biz'), t) for t in names]
    for database, table in objects:
        if connection.execute(text('SELECT COUNT(*) FROM `' + database + '`.`' + table + '`')).scalar():
            raise RuntimeError('Nonempty table: downgrade refused')
    for database, table in reversed(objects):
        op.execute(text('DROP TABLE `' + database + '`.`' + table + '`'))
