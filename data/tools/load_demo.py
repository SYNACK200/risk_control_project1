"""Explicitly approved synthetic-only loader; refuses any existing core rows."""
import argparse
import datetime
import decimal
import getpass
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from validation import validate_record
from logical_backup import guard, DATABASES
from synthetic import transactions


def main():
    import pymysql
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply: parser.error('--apply required; writes synthetic rows')
    schema = json.loads((Path(__file__).resolve().parents[1] / 'core/schema.json').read_text())
    with pymysql.connect(host='127.0.0.1', port=3307, user=args.user, password=getpass.getpass('Synthetic load credential: '), charset='utf8mb4', write_timeout=60) as conn:
        guard(conn)
        with conn.cursor() as cur:
            for table in schema:
                db = DATABASES[2] if table == 'audit_log' else DATABASES[1] if table in ('report', 'metric_value') else DATABASES[0]
                cur.execute('SELECT COUNT(*) FROM `' + db + '`.`' + table + '`')
                if cur.fetchone()[0]: raise RuntimeError('Nonempty core; no append/overwrite permitted')
            if input('Type LOAD SYNTHETIC DEMO to approve: ') != 'LOAD SYNTHETIC DEMO': raise RuntimeError('Not approved')
            for task in range(1, 501):
                cur.execute("INSERT INTO rc_demo_biz.task (id,biz_no,task_type,status) VALUES (%s,%s,'credit','DONE')", (task, 'SYNTHETIC-' + str(task)))
                cur.execute('INSERT INTO rc_demo_biz.bank_account (id,task_id,account_no,opening_balance) VALUES (%s,%s,%s,%s)', (task, task, '0000********0000', decimal.Decimal('10000.00')))
                cur.execute("INSERT INTO rc_demo_report.metric_value (task_id,metric_code,metric_name,value_num,unit,caliber_version) VALUES (%s,'DEMO','SYNTHETIC ROW COUNT',3000,'rows',1)", (task,))
                cur.execute('INSERT INTO rc_demo_report.report (task_id,version) VALUES (%s,1)', (task,))
            fields = list(schema['txn'])
            sql = 'INSERT INTO rc_demo_biz.txn (' + ','.join('`'+f+'`' for f in fields) + ') VALUES (' + ','.join(['%s'] * len(fields)) + ')'
            batch = []
            for record in transactions():
                record = validate_record('txn', record)
                batch.append(tuple(record[f] for f in fields))
                if len(batch) == 1000: cur.executemany(sql, batch); batch = []
            if batch: cur.executemany(sql, batch)
            cur.execute('SELECT COUNT(*),COUNT(DISTINCT task_id) FROM rc_demo_biz.txn')
            if cur.fetchone() != (1500000, 500): raise RuntimeError('Count mismatch; rollback')
        conn.commit()
    print('Synthetic load committed: tasks=500 transactions=1500000; no customer data')


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('Synthetic load failed; inspect state privately, never delete or retry blindly')
