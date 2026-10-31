"""Only the secure runner may supply an existing verified connection."""
from alembic import context
from sqlalchemy import text

if context.is_offline_mode():
    raise RuntimeError('Offline migration execution is disabled: target must be verified')
connection = context.config.attributes.get('connection')
if connection is None or context.config.attributes.get('approved_revision') != '0001_core':
    raise RuntimeError('Use the secure core runner; direct CLI/head and interactive getpass are disabled')
if context.get_revision_argument() != '0001_core':
    raise RuntimeError('Only the separately approved 0001_core target is allowed by this entry')
version, port, directory = connection.execute(text('SELECT VERSION(), @@port, @@datadir')).one()
if not version.startswith('8.4.') or port != 3307 or directory.replace('\\', '/').rstrip('/').lower() != 'd:/riskcontroldemo/mysql84/data':
    raise RuntimeError('Migration target rejected')
connection.execute(text("SET SESSION time_zone = '+08:00'"))
context.configure(connection=connection, target_metadata=None, version_table_schema='rc_demo_biz')
with context.begin_transaction():
    context.run_migrations()
