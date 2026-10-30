"""Deterministic synthetic transactions; never reads customer data."""
from decimal import Decimal
from datetime import datetime, timedelta
import argparse
import json


def mask_account(value):
    if value is None:
        return None
    if len(value) <= 8:
        return '*' * len(value)
    return value[:4] + '*' * (len(value) - 8) + value[-4:]


def mask_name(value):
    return value[:1] + '*' * max(1, len(value) - 1) if value else value


def transactions(tasks=500, per_task=3000):
    for task in range(1, tasks + 1):
        balance = Decimal('10000.00')
        for index in range(per_task):
            amount = Decimal(index % 97 + 1).quantize(Decimal('0.01'))
            direction = 'in' if index % 2 == 0 else 'out'
            balance += amount if direction == 'in' else -amount
            yield {'id': (task - 1) * per_task + index + 1, 'task_id': task,
                   'account_id': task, 'txn_date': (datetime(2026, 10, 1) + timedelta(minutes=index)).isoformat() + '+08:00',
                   'direction': direction, 'amount': str(amount), 'balance': str(balance),
                   'summary': 'SYNTHETIC DEMO', 'counterparty_name': 'D***', 'page_no': index // 300 + 1}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--tasks', type=int, default=500)
    parser.add_argument('--per-task', type=int, default=3000)
    parser.add_argument('--count-only', action='store_true')
    args = parser.parse_args()
    if args.tasks <= 0 or args.per_task <= 0:
        parser.error('counts must be positive')
    count = 0
    for row in transactions(args.tasks, args.per_task):
        count += 1
        if not args.count_only:
            print(json.dumps(row))
    if args.count_only:
        print('SYNTHETIC rows=' + str(count))
