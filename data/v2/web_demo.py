"""Existing V2 Demo: read-only verification or API serving; never initializes SQL."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
import uuid

DATA = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(DATA), str(DATA/'bootstrap')]
from authenticate_pipe import dependencies
from provision_core import read_response
from v2.deploy import connect
from v2.migration import guard


QUERIES = {
    'task': ('SELECT id FROM task WHERE id=%s', (1,)),
    'transactions': ('SELECT id FROM txn WHERE task_id=%s ORDER BY txn_date', (1,)),
    'metrics': ('SELECT id FROM metric_value WHERE task_id=%s AND metric_code=%s', (1, 'M01')),
    'report': ('SELECT id FROM report WHERE task_id=%s', (1,)),
}


def verify(connection):
    """Only SELECT / SHOW / EXPLAIN, no trial DML even when rolled back."""
    with connection.cursor() as cursor:
        guard(cursor)
        cursor.execute('SELECT CURRENT_USER(), DATABASE()')
        if cursor.fetchone() != ('rc_demo_app@localhost', 'rc_demo_v2'):
            raise RuntimeError('Wrong runtime identity')
        cursor.execute('SHOW TABLES')
        # SHOW TABLES is privilege-filtered: staff_user deliberately unavailable.
        visible = {row[0] for row in cursor.fetchall()}
        expected = {'file_obj','task','task_file','bank_account','txn','metric_value','report','template','rule','audit_log'}
        if visible != expected:
            raise RuntimeError('Unexpected visible objects')
        cursor.execute('SHOW CREATE TABLE txn')
        partitioned = 'PARTITION BY RANGE' in cursor.fetchone()[1]
        if not partitioned:
            raise RuntimeError('Missing monthly partitions')
        plans = {}
        for label, (sql, parameters) in QUERIES.items():
            cursor.execute('EXPLAIN '+sql, parameters)
            names = [column[0] for column in cursor.description]
            rows = [dict(zip(names, row)) for row in cursor.fetchall()]
            plans[label] = [{'key': row.get('key'), 'type': row.get('type')} for row in rows]
        cursor.execute('SELECT counterparty_name FROM txn WHERE task_id=%s', (1,))
        rows = cursor.fetchall()
        if len(rows) != 3 or any(name and '*' not in name for (name,) in rows):
            raise RuntimeError('Synthetic stored privacy mismatch')
    return {'visible_objects': len(visible), 'partitioned': partitioned,
            'stored_privacy': True, 'explain': plans,
            'four_index_paths_pass': all(any(row['key'] for row in plan) for plan in plans.values()),
            'reader_permissions_tested': False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['Verify', 'Serve'], required=True)
    parser.add_argument('--v2-root', required=True)
    args = parser.parse_args()
    secret = None
    engine = None
    try:
        driver = dependencies()
        secret = read_response(sys.stdin.buffer)
        if not secret or any(ord(c)<32 or 127<=ord(c)<=159 for c in secret):
            raise ValueError('Rejected credential')
        with connect(driver, 'rc_demo_app', secret, 'rc_demo_v2') as connection:
            report = verify(connection)
        path = DATA/'evidence'/('v2-readonly-'+uuid.uuid4().hex+'.json')
        with path.open('x', encoding='utf-8') as file:
            json.dump({'source':'live_mysql','database':'rc_demo_v2','checks':report},file,indent=2)
        print('PASS: existing V2 database read-only verification', flush=True)
        print('Evidence: '+str(path), flush=True)
        if args.mode == 'Verify':
            return 0
        from sqlalchemy import create_engine
        from sqlalchemy.pool import NullPool
        from v2.runtime import load_app
        engine = create_engine('mysql+pymysql://',creator=lambda:connect(driver,'rc_demo_app',secret,'rc_demo_v2'),
                               poolclass=NullPool,hide_parameters=True)
        # Never expose team/driver exception text (may contain SQL parameters).
        with contextlib.redirect_stdout(sys.stderr):
            app = load_app(args.v2_root,engine)
            import importlib
            importlib.import_module('routers.tasks').STORAGE = DATA/'inputs/demo_v2_uploads'
        import uvicorn
        print('API ready to start: http://127.0.0.1:8000 (Ctrl+C stops)',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=8000,access_log=False,log_level='critical')
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        original = getattr(error,'orig',error)
        code = original.args[0] if original.args and type(original.args[0]) is int else 'suppressed'
        print('STOP: V2 existing-database verification/serving; code='+str(code),flush=True)
        return 1
    finally:
        if engine is not None:
            engine.dispose()
        secret = None


if __name__ == '__main__':
    sys.exit(main())
