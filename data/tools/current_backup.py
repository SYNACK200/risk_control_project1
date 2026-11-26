"""Authenticated encrypted current-model snapshots. Key is supplied by caller.

Full data snapshots contain credentials: never publish keys or snapshot files.
Restore accepts empty tables only and validates everything before insertion.
"""
import datetime
import decimal
import hashlib
import json
from pathlib import Path
from cryptography.fernet import Fernet
from sqlalchemy import select
from current_schema import artifacts


def encode(value):
    if isinstance(value, decimal.Decimal):
        return {'__decimal__': str(value)}
    if isinstance(value, datetime.datetime):
        return {'__datetime__': value.isoformat()}
    if isinstance(value, datetime.date):
        return {'__date__': value.isoformat()}
    raise TypeError('Unsupported snapshot type')


def decode(value):
    if set(value) == {'__decimal__'}:
        return decimal.Decimal(value['__decimal__'])
    if set(value) == {'__datetime__'}:
        return datetime.datetime.fromisoformat(value['__datetime__'])
    if set(value) == {'__date__'}:
        return datetime.date.fromisoformat(value['__date__'])
    return value


def save(connection, metadata, path, key):
    tables = {table.name: [dict(row) for row in connection.execute(select(table).order_by(*table.primary_key.columns)).mappings()]
              for table in metadata.sorted_tables}
    payload = {'format': 1, 'schema_sha256': hashlib.sha256(artifacts()['schema.json'].encode()).hexdigest(), 'tables': tables}
    encrypted = Fernet(key).encrypt(json.dumps(payload, default=encode, sort_keys=True).encode())
    with Path(path).open('xb') as stream:
        stream.write(encrypted)
    return {name: len(rows) for name, rows in tables.items()}


def restore(connection, metadata, path, key):
    from sqlalchemy import insert
    raw = Fernet(key).decrypt(Path(path).read_bytes())
    payload = json.loads(raw, object_hook=decode)
    if payload.get('format') != 1 or payload.get('schema_sha256') != hashlib.sha256(artifacts()['schema.json'].encode()).hexdigest():
        raise ValueError('Snapshot schema mismatch')
    tables = payload['tables']
    if set(tables) != set(metadata.tables):
        raise ValueError('Incomplete table set')
    for table in metadata.sorted_tables:
        if connection.execute(select(table).limit(1)).first() is not None:
            raise ValueError('Restore requires empty tables')
        rows = tables[table.name]
        if not isinstance(rows, list) or any(not isinstance(row, dict) or set(row) != set(table.columns.keys()) for row in rows):
            raise ValueError('Snapshot column mismatch')
    for table in metadata.sorted_tables:
        if tables[table.name]:
            connection.execute(insert(table), tables[table.name])
    return {name: len(rows) for name, rows in tables.items()}
