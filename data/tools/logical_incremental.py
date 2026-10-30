"""Offline logical row deltas between verified snapshots, NOT binlog/PITR.

Both snapshots must first be exported from the guarded Demo. This scans snapshots,
does not read/write MySQL, and materializes into a new folder only.
"""
import argparse
import hashlib
import json
from pathlib import Path
from logical_backup import decode, encode, row_text
from snapshot_format import validate, rows, row_key, sha256, IMMUTABLE


def line(value):
    return json.dumps(value, default=encode, ensure_ascii=True, separators=(',', ':')) + '\n'


def by_table(manifest): return {entry['table']: entry for entry in manifest['tables']}


def create(base, target, output):
    base = Path(base).resolve(); target = Path(target).resolve(); output = Path(output).resolve()
    old = validate(base); new = validate(target)
    if old['scope'] != new['scope']: raise ValueError('Snapshot scope mismatch')
    old_tables = by_table(old); new_tables = by_table(new)
    if output in (base, target) or base in output.parents or target in output.parents:
        raise ValueError('Output cannot be inside input snapshots')
    output.mkdir(parents=True, exist_ok=False)
    files = []
    for table, entry in old_tables.items():
        left = iter(rows(base, entry)); right = iter(rows(target, new_tables[table]))
        before = next(left, None); after = next(right, None); changes = 0
        path = output / (table + '.delta.jsonl')
        with path.open('x', encoding='utf-8', newline='\n') as stream:
            while before is not None or after is not None:
                bk = row_key(table, before) if before is not None else None
                ak = row_key(table, after) if after is not None else None
                if after is None or (before is not None and bk < ak):
                    if table in IMMUTABLE: raise ValueError('Append-only source row deleted')
                    stream.write(line({'op': 'delete', 'key': bk})); before = next(left, None)
                elif before is None or ak < bk:
                    stream.write(line({'op': 'upsert', 'key': ak, 'row': after})); after = next(right, None)
                else:
                    if row_text(before) == row_text(after):
                        before = next(left, None); after = next(right, None); continue
                    if table in IMMUTABLE: raise ValueError('Append-only source row changed')
                    stream.write(line({'op': 'upsert', 'key': ak, 'row': after}))
                    before = next(left, None); after = next(right, None)
                changes += 1
        files.append({'table': table, 'file': path.name, 'operations': changes, 'sha256': sha256(path)})
    target_text = (target / 'manifest.json').read_text(encoding='utf-8')
    manifest = {'format': 'logical-row-delta-1', 'complete': True,
                'base_manifest_sha256': sha256(base / 'manifest.json'),
                'target_manifest_text': target_text,
                'target_manifest_sha256': hashlib.sha256(target_text.encode('utf-8')).hexdigest(), 'files': files}
    with (output / 'delta.json').open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(manifest, stream, indent=2); stream.write('\n')
    return sum(entry['operations'] for entry in files)


def operations(folder, entry, columns):
    path = Path(folder) / entry['file']
    if path.is_symlink() or path.resolve().parent != Path(folder).resolve() or sha256(path) != entry['sha256']:
        raise ValueError('Delta path/checksum mismatch')
    previous = None; count = 0
    with path.open(encoding='utf-8') as stream:
        for text in stream:
            op = json.loads(text)
            key = tuple(decode(value) for value in op['key'])
            if previous is not None and key <= previous: raise ValueError('Unordered/duplicate operation')
            previous = key
            if op['op'] == 'upsert':
                value = tuple(decode(v) for v in op['row'])
                if len(value) != columns or row_key(entry['table'], value) != key: raise ValueError('Invalid upsert row/key')
            elif op['op'] == 'delete': value = None
            else: raise ValueError('Unknown delta operation')
            count += 1
            yield key, value
    if count != entry['operations']: raise ValueError('Delta operation count mismatch')


def materialize(base, delta, output):
    base = Path(base).resolve(); delta = Path(delta).resolve(); output = Path(output).resolve()
    baseline = validate(base)
    manifest = json.loads((delta / 'delta.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 'logical-row-delta-1' or manifest.get('complete') is not True:
        raise ValueError('Incomplete delta')
    if manifest['base_manifest_sha256'] != sha256(base / 'manifest.json'): raise ValueError('Wrong base')
    target_text = manifest['target_manifest_text']
    if hashlib.sha256(target_text.encode('utf-8')).hexdigest() != manifest['target_manifest_sha256']:
        raise ValueError('Target metadata checksum mismatch')
    target = json.loads(target_text)
    if target.get('format') != 2 or target.get('complete') is not True or target['scope'] != baseline['scope'] or target['schema_sha256'] != baseline['schema_sha256']:
        raise ValueError('Target metadata scope/version mismatch')
    tables = by_table(baseline); target_tables = by_table(target)
    files = manifest['files']
    if len(files) != len(tables) or {entry['table'] for entry in files} != set(tables) or len(target['tables']) != len(tables) or set(target_tables) != set(tables):
        raise ValueError('Incomplete/duplicate delta scope')
    for entry in files:
        table = entry['table']
        if entry['file'] != table + '.delta.jsonl' or target_tables[table]['file'] != table + '.jsonl' or target_tables[table]['columns'] != tables[table]['columns'] or target_tables[table]['database'] != tables[table]['database']:
            raise ValueError('Unsafe delta mapping')
        if type(entry['operations']) is not int or entry['operations'] < 0: raise ValueError('Invalid operation count')
        for _ in operations(delta, entry, len(tables[table]['columns'])): pass
    if output in (base, delta) or base in output.parents or delta in output.parents:
        raise ValueError('Output overlaps input')
    output.mkdir(parents=True, exist_ok=False)
    for entry in files:
        table = entry['table']
        source = iter(rows(base, tables[table])); changes = iter(operations(delta, entry, len(tables[table]['columns'])))
        before = next(source, None); change = next(changes, None)
        with (output / (table + '.jsonl')).open('x', encoding='utf-8', newline='\n') as stream:
            while before is not None or change is not None:
                bk = row_key(table, before) if before is not None else None
                if change is None or (before is not None and bk < change[0]):
                    stream.write(row_text(before)); before = next(source, None)
                elif before is None or change[0] < bk:
                    if change[1] is None: raise ValueError('Delete of absent row')
                    stream.write(row_text(change[1])); change = next(changes, None)
                else:
                    if table in IMMUTABLE: raise ValueError('Append-only baseline changed')
                    if change[1] is not None: stream.write(row_text(change[1]))
                    before = next(source, None); change = next(changes, None)
    # Validate against target hashes before exposing a complete manifest.
    for table, entry in target_tables.items():
        if sha256(output / (table + '.jsonl')) != entry['sha256']: raise ValueError('Materialized target checksum mismatch')
        if sum(1 for _ in rows(output, entry)) != entry['rows']: raise ValueError('Target row count mismatch')
    with (output / 'manifest.json').open('x', encoding='utf-8', newline='\n') as stream: stream.write(target_text)
    return validate(output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['create', 'materialize'])
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True, help='Target snapshot or delta folder')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.mode == 'create': print('OFFLINE DELTA operations=' + str(create(args.base, args.input, args.output)))
    else:
        manifest = materialize(args.base, args.input, args.output)
        print('OFFLINE MATERIALIZED VERIFIED tables=' + str(len(manifest['tables'])))


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('Offline delta failed; preserve partial output; no database operation performed')
