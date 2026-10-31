"""Guarded logical backup/restore rehearsal for the isolated Demo only.

Never deletes databases. Restore accepts fresh rc_restore_* schemas only.
"""
import argparse
import base64
import datetime
import decimal
import getpass
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATABASES = ('rc_demo_biz', 'rc_demo_report', 'rc_demo_audit')


def encode(value):
    if isinstance(value, decimal.Decimal): return {'type': 'decimal', 'value': str(value)}
    if isinstance(value, (datetime.datetime, datetime.date)): return {'type': 'datetime', 'value': value.isoformat()}
    if isinstance(value, bytes): return {'type': 'bytes', 'value': base64.b64encode(value).decode('ascii')}
    raise TypeError('Unsupported backup value')


def decode(value):
    if not isinstance(value, dict): return value
    if value['type'] == 'decimal': return decimal.Decimal(value['value'])
    if value['type'] == 'datetime':
        text = value['value']
        return datetime.datetime.fromisoformat(text) if 'T' in text else datetime.date.fromisoformat(text)
    if value['type'] == 'bytes': return base64.b64decode(value['value'])
    raise ValueError('Unknown value encoding')


def row_text(row):
    return json.dumps(list(row), default=encode, ensure_ascii=True, separators=(',', ':')) + '\n'


def file_hash(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1048576), b''): digest.update(chunk)
    return digest.hexdigest()


def guard(connection):
    with connection.cursor() as cur:
        cur.execute('SELECT VERSION(), @@port, @@datadir')
        version, port, directory = cur.fetchone()
        if not version.startswith('8.4.') or port != 3307 or directory.replace('\\', '/').rstrip('/').lower() != 'd:/riskcontroldemo/mysql84/data':
            raise RuntimeError('Target rejected')
        cur.execute("SET SESSION time_zone='+08:00'")


def export(connection, folder, audit_only=False):
    from pymysql.cursors import SSCursor
    from snapshot_format import finish_manifest
    schema = json.loads((ROOT / 'data/core/schema.json').read_text())
    folder.mkdir(parents=True, exist_ok=False)
    manifest = []
    with connection.cursor() as cur:
        cur.execute('SET SESSION TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        cur.execute('START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY')
    for table in schema:
        database = DATABASES[2] if table == 'audit_log' else DATABASES[1] if table in ('metric_value', 'report') else DATABASES[0]
        if audit_only and table != 'audit_log': continue
        with connection.cursor() as cur:
            cur.execute('SHOW CREATE TABLE `' + database + '`.`' + table + '`')
            ddl = cur.fetchone()[1]
        path = folder / (table + '.jsonl')
        count = 0
        with path.open('x', encoding='utf-8', newline='\n') as output:
            with connection.cursor(SSCursor) as cur:
                order = '`id`,`txn_date`' if table == 'txn' else '`id`'
                columns = ','.join('`' + f + '`' for f in schema[table])
                cur.execute('SELECT ' + columns + ' FROM `' + database + '`.`' + table + '` ORDER BY ' + order)
                for row in cur:
                    output.write(row_text(row)); count += 1
        manifest.append({'database': database, 'table': table, 'columns': list(schema[table]), 'ddl': ddl, 'file': path.name, 'rows': count, 'sha256': file_hash(path)})
    connection.rollback()
    finish_manifest(folder, manifest, 'audit' if audit_only else 'full')
    print('BACKUP COMPLETE: tables=' + str(len(manifest)) + '; no row contents printed')


def restore(connection, folder):
    from pymysql.cursors import SSCursor
    from snapshot_format import validate
    # Validate complete scope, all rows and hashes BEFORE the first database creation.
    manifest = validate(folder)
    schema = json.loads((ROOT / 'data/core/schema.json').read_text())
    # Restore only reviewed repository DDL, never executable SQL from a backup manifest.
    reviewed_ddl = {}
    for statement in (ROOT / 'data/core/schema.sql').read_text(encoding='utf-8').split(';'):
        statement = statement.strip()
        match = re.match(r'CREATE TABLE `([a-z_]+)`\.`([a-z_]+)`', statement)
        if match:
            reviewed_ddl[match[2]] = statement.replace('`' + match[1] + '`.', '', 1)
    if set(reviewed_ddl) != set(schema): raise ValueError('Reviewed restore DDL incomplete')
    entries = manifest['tables']
    if manifest.get('format') != 2 or not manifest.get('complete') or not entries:
        raise ValueError('Incomplete backup')
    if len({entry['table'] for entry in entries}) != len(entries): raise ValueError('Duplicate table')
    for entry in entries:
        table = entry['table']
        if table not in schema or entry['columns'] != list(schema[table]): raise ValueError('Unknown schema')
        expected_database = DATABASES[2] if table == 'audit_log' else DATABASES[1] if table in ('metric_value','report') else DATABASES[0]
        if entry['database'] != expected_database or entry['file'] != table + '.jsonl': raise ValueError('Unsafe backup mapping')
        if file_hash(folder / entry['file']) != entry['sha256']: raise ValueError('Backup checksum mismatch')
        # Backup DDL is reference metadata only; only reviewed_ddl is ever executed.
    targets = {db: db.replace('rc_demo_', 'rc_restore_', 1) for db in DATABASES}
    with connection.cursor() as cur:
        for target in targets.values():
            cur.execute('SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name=%s', (target,))
            if cur.fetchone()[0]: raise RuntimeError('Restore schema already exists; never overwrite')
    if input('Type CREATE FRESH RESTORE SCHEMAS to approve: ') != 'CREATE FRESH RESTORE SCHEMAS': raise RuntimeError('Not approved')
    with connection.cursor() as cur:
        for target in targets.values(): cur.execute('CREATE DATABASE `' + target + '` CHARACTER SET utf8mb4')
        for entry in entries:
            target = targets[entry['database']]
            cur.execute('USE `' + target + '`')
            cur.execute(reviewed_ddl[entry['table']])
            sql = 'INSERT INTO `' + entry['table'] + '` (' + ','.join('`'+f+'`' for f in entry['columns']) + ') VALUES (' + ','.join(['%s'] * len(entry['columns'])) + ')'
            batch = []
            with (folder / entry['file']).open(encoding='utf-8') as source:
                for line in source:
                    batch.append(tuple(decode(v) for v in json.loads(line)))
                    if len(batch) == 1000: cur.executemany(sql, batch); batch = []
                if batch: cur.executemany(sql, batch)
    connection.commit()
    for entry in entries:
        digest = hashlib.sha256(); count = 0
        with connection.cursor(SSCursor) as cur:
            order = '`id`,`txn_date`' if entry['table'] == 'txn' else '`id`'
            columns = ','.join('`'+f+'`' for f in entry['columns'])
            cur.execute('SELECT '+columns+' FROM `'+targets[entry['database']]+'`.`'+entry['table']+'` ORDER BY '+order)
            for row in cur: digest.update(row_text(row).encode('utf-8')); count += 1
        if count != entry['rows'] or digest.hexdigest() != entry['sha256']: raise RuntimeError('Restored content mismatch')
    print('RESTORE VERIFIED: row counts and canonical row SHA256 match; original schemas untouched')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['full', 'audit', 'restore', 'verify'])
    parser.add_argument('--user')
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'verify':
        from snapshot_format import validate
        manifest = validate(args.folder)
        print('OFFLINE SNAPSHOT VERIFIED: scope=' + manifest['scope'] + '; tables=' + str(len(manifest['tables'])))
        return
    if not args.user: parser.error('--user required for database modes')
    import pymysql
    folder = args.folder.resolve()
    protected = Path('C:/ProgramData/RiskControlDemoAclBackup').resolve()
    if protected not in folder.parents: raise ValueError('Use the protected external backup tree')
    with pymysql.connect(host='127.0.0.1', port=3307, user=args.user, password=getpass.getpass('Demo credential: '), charset='utf8mb4', read_timeout=60) as connection:
        guard(connection)
        if args.mode == 'restore': restore(connection, folder)
        else: export(connection, folder, args.mode == 'audit')


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('Backup/rehearsal failed; preserve partial state. Sensitive error details suppressed.')
