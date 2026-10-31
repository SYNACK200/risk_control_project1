"""Streaming acceptance of synthetic fixture cardinality/integrity, no database."""
import argparse
from collections import Counter
from decimal import Decimal
import json
from synthetic import transactions


def audit(records, tasks, per_task):
    counts = Counter(); count = 0; balance = Decimal('10000.00')
    for record in records:
        count += 1
        expected_task = (count - 1) // per_task + 1
        if record['id'] != count or record['task_id'] != expected_task or record['account_id'] != expected_task:
            raise ValueError('Synthetic sequence or logical reference mismatch')
        if counts[expected_task] == 0: balance = Decimal('10000.00')
        counts[expected_task] += 1
        amount = Decimal(record['amount'])
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent != -2 or record['direction'] not in ('in','out'):
            raise ValueError('Synthetic amount/direction mismatch')
        balance += amount if record['direction'] == 'in' else -amount
        if balance != Decimal(record['balance']) or not record['txn_date'].endswith('+08:00') or record['counterparty_name'] != 'D***':
            raise ValueError('Synthetic balance/time/mask mismatch')
    if count != tasks * per_task or set(counts) != set(range(1,tasks+1)) or set(counts.values()) != {per_task}:
        raise ValueError('Synthetic task/row cardinality mismatch')
    return {'synthetic_only': True, 'tasks': tasks, 'per_task': per_task, 'transactions': count,
            'id_reference_balance_amount_time_mask_checks': 'PASS', 'database_loaded': False}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tasks',type=int,default=500)
    parser.add_argument('--per-task',type=int,default=3000)
    args=parser.parse_args()
    if args.tasks <= 0 or args.per_task <= 0: parser.error('Positive counts required')
    print(json.dumps(audit(transactions(args.tasks,args.per_task),args.tasks,args.per_task)))


if __name__ == '__main__': main()
