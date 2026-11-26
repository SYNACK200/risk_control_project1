"""JSON retention dry-run CLI. Input contains IDs/timestamps only, no originals."""
import argparse
import datetime
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retention import retention_preview


def preview(records, now, policy):
    output = []
    for record in records:
        if set(record) != {'kind', 'id', 'created_at'}:
            raise ValueError('Only kind/id/created_at metadata accepted')
        kind = record['kind']
        days = policy.get(kind)
        if kind == 'audit':
            days = 1  # Underlying policy always retains audit; no deletion option.
        if days is None:
            raise ValueError('Explicit retention days required per non-audit kind')
        parsed = dict(record, created_at=datetime.datetime.fromisoformat(record['created_at']))
        output.extend(retention_preview([parsed], now, days))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--policy', type=Path, required=True)
    parser.add_argument('--now', required=True, help='ISO timestamp including UTC offset')
    args = parser.parse_args()
    result = preview(json.loads(args.input.read_text(encoding='utf-8')),
                     datetime.datetime.fromisoformat(args.now),
                     json.loads(args.policy.read_text(encoding='utf-8')))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
