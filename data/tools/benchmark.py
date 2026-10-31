"""Read-only four-path Demo benchmark. Requires running approved MySQL 8.4."""
import argparse
import getpass
import json
import math
import pathlib
import time

EXPECTED_KEYS = ['ix_task_status', 'ix_txn_task_date', 'ix_metric_task_code', 'ix_report_task_version']


def summarize(samples, rows, plans, description, expected_key):
    if len(samples) < 100 or rows <= 0 or not plans:
        raise ValueError('Insufficient/nonempty performance evidence')
    names = [column[0].lower() for column in description]
    # MySQL traditional EXPLAIN has possible_keys AND key; only key is selected.
    key_index = names.index('key'); access_index = names.index('type')
    selected = all(plan[key_index] == expected_key and plan[access_index] not in ('ALL', 'index') for plan in plans)
    p99 = sorted(samples)[math.ceil(len(samples) * .99) - 1]
    return {'observations': len(samples), 'rows': rows, 'p99_ms': p99,
            'plan_key_selected': selected, 'latency_target_met': p99 <= 300,
            'accepted': selected and p99 <= 300}


def main():
    import pymysql
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', required=True)
    parser.add_argument('--iterations', type=int, default=100)
    args = parser.parse_args()
    if args.iterations < 100:
        parser.error('At least 100 observations required')
    failures = 0
    queries = [q.strip().removeprefix('EXPLAIN ') for q in '\n'.join(line for line in (pathlib.Path(__file__).resolve().parents[1] / 'core' / 'queries.sql').read_text().splitlines() if not line.startswith('--')).split(';') if q.strip()]
    if len(queries) != len(EXPECTED_KEYS): raise ValueError('Expected exactly four query paths')
    with pymysql.connect(host='127.0.0.1', port=3307, user=args.user, password=getpass.getpass('Demo read credential: '), read_timeout=30) as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT VERSION(), @@port, @@datadir')
            version, port, directory = cur.fetchone()
            if not version.startswith('8.4.') or port != 3307 or directory.replace('\\', '/').rstrip('/').lower() != 'd:/riskcontroldemo/mysql84/data':
                raise RuntimeError('Target rejected')
            cur.execute("SET SESSION time_zone='+08:00'")
            cur.execute('SELECT COUNT(*) FROM rc_demo_biz.txn')
            if cur.fetchone()[0] < 1500000:
                raise RuntimeError('Full synthetic dataset must be loaded before acceptance')
            for index, query in enumerate(queries):
                cur.execute('EXPLAIN ' + query)
                plans = cur.fetchall()
                description = cur.description
                samples = []
                rows = 0
                for _ in range(args.iterations):
                    start = time.perf_counter()
                    cur.execute(query)
                    rows = len(cur.fetchall())
                    samples.append((time.perf_counter() - start) * 1000)
                result = summarize(samples, rows, plans, description, EXPECTED_KEYS[index])
                result['query'] = index + 1
                failures += not result['accepted']
                print(json.dumps(result))
    if failures: raise SystemExit('Performance acceptance failed paths=' + str(failures))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        raise SystemExit('Benchmark failed; details suppressed to protect credentials. No PASS claimed.')
