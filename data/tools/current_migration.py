"""Offline additive MySQL migration planner. Never executes SQL.

Input is a reviewed schema.json snapshot in current_schema's format.
Unknown tables, removed fields and type/nullability changes block the plan.
"""
import argparse
import json
from pathlib import Path
from current_schema import artifacts


def plan(previous):
    from sqlalchemy import MetaData
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateTable, CreateColumn, CreateIndex
    import sys
    target = json.loads(artifacts()['schema.json'])
    metadata = sys.modules['current_data_models'].Base.metadata
    old = previous['tables']
    if set(old) - set(target['tables']):
        raise ValueError('Removed/unknown tables require manual migration review')
    up, down, blockers = [], [], []
    mysql = dialect()
    for table in metadata.sorted_tables:
        if table.name not in old:
            up.append(str(CreateTable(table).compile(dialect=mysql)).strip() + ';')
            up.extend(str(CreateIndex(index).compile(dialect=mysql)) + ';'
                      for index in sorted(table.indexes, key=lambda item: item.name))
            down.insert(0, 'DROP TABLE `' + table.name + '`;')
            continue
        before = old[table.name]
        after = target['tables'][table.name]
        if set(before) - set(after):
            blockers.append(table.name + ': removed columns')
        for name, definition in before.items():
            if name in after and definition != after[name]:
                blockers.append(table.name + '.' + name + ': changed type/nullability')
        for column in table.columns:
            if column.name in before:
                continue
            if not column.nullable or column.primary_key or column.foreign_keys or column.unique or column.index:
                blockers.append(table.name + '.' + column.name + ': needs backfill/constraint/index review')
                continue
            up.append('ALTER TABLE `' + table.name + '` ADD COLUMN ' + str(CreateColumn(column).compile(dialect=mysql)) + ';')
            down.insert(0, 'ALTER TABLE `' + table.name + '` DROP COLUMN `' + column.name + '`;')
    return {'status': 'blocked' if blockers else 'review_required', 'blockers': blockers,
            'up': [] if blockers else up, 'down': [] if blockers else down,
            'warning': 'Down destroys newly added data. Backup and inspect live indexes/constraints before execution. MySQL DDL is not transactional.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = plan(json.loads(args.from_snapshot.read_text(encoding='utf-8')))
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    if result['blockers']:
        raise SystemExit('Blocked: see plan; no executable SQL emitted')
    print('Review plan written; no database accessed')


if __name__ == '__main__':
    main()
