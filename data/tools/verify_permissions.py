"""Runtime privilege checks using zero-row DML; never inserts/updates/deletes rows.

Still requires explicit runtime validation authorization. Exact 1142/1143 denial only.
"""
import argparse
import getpass
import json
from pathlib import Path
from logical_backup import guard, DATABASES


def main():
    import pymysql
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', required=True)
    parser.add_argument('--role', required=True, choices=['reader', 'app', 'audit_writer'])
    parser.add_argument('--confirm-zero-row-dml', action='store_true')
    args = parser.parse_args()
    if not args.confirm_zero_row_dml: parser.error('Explicit zero-row DML approval required')
    schema = json.loads((Path(__file__).resolve().parents[1] / 'core/schema.json').read_text())
    checks = 0
    with pymysql.connect(host='127.0.0.1', port=3307, user=args.user, password=getpass.getpass('Runtime credential: ')) as conn:
        guard(conn)
        with conn.cursor() as cur:
            def check(sql, allowed):
                nonlocal checks
                try:
                    cur.execute(sql)
                    cur.fetchall()
                except pymysql.MySQLError as error:
                    if allowed or error.args[0] not in (1142, 1143): raise RuntimeError('Unexpected privilege result') from None
                else:
                    if not allowed: raise RuntimeError('Forbidden capability was granted')
                checks += 1
            if args.role == 'reader':
                for table in schema:
                    database = DATABASES[2] if table == 'audit_log' else DATABASES[1] if table in ('report','metric_value') else DATABASES[0]
                    target = '`' + database + '`.`' + table + '`'
                    if table != 'audit_log': check('SELECT * FROM `' + database + '`.`v_' + table + '` LIMIT 0', True)
                    check('SELECT * FROM ' + target + ' LIMIT 0', False)
                    check('INSERT INTO ' + target + ' (`id`) SELECT 1 WHERE 0', False)
            elif args.role == 'audit_writer':
                check('INSERT INTO rc_demo_audit.audit_log (id) SELECT 1 WHERE 0', True)
                check('SELECT * FROM rc_demo_audit.audit_log LIMIT 0', False)
                check('UPDATE rc_demo_audit.audit_log SET action=action WHERE 0', False)
                check('DELETE FROM rc_demo_audit.audit_log WHERE 0', False)
                check('SELECT * FROM rc_demo_biz.task LIMIT 0', False)
            else:
                for table in ('report', 'metric_value', 'template', 'rule'):
                    database = DATABASES[1] if table in ('report','metric_value') else DATABASES[0]
                    target = '`' + database + '`.`' + table + '`'
                    check('SELECT * FROM ' + target + ' LIMIT 0', True)
                    check('UPDATE ' + target + ' SET id=id WHERE 0', False)
                    check('DELETE FROM ' + target + ' WHERE 0', False)
                check('SELECT * FROM rc_demo_audit.audit_log LIMIT 0', False)
                check('INSERT INTO rc_demo_audit.audit_log (id) SELECT 1 WHERE 0', False)
        conn.rollback()
    print('Privilege checks passed=' + str(checks) + '; zero row mutations; no customer rows read')


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('Privilege verification failed; no PASS. Sensitive details suppressed.')
