"""V2 fresh-Demo migration. Existing databases are never changed or overwritten."""
from pathlib import Path

DATABASE = 'rc_demo_v2'


def guard(cursor):
    cursor.execute('SELECT VERSION(), @@port, @@datadir')
    version, port, directory = cursor.fetchone()
    if not (version.startswith('8.4.') and port == 3307 and
            directory.replace('\\','/').rstrip('/').lower() == 'd:/riskcontroldemo/mysql84/data'):
        raise RuntimeError('Wrong Demo target')


def upgrade(connection, approved=False):
    if not approved: raise RuntimeError('Separate V2 database and synthetic-write authorization required')
    with connection.cursor() as cursor:
        guard(cursor)
        cursor.execute('SELECT schema_name FROM information_schema.schemata WHERE schema_name=%s',(DATABASE,))
        if cursor.fetchone() is not None: raise RuntimeError('V2 database already exists; stop without changes')
        cursor.execute('CREATE DATABASE `rc_demo_v2` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        cursor.execute('USE `rc_demo_v2`')
        for statement in (Path(__file__).parent/'schema.sql').read_text(encoding='utf-8').split(';'):
            if statement.strip(): cursor.execute(statement.strip())
    connection.commit()


def downgrade_plan(v2_root):
    # Reviewable inverse only. No deletion is executed by this function.
    from v2.models import build_ddl
    metadata, _ = build_ddl(v2_root)
    return ['DROP TABLE `rc_demo_v2`.`' + table.name + '`;' for table in reversed(metadata.sorted_tables)]
