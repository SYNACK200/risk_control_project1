"""Explicit view grants; no runtime execution yet."""
from pathlib import Path
from alembic import op
from sqlalchemy import text

revision = '0002_views'
down_revision = '0001_core'
branch_labels = None
depends_on = None


def statements():
    source = (Path(__file__).resolve().parents[2] / 'core/views_grants.sql').read_text()
    source = '\n'.join(line for line in source.splitlines() if not line.startswith('--'))
    return [s.strip() for s in source.split(';') if s.strip()]


def upgrade():
    # env.py already checks version, port and datadir before every migration.
    conn = op.get_bind()
    for role in ('rc_role_app', 'rc_role_reader', 'rc_role_audit_writer'):
        grants = conn.execute(text("SHOW GRANTS FOR '" + role + "'@'localhost'")).all()
        if len(grants) != 1 or not grants[0][0].startswith('GRANT USAGE ON *.* TO '):
            raise RuntimeError('Expected empty bootstrap roles; never widen or overwrite existing grants')
    for statement in statements(): conn.execute(text(statement))


def downgrade():
    conn = op.get_bind()
    for statement in reversed(statements()):
        if statement.startswith('GRANT '):
            conn.execute(text(statement.replace('GRANT ', 'REVOKE ', 1).replace(' TO ', ' FROM ', 1)))
        elif statement.startswith('CREATE SQL SECURITY DEFINER VIEW '):
            name = statement.split(' VIEW ', 1)[1].split(' AS SELECT ', 1)[0]
            conn.execute(text('DROP VIEW ' + name))
