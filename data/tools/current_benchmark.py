"""Read-only current-schema query benchmark. Credentials come from MYSQL_* env.

Requires an explicit task with >=191 transactions; never logs connection errors.
"""
import argparse
import json
import math
import os
import time

QUERIES = {
    'txn_date': 'SELECT id,txn_date,amount,balance FROM txn WHERE task_id=:task ORDER BY txn_date,id LIMIT 191',
    'metric_code': 'SELECT metric_code,value_num FROM metric_value WHERE task_id=:task AND metric_code=:metric',
    'report_version': 'SELECT id,version FROM report WHERE task_id=:task ORDER BY version DESC LIMIT 1',
}


def measure(connection, statement, params, iterations):
    from sqlalchemy import text
    plan = [dict(row) for row in connection.execute(text('EXPLAIN ' + statement), params).mappings()]
    samples, count = [], 0
    for _ in range(iterations):
        start = time.perf_counter()
        count = len(connection.execute(text(statement), params).all())
        samples.append((time.perf_counter() - start) * 1000)
    p99 = sorted(samples)[math.ceil(len(samples) * .99) - 1]
    indexed = bool(plan) and all(row.get('key') and row.get('type') not in ('ALL', 'index') for row in plan)
    return {'observations': len(samples), 'rows': count, 'p99_ms': p99,
            'selected_indexes': [row.get('key') for row in plan],
            'accepted': count > 0 and indexed and p99 < 50}


def main():
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-id', required=True, type=int)
    parser.add_argument('--metric-code', default='A01')
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 100 or args.task_id <= 0:
        parser.error('Require >=100 iterations and positive task ID')
    required = ['MYSQL_HOST', 'MYSQL_PORT', 'MYSQL_USER', 'MYSQL_PASSWORD', 'MYSQL_DB']
    if any(not os.environ.get(key) for key in required):
        raise SystemExit('Set all MYSQL_* connection variables; do not put credentials in arguments')
    engine = create_engine(URL.create('mysql+pymysql', username=os.environ['MYSQL_USER'],
        password=os.environ['MYSQL_PASSWORD'], host=os.environ['MYSQL_HOST'],
        port=int(os.environ['MYSQL_PORT']), database=os.environ['MYSQL_DB']), pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text('SET TRANSACTION READ ONLY'))
            conn.execute(text('START TRANSACTION'))
            if conn.execute(text('SELECT COUNT(*) FROM txn WHERE task_id=:task'), {'task': args.task_id}).scalar_one() < 191:
                raise ValueError('Insufficient synthetic workload')
            results = {name: measure(conn, sql, {'task': args.task_id, 'metric': args.metric_code}, args.iterations)
                       for name, sql in QUERIES.items()}
            conn.rollback()
        print(json.dumps(results, ensure_ascii=False, indent=2))
        if not all(result['accepted'] for result in results.values()):
            raise SystemExit('Performance acceptance failed')
    finally:
        engine.dispose()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Benchmark unavailable or failed; no PASS claimed. Connection details suppressed.')
