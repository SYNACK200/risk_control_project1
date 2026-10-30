"""Secure first-core migration: plan/read-only verification or explicit 0001 apply."""
import hashlib
import importlib.util
import json
import os
import re
import sys
import uuid
from pathlib import Path
from authenticate_pipe import dependencies
from provision_core import SafeFailure, emit, request_secret, read_response, expected_dir

DATA = Path(__file__).resolve().parents[1]
DATABASES = ('rc_demo_biz', 'rc_demo_report', 'rc_demo_audit')
TARGET_REVISION = '0001_core'
PHRASE = 'APPLY CORE 0001 ON DEMO 3307'
state = {'writes_started': False}


def database_for(table):
    return DATABASES[2] if table == 'audit_log' else DATABASES[1] if table in ('metric_value', 'report') else DATABASES[0]


def artifacts():
    ddl_bytes = (DATA / 'core/schema.sql').read_bytes()
    ddl = ddl_bytes.decode('utf-8').replace('\r\n', '\n')
    schema = json.loads((DATA / 'core/schema.json').read_text(encoding='utf-8'))
    contract = (DATA.parent / 'contract.md').read_text(encoding='utf-8')
    expected = {t: f.strip().split('、') for t, f in re.findall(r'^\| ([a-z_]+) \| ([^|]+) \|', contract, re.M) if t in schema}
    if len(expected) != len(schema) or len(schema) != 11 or sum(map(len, expected.values())) != 82:
        raise SafeFailure('ARTIFACT_MISMATCH')
    if ddl.count('CREATE TABLE ') != 11 or 'FOREIGN KEY' in ddl:
        raise SafeFailure('ARTIFACT_MISMATCH')
    for table, fields in expected.items():
        block = re.search(r'CREATE TABLE `([^`]+)`\.`' + table + r'` \((.*?)\n\) ENGINE', ddl, re.S)
        if not block or block[1] != database_for(table):
            raise SafeFailure('ARTIFACT_MISMATCH')
        columns = re.findall(r'^  `([a-z0-9_]+)` (.+?)(?:,)?$', block[2], re.M)
        if [c[0] for c in columns] != fields or dict(columns) != schema[table]:
            raise SafeFailure('ARTIFACT_MISMATCH')
    return schema, ddl, hashlib.sha256(ddl_bytes).hexdigest().upper()


def require_da01():
    names = {'admin_structure_and_isolation', 'runtime_metadata', 'rc_demo_app', 'rc_demo_reader', 'rc_demo_audit_writer'}
    for path in sorted((DATA / 'evidence').glob('da01-live-*.json'), reverse=True):
        receipt = json.loads(path.read_text(encoding='utf-8'))
        checks = receipt.get('checks', [])
        if (receipt.get('source') == 'live_mysql' and receipt.get('passed') is True and
                receipt.get('endpoint') == '127.0.0.1:3307' and len(checks) == 5 and
                {c.get('name') for c in checks} == names and all(c.get('ok') is True for c in checks)):
            return path.name
    raise SafeFailure('DA01_EVIDENCE_REQUIRED')


def guard(cur, user):
    cur.execute('SELECT VERSION(), @@port, @@datadir, CURRENT_USER()')
    version, port, directory, matched = cur.fetchone()
    if not (version.startswith('8.4.') and port == 3307 and
            directory.replace('\\', '/').rstrip('/').lower() == expected_dir and matched == user + '@localhost'):
        raise SafeFailure('TARGET_MISMATCH')
    cur.execute("SELECT schema_name,default_character_set_name,default_collation_name FROM information_schema.schemata "
                "WHERE schema_name IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')")
    rows = cur.fetchall()
    if set(rows) != {(d, 'utf8mb4', 'utf8mb4_0900_ai_ci') for d in DATABASES}:
        raise SafeFailure('TARGET_MISMATCH')


def inventory(cur):
    cur.execute("SELECT table_schema,table_name,table_type FROM information_schema.tables "
                "WHERE table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit') ORDER BY table_schema,table_name")
    objects = list(cur.fetchall())
    for source, schema_col in [('triggers', 'trigger_schema'), ('routines', 'routine_schema'), ('events', 'event_schema')]:
        cur.execute('SELECT COUNT(*) FROM information_schema.' + source + ' WHERE ' + schema_col +
                    " IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')")
        if cur.fetchone()[0]:
            raise SafeFailure('UNEXPECTED_OBJECTS')
    return objects


def classify(objects, schema):
    if not objects:
        return 'fresh'
    expected = {(database_for(t), t, 'BASE TABLE') for t in schema}
    expected.add(('rc_demo_biz', 'alembic_version', 'BASE TABLE'))
    if len(objects) == len(expected) and set(objects) == expected:
        return 'existing'
    raise SafeFailure('PARTIAL_OR_UNKNOWN_OBJECTS')


def normalized_check(value):
    value = re.sub(r'_[a-zA-Z0-9]+(?=\')', '', value)
    return re.sub(r'[\s`()]+', '', value).lower()


def migration_dependencies_ready():
    try:
        from importlib.metadata import version
        for name, lower, upper in [('alembic',(1,13,0),(2,0,0)), ('SQLAlchemy',(2,0,0),(2,1,0))]:
            value = version(name)
            if not re.fullmatch(r'\d+\.\d+\.\d+', value) or not lower <= tuple(map(int, value.split('.'))) < upper:
                return False
        return all(importlib.util.find_spec(n) is not None for n in ('alembic','sqlalchemy'))
    except Exception:
        return False


def verify(cur, schema, ddl):
    sys.path.insert(0, str(DATA / 'tools'))
    from verify_live import column_matches
    cur.execute("SELECT table_schema,table_name,engine,table_collation,table_type FROM information_schema.tables "
                "WHERE table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit') "
                "AND NOT (table_schema='rc_demo_biz' AND table_name='alembic_version')")
    table_rows = cur.fetchall()
    wanted_tables = {(database_for(t),t,'InnoDB','utf8mb4_0900_ai_ci','BASE TABLE') for t in schema}
    tables_ok = len(table_rows) == 11 and set(table_rows) == wanted_tables
    fields_ok = primary_ok = index_ok = True
    field_count = 0
    for table, definitions in schema.items():
        db = database_for(table)
        cur.execute('SELECT column_name,column_type,is_nullable,extra,character_set_name,collation_name,column_default '
                    'FROM information_schema.columns WHERE table_schema=%s AND table_name=%s ORDER BY ordinal_position', (db, table))
        columns = cur.fetchall()
        field_count += len(columns)
        fields_ok &= ([c[0] for c in columns] == list(definitions) and
                      all(c[0] in definitions and column_matches(definitions[c[0]], c) for c in columns))
        cur.execute('SELECT index_name,column_name,non_unique FROM information_schema.statistics '
                    'WHERE table_schema=%s AND table_name=%s ORDER BY index_name,seq_in_index', (db, table))
        indexes = {}
        for name, col, non_unique in cur.fetchall():
            indexes.setdefault(name, []).append((col, int(non_unique)))
        pk = ['id', 'txn_date'] if table == 'txn' else ['id']
        primary_ok &= indexes.get('PRIMARY') == [(c, 0) for c in pk]
        wanted = {'PRIMARY': [(c, 0) for c in pk]}
        extras = {'file_obj': ('uq_file_sha256', ['sha256'], 0), 'task': ('ix_task_status', ['status', 'id'], 1),
                  'txn': ('ix_txn_task_date', ['task_id', 'txn_date', 'id'], 1),
                  'metric_value': ('ix_metric_task_code', ['task_id', 'metric_code'], 1),
                  'report': ('ix_report_task_version', ['task_id', 'version'], 1)}
        if table in extras:
            name, cols, flag = extras[table]
            wanted[name] = [(c, flag) for c in cols]
        if table == 'task': wanted['uq_task_biz_no'] = [('biz_no', 0)]
        index_ok &= indexes == wanted
    cur.execute("SELECT tc.table_name,cc.check_clause,tc.enforced FROM information_schema.table_constraints AS tc "
                "JOIN information_schema.check_constraints AS cc ON cc.constraint_schema=tc.constraint_schema "
                "AND cc.constraint_name=tc.constraint_name WHERE tc.constraint_type='CHECK' "
                "AND tc.table_schema IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')")
    check_rows = cur.fetchall()
    actual_checks = [(t, normalized_check(c)) for t, c, enforced in check_rows if enforced == 'YES']
    wanted_checks = []
    for table in schema:
        block = re.search(r'CREATE TABLE `[^`]+`\.`' + table + r'` \((.*?)\n\) ENGINE', ddl, re.S)[1]
        wanted_checks += [(table, normalized_check(c)) for c in re.findall(r'^  CHECK \((.*)\),?$', block, re.M)]
    checks_ok = all(row[2] == 'YES' for row in check_rows) and sorted(actual_checks) == sorted(wanted_checks)
    cur.execute("SELECT COUNT(*) FROM information_schema.referential_constraints WHERE constraint_schema "
                "IN ('rc_demo_biz','rc_demo_report','rc_demo_audit')")
    no_fk = cur.fetchone()[0] == 0
    cur.execute("SELECT partition_name,partition_method,partition_expression,partition_description "
                "FROM information_schema.partitions WHERE table_schema='rc_demo_biz' AND table_name='txn' "
                "ORDER BY partition_ordinal_position")
    partitions = list(cur.fetchall())
    expected_parts = [('p_before', '2026-10-01'), ('p202610', '2026-11-01'), ('p202611', '2026-12-01'),
                      ('p202612', '2027-01-01'), ('p_future', 'MAXVALUE')]
    parts_ok = (len(partitions) == 5 and all(
        name == expected[0] and method == 'RANGE COLUMNS' and normalized_check(expr) == 'txn_date' and
        description.strip("'").split(' ')[0].upper() == expected[1]
        for (name, method, expr, description), expected in zip(partitions, expected_parts)))
    cur.execute('SHOW CREATE TABLE rc_demo_biz.txn')
    create_row = cur.fetchone()
    show_partitioned = (len(create_row) >= 2 and 'PARTITION BY RANGE COLUMNS' in create_row[1].upper())
    cur.execute('SELECT version_num FROM rc_demo_biz.alembic_version')
    revision_ok = cur.fetchall() == ((TARGET_REVISION,),)
    matched_indexes = 0
    query_source = '\n'.join(line for line in (DATA / 'core/queries.sql').read_text().splitlines() if not line.lstrip().startswith('--'))
    queries = [s.strip() for s in query_source.split(';') if s.strip()]
    if len(queries) != 4 or not all(s.startswith('EXPLAIN SELECT ') for s in queries):
        raise SafeFailure('ARTIFACT_MISMATCH')
    for sql, expected_index in zip(queries,
            ['ix_task_status', 'ix_txn_task_date', 'ix_metric_task_code', 'ix_report_task_version']):
        cur.execute(sql)
        names = [c[0].lower() for c in cur.description]
        selected = [dict(zip(names, row)).get('key') for row in cur.fetchall()]
        matched_indexes += expected_index in selected
    return {'table_count': len(table_rows), 'tables_ok': tables_ok, 'field_count': field_count, 'fields_ok': bool(fields_ok),
            'primary_keys_ok': bool(primary_ok), 'indexes_ok': bool(index_ok), 'constraints_ok': checks_ok,
            'partitions_ok': parts_ok and show_partitioned, 'show_create_partitioned': show_partitioned,
            'foreign_keys_absent': no_fk, 'revision_ok': revision_ok,
            'explain_matches': matched_indexes, 'boundary_dml_tested': False, 'downgrade_tested': False}


def migration_upgrade(raw):
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine
    from sqlalchemy.pool import NullPool
    engine = create_engine('mysql+pymysql://', creator=lambda: raw, poolclass=NullPool, hide_parameters=True)
    try:
        with engine.connect() as connection:
            cfg = Config(str(DATA / 'alembic.ini'))
            cfg.attributes.update(connection=connection, approved_revision=TARGET_REVISION)
            command.upgrade(cfg, TARGET_REVISION)  # Never head/0002, never downgrade.
            connection.commit()
            with raw.cursor() as cur:
                schema, ddl, _ = artifacts()
                return verify(cur, schema, ddl)
    finally:
        engine.dispose()


def run(mode, user, apply=False, expected_hash=None):
    state['writes_started'] = False
    schema, ddl, digest = artifacts()
    require_da01()
    if mode not in ('CorePlan', 'CoreApply', 'CoreVerify') or (mode == 'CoreApply') != bool(apply):
        raise SafeFailure('APPLY_REQUIRED')
    if not re.fullmatch('[A-Za-z0-9_]+', user):
        raise SafeFailure('MODE_REJECTED')
    ready = migration_dependencies_ready()
    if apply and (not ready or expected_hash != digest):
        raise SafeFailure('MIGRATION_DEPENDENCIES_OR_HASH')
    driver = dependencies()
    secret = request_secret(user, 'login')
    raw = None
    try:
        raw = driver.connect(host='127.0.0.1', port=3307, user=user, password=secret.encode('utf-8'),
                             database='rc_demo_biz', charset='utf8mb4', autocommit=False,
                             local_infile=False, connect_timeout=5, read_timeout=20, write_timeout=20)
        secret = None
        with raw.cursor() as cur:
            guard(cur, user)
            objects = inventory(cur)
            phase = classify(objects, schema)
            if apply and phase != 'fresh':
                raise SafeFailure('EXISTING_OBJECTS_STOP')
            report = {'phase': phase, 'schema_sha256': digest, 'migration_dependencies_ready': ready,
                      'table_count': 0, 'field_count': 0, 'baseline_file': None}
            if phase == 'existing':
                report.update(verify(cur, schema, ddl))
                required = ['tables_ok','fields_ok','primary_keys_ok','indexes_ok','constraints_ok','partitions_ok','foreign_keys_absent','revision_ok']
                if not all(report[k] for k in required): raise SafeFailure('SCHEMA_MISMATCH')
                report['phase'] = 'already_applied'
            elif mode == 'CoreVerify':
                raise SafeFailure('SCHEMA_NOT_CREATED')
            elif apply:
                emit({'type': 'confirm'})
                if read_response(sys.stdin.buffer) != PHRASE: raise SafeFailure('CONFIRMATION_REQUIRED')
                # Empty-instance metadata snapshot. No business rows/passwords are read or saved.
                name = 'core-before-' + uuid.uuid4().hex + '.json'
                baseline = {'objects': objects, 'schemas': list(DATABASES), 'schema_sha256': digest,
                            'account_changes': False, 'target_revision': TARGET_REVISION}
                baseline['code_hashes'] = {name: hashlib.sha256((DATA / name).read_bytes()).hexdigest().upper()
                    for name in ('core/schema.sql','core/schema.json','migrations/env.py','migrations/versions/0001_core.py')}
                with (DATA / 'evidence' / name).open('x', encoding='utf-8') as f:
                    json.dump(baseline, f, ensure_ascii=True)
                    f.flush()
                    os.fsync(f.fileno())
                cur.close()
                raw.commit()
                state['writes_started'] = True
                report.update(migration_upgrade(raw))
                report['baseline_file'] = name
                report['phase'] = 'applied'
                required = ['tables_ok','fields_ok','primary_keys_ok','indexes_ok','constraints_ok','partitions_ok','foreign_keys_absent','revision_ok']
                if not all(report[k] for k in required): raise SafeFailure('SCHEMA_MISMATCH')
        return {'type': 'result', 'ok': True, 'mode': mode, 'core_report': report}
    finally:
        secret = None
        if raw is not None and not getattr(raw, '_closed', False):
            raw.close()


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    try:
        user = sys.argv[2]
        extra = sys.argv[3:]
        apply = '--apply' in extra
        expected = extra[extra.index('--ddl-sha256') + 1] if '--ddl-sha256' in extra else None
        emit(run(mode, user, apply, expected))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        allowed = {'ARTIFACT_MISMATCH','DA01_EVIDENCE_REQUIRED','TARGET_MISMATCH','UNEXPECTED_OBJECTS',
                   'PARTIAL_OR_UNKNOWN_OBJECTS','APPLY_REQUIRED','MODE_REJECTED','MIGRATION_DEPENDENCIES_OR_HASH',
                   'SCHEMA_MISMATCH','SCHEMA_NOT_CREATED','EXISTING_OBJECTS_STOP','CONFIRMATION_REQUIRED','EMPTY_INPUT','CONTROL_CHARACTER','INPUT_REJECTED','INPUT_EOF'}
        category = error.args[0] if isinstance(error, SafeFailure) and error.args and error.args[0] in allowed else 'CORE_EXECUTION_FAILED'
        code = error.args[0] if error.args and type(error.args[0]) is int else None
        emit({'type': 'result', 'ok': False, 'mode': mode, 'category': category, 'code': code,
              'stage': 'core', 'writes_started': state['writes_started']})
        return 1


if __name__ == '__main__':
    sys.exit(main())
