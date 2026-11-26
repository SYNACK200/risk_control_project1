"""Compile current backend metadata without importing sessions or opening a database.

Run with --write to refresh the reviewed artifacts, or --check to detect drift.
The generated SQL targets an empty database; it is not an existing-DB migration.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / 'data/current'


def artifacts():
    from sqlalchemy.dialects.mysql import dialect
    from sqlalchemy.schema import CreateIndex, CreateTable
    from sqlalchemy import Float
    spec = importlib.util.spec_from_file_location('current_data_models', ROOT / 'backend/db/models.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    metadata = module.Base.metadata
    mysql = dialect()
    tables = {}
    statements = ['-- Empty database only. No CREATE DATABASE / USE / DROP statements.']
    dictionary = ['# 当前后端物理数据字典', '', '由 data/tools/current_schema.py 生成；与历史 v2 Demo 分开。', '']
    for table in metadata.sorted_tables:
        tables[table.name] = {}
        dictionary += ['## ' + table.name, '', '| 字段 | MySQL 类型 | 可空 |', '| --- | --- | --- |']
        for column in table.columns:
            if isinstance(column.type, Float):
                raise ValueError('Floating point storage is not allowed: ' + table.name + '.' + column.name)
            entry = {'type': str(column.type.compile(dialect=mysql)), 'nullable': column.nullable}
            tables[table.name][column.name] = entry
            dictionary.append('| {} | {} | {} |'.format(column.name, entry['type'], entry['nullable']))
        dictionary.append('')
        # Normalize constraint rendering without changing shared backend metadata.
        sql = str(CreateTable(table).compile(dialect=mysql)).strip()
        lines = sql.splitlines()
        positions = [i for i, line in enumerate(lines) if line.lstrip().startswith(('PRIMARY KEY ', 'FOREIGN KEY', 'CONSTRAINT ', 'UNIQUE ', 'CHECK '))]
        constraints = sorted(lines[i].rstrip().rstrip(',') for i in positions)
        for offset, position in enumerate(positions):
            lines[position] = constraints[offset] + (',' if offset < len(positions) - 1 else '')
        statements.append('\n'.join(line.rstrip() for line in lines) + ';')
        for index in sorted(table.indexes, key=lambda item: item.name):
            statements.append(str(CreateIndex(index).compile(dialect=mysql)) + ';')
    snapshot = {'source': 'backend/db/models.py', 'table_count': len(tables),
                'field_count': sum(len(fields) for fields in tables.values()), 'tables': tables}
    return {'schema.sql': '\n\n'.join(statements) + '\n',
            'schema.json': json.dumps(snapshot, ensure_ascii=False, indent=2) + '\n',
            'data_dictionary.md': '\n'.join(dictionary).rstrip() + '\n'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--write', action='store_true')
    mode.add_argument('--check', action='store_true')
    args = parser.parse_args()
    expected = artifacts()
    if args.write:
        OUTPUT.mkdir(parents=True, exist_ok=True)
        for name, content in expected.items():
            (OUTPUT / name).write_text(content, encoding='utf-8')
    else:
        for name, content in expected.items():
            path = OUTPUT / name
            if not path.exists() or path.read_text(encoding='utf-8') != content:
                raise SystemExit('Schema drift: ' + name + '; review changes before --write')
    snapshot = json.loads(expected['schema.json'])
    print('PASS: {} tables, {} fields; no database connection'.format(snapshot['table_count'], snapshot['field_count']))


if __name__ == '__main__':
    main()
