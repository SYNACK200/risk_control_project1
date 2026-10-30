"""Independent offline contract/DDL/physical dictionary coverage check."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
core = ROOT / 'data' / 'core'
ddl = (core / 'schema.sql').read_text(encoding='utf-8')
assert len(re.findall(r'^CREATE TABLE ',ddl,re.M)) == 11, 'Unexpected core table count'
schema = json.loads((core / 'schema.json').read_text(encoding='utf-8'))
contract = (ROOT / 'contract.md').read_text(encoding='utf-8')
expected = {t: f.strip().split(chr(12289)) for t, f in re.findall(r'^\| ([a-z_]+) \| ([^|]+) \|', contract, re.M) if t in schema}
assert len(expected) == len(schema) == 11
assert sum(map(len, expected.values())) == 82
for table, fields in expected.items():
    block = re.search(r'CREATE TABLE `[^`]+`\.`' + table + r'` \((.*?)\n\) ENGINE', ddl, re.S).group(1)
    columns = re.findall(r'^  `([a-z0-9_]+)` (.+?)(?:,)?$', block, re.M)
    actual = [f for f, _ in columns]
    assert len(actual) == len(set(actual)) and actual == fields, table
    assert dict(columns) == schema[table], table
    print(table + ': contract=' + str(len(fields)) + ' DDL=' + str(len(actual)) + ' missing=0 extra=0 duplicate=0')
assert 'PARTITION BY RANGE COLUMNS (`txn_date`)' in ddl
assert 'PRIMARY KEY (`id`, `txn_date`)' in ddl
assert 'CHECK (`amount` > 0)' in ddl
assert 'FOREIGN KEY' not in ddl
dictionary = (core / 'physical_dictionary.md').read_text(encoding='utf-8')
for table, fields in expected.items():
    block = re.search(r'^## ' + table + r'\n(.*?)(?=^## |\Z)', dictionary, re.M | re.S).group(1)
    entries = re.findall(r'^\| ([a-z0-9_]+) \| (.+) \|$', block, re.M)
    assert [field for field, definition in entries] == fields
    assert dict(entries) == schema[table], 'Dictionary type mismatch: ' + table
print('OFFLINE PASS; MySQL execution, migrations, grants and performance NOT verified')
