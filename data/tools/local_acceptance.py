"""Interactive local MySQL acceptance. Creates new synthetic-only schemas.

No existing schema is changed. Test schemas are retained for inspection.
"""
import datetime
import decimal
import getpass
import hashlib
import json
from pathlib import Path
import sys
import uuid
from current_schema import artifacts, ROOT
from current_benchmark import measure, QUERIES


def canonical(rows):
    def encode(value):
        if isinstance(value, (datetime.datetime, datetime.date)):
            return value.isoformat()
        if isinstance(value, decimal.Decimal):
            return str(value)
        raise TypeError('Unsupported value')
    return json.dumps(rows, default=encode, sort_keys=True, ensure_ascii=True)


def main():
    from sqlalchemy import create_engine, text, insert, select, inspect
    from sqlalchemy.engine import URL
    artifacts()
    metadata = sys.modules['current_data_models'].Base.metadata
    password = getpass.getpass('Local MySQL84 root password (not logged): ')
    engine = create_engine(URL.create('mysql+pymysql', username='root', password=password,
                                     host='127.0.0.1', port=3307))
    suffix = datetime.datetime.now().strftime('%Y%m%d') + '_' + uuid.uuid4().hex[:8]
    source, restore = 'rc_test_' + suffix, 'rc_restore_' + suffix
    receipt = {'source': source, 'restore': restore, 'synthetic_only': True, 'complete': False}
    try:
        with engine.connect() as conn:
            version, port, datadir = conn.execute(text('SELECT VERSION(),@@port,@@datadir')).one()
            if not version.startswith('8.4.') or port != 3307 or str(datadir).replace('\\', '/').rstrip('/').lower() != 'd:/riskcontroldemo/mysql84/data':
                raise RuntimeError('Unexpected server target')
            for name in (source, restore):
                conn.execute(text('CREATE DATABASE `' + name + '` CHARACTER SET utf8mb4'))
            conn.commit()
        engines = [create_engine(URL.create('mysql+pymysql', username='root', password=password,
                    host='127.0.0.1', port=3307, database=name)) for name in (source, restore)]
        password = None
        try:
            for target in engines:
                metadata.create_all(target)
                assert set(inspect(target).get_table_names()) == set(metadata.tables)
            receipt['tables'] = len(metadata.tables)
            # Exercise reversible nullable-column upgrade on a newly created test table only.
            with engines[0].begin() as conn:
                conn.execute(text('ALTER TABLE txn DROP COLUMN extra'))
                conn.execute(text('ALTER TABLE txn ADD COLUMN extra JSON NULL'))
            receipt['nullable_column_down_up'] = 'PASS'
            with engines[0].begin() as conn:
                conn.execute(insert(metadata.tables['task']).values(id=1, biz_no='SYNTHETIC-ONLY', status='QUEUED'))
                conn.execute(insert(metadata.tables['task']), [dict(id=i, biz_no='SYNTHETIC-'+str(i), status='DONE') for i in range(2, 101)])
                conn.execute(insert(metadata.tables['txn']), [dict(id=(task-1)*191+i, task_id=task, txn_date='2026-11-01',
                    amount=decimal.Decimal('1.00'), balance=decimal.Decimal('100.00'), extra={'synthetic': True}) for task in range(1, 101) for i in range(1, 192)])
                conn.execute(insert(metadata.tables['metric_value']).values(task_id=1, metric_code='A01', metric_name='synthetic', value_num=None))
                conn.execute(insert(metadata.tables['report']).values(task_id=1, version=1, payload={'synthetic': True}))
                # Exercise every implementation table, using generated non-customer values.
                from sqlalchemy import Boolean, DateTime, Integer, Numeric, JSON
                for table in metadata.sorted_tables:
                    if table.name in {'task', 'txn', 'metric_value', 'report'}:
                        continue
                    row = {'id': 1}
                    for column in table.columns:
                        if column.name == 'id' or column.nullable or column.default is not None or column.server_default is not None:
                            continue
                        if isinstance(column.type, Boolean): value = False
                        elif isinstance(column.type, Integer): value = 1
                        elif isinstance(column.type, Numeric): value = decimal.Decimal('1')
                        elif isinstance(column.type, DateTime): value = datetime.datetime(2026, 11, 26)
                        elif isinstance(column.type, JSON): value = {}
                        else: value = 'synthetic'
                        row[column.name] = value
                    if table.name == 'bank_account': row['account_no'] = '0000********0000'
                    conn.execute(insert(table).values(**row))
            for statement in (ROOT / 'data/current/index_review.sql').read_text(encoding='utf-8').splitlines():
                if statement.startswith('CREATE INDEX'):
                    with engines[0].begin() as conn:
                        conn.execute(text(statement))
            # Backup is in memory and includes all current tables, including empty config tables.
            backup = {}
            with engines[0].connect().execution_options(isolation_level='REPEATABLE READ') as conn:
                with conn.begin():
                    for table in metadata.sorted_tables:
                        backup[table.name] = [dict(row) for row in conn.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
            from current_backup import save, restore as restore_snapshot
            from cryptography.fernet import Fernet
            import tempfile
            key = Fernet.generate_key()
            with tempfile.TemporaryDirectory(prefix='rc-synthetic-backup-') as directory:
                snapshot = Path(directory) / 'synthetic.enc'
                with engines[0].connect().execution_options(isolation_level='REPEATABLE READ') as conn:
                    with conn.begin():
                        save(conn, metadata, snapshot, key)
                with engines[1].begin() as conn:
                    restore_snapshot(conn, metadata, snapshot, key)
            key = None
            with engines[1].connect() as conn:
                restored = {table.name: [dict(row) for row in conn.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
                            for table in metadata.sorted_tables}
            if canonical(backup) != canonical(restored):
                raise RuntimeError('Restore mismatch')
            receipt['backup_restore'] = {'status': 'PASS', 'rows': {name: len(rows) for name, rows in backup.items()},
                                        'sha256': hashlib.sha256(canonical(backup).encode()).hexdigest()}
            with engines[0].connect() as conn:
                receipt['performance'] = {name: measure(conn, sql, {'task': 1, 'metric': 'A01'}, 100) for name, sql in QUERIES.items()}
            receipt['complete'] = all(item['accepted'] for item in receipt['performance'].values())
        finally:
            for target in engines:
                target.dispose()
    finally:
        engine.dispose()
        output = ROOT / 'data/evidence' / ('current-local-' + suffix + '.json')
        output.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
        print('Receipt: ' + str(output))
        print('Synthetic schemas retained: ' + source + ', ' + restore)
    if not receipt['complete']:
        raise SystemExit('Acceptance incomplete; inspect receipt')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Acceptance failed; connection details suppressed. Test schemas may remain; no existing schema changed.')
