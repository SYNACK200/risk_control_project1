"""Streaming, offline snapshot validation. No credentials or database access."""
import hashlib
import json
from pathlib import Path
import re
import datetime
import sys
from logical_backup import decode, row_text

DATA = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(DATA))
from validation import validate_record, UTC8
SCHEMA = json.loads((DATA / 'core/schema.json').read_text(encoding='utf-8'))
IMMUTABLE = {'report', 'metric_value', 'template', 'rule', 'audit_log'}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''): digest.update(block)
    return digest.hexdigest()


def row_key(table, row):
    if type(row[0]) is not int or row[0] <= 0: raise ValueError('Invalid primary ID')
    return (row[0], row[3]) if table == 'txn' else (row[0],)


def rows(folder, entry):
    """Return validated decoded rows; files must be local direct children, not links."""
    path = Path(folder) / entry['file']
    if path.is_symlink() or path.resolve().parent != Path(folder).resolve():
        raise ValueError('Snapshot path is not a direct local child')
    previous = None
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            raw = json.loads(line)
            if not isinstance(raw, list) or len(raw) != len(entry['columns']): raise ValueError('Row width mismatch')
            row = tuple(decode(value) for value in raw)
            record=dict(zip(entry['columns'],row))
            for field,definition in SCHEMA[entry['table']].items():
                value=record.get(field)
                # DB DATETIME is offset-free; backup sessions are fixed to UTC+8.
                if isinstance(value,datetime.datetime) and value.tzinfo is None:
                    record[field]=value.replace(tzinfo=UTC8)
                if definition.startswith('BOOLEAN') and type(value) is int and value in (0,1):
                    record[field]=bool(value)
            validate_record(entry['table'],record)
            key = row_key(entry['table'], row)
            if previous is not None and key <= previous: raise ValueError('Duplicate or unordered key')
            previous = key
            if row_text(row) != line: raise ValueError('Noncanonical row encoding')
            yield row


def validate(folder):
    folder = Path(folder).resolve()
    schema = json.loads((DATA / 'core/schema.json').read_text(encoding='utf-8'))
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 2 or manifest.get('complete') is not True:
        raise ValueError('Missing complete format-2 snapshot')
    if manifest.get('schema_sha256') != sha256(DATA / 'core/schema.sql'):
        raise ValueError('Reviewed DDL version mismatch')
    required = {'audit_log'} if manifest.get('scope') == 'audit' else set(schema) if manifest.get('scope') == 'full' else set()
    entries = manifest.get('tables', [])
    if not required or len(entries) != len(required) or {e['table'] for e in entries} != required:
        raise ValueError('Incomplete scope or duplicate/unknown tables')
    for entry in entries:
        table = entry['table']
        db = 'rc_demo_audit' if table == 'audit_log' else 'rc_demo_report' if table in ('report', 'metric_value') else 'rc_demo_biz'
        if entry.get('database') != db or entry.get('columns') != list(schema[table]) or entry.get('file') != table + '.jsonl':
            raise ValueError('Unsafe table/column/path mapping')
        if type(entry.get('rows')) is not int or entry['rows'] < 0 or not re.fullmatch('[0-9a-f]{64}', entry.get('sha256', '')):
            raise ValueError('Invalid row count/checksum')
        digest = hashlib.sha256(); count = 0
        for row in rows(folder, entry):
            digest.update(row_text(row).encode('utf-8')); count += 1
        if count != entry['rows'] or digest.hexdigest() != entry['sha256']:
            raise ValueError('Snapshot row count or checksum mismatch')
    return manifest


def finish_manifest(folder, entries, scope):
    manifest = {'format': 2, 'complete': True, 'scope': scope,
                'schema_sha256': sha256(DATA / 'core/schema.sql'), 'tables': entries}
    with (Path(folder) / 'manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    return manifest
