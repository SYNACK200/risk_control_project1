import copy
import datetime
import decimal
import json
from pathlib import Path
import tempfile
import unittest
from logical_backup import row_text
from logical_incremental import create, materialize
from snapshot_format import validate, finish_manifest, sha256, DATA


SCHEMA = json.loads((DATA / 'core/schema.json').read_text(encoding='utf-8'))


def task(identifier, status):
    values = {field: None for field in SCHEMA['task']}
    values.update(id=identifier, biz_no='SYNTHETIC-' + str(identifier), status=status)
    return list(values.values())


def snapshot(folder, data=None, scope='full'):
    folder.mkdir()
    entries = []
    for table in (['audit_log'] if scope == 'audit' else SCHEMA):
        records = (data or {}).get(table, [])
        path = folder / (table + '.jsonl')
        path.write_bytes(''.join(row_text(row) for row in records).encode('utf-8'))
        db = 'rc_demo_audit' if table == 'audit_log' else 'rc_demo_report' if table in ('report','metric_value') else 'rc_demo_biz'
        entries.append({'table': table, 'database': db, 'columns': list(SCHEMA[table]),
                        'file': path.name, 'rows': len(records), 'sha256': sha256(path), 'ddl': 'REFERENCE ONLY'})
    return finish_manifest(folder, entries, scope)


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()

    def test_full_snapshot_and_utc8_decimal_rows(self):
        row = [1,1,1,datetime.datetime(2026,10,1),'in',decimal.Decimal('1.20'),decimal.Decimal('10001.20'),'SYNTHETIC','D***',1]
        snapshot(self.root/'base', {'txn':[row]})
        self.assertEqual(len(validate(self.root/'base')['tables']),11)

    def test_insert_update_delete_delta_and_second_delta(self):
        snapshot(self.root/'base', {'task':[task(1,'PENDING'),task(2,'PENDING')]})
        snapshot(self.root/'target', {'task':[task(1,'DONE'),task(3,'PENDING')]})
        self.assertEqual(create(self.root/'base',self.root/'target',self.root/'delta'),3)
        materialize(self.root/'base',self.root/'delta',self.root/'restored')
        self.assertEqual((self.root/'restored/task.jsonl').read_bytes(),(self.root/'target/task.jsonl').read_bytes())
        snapshot(self.root/'next', {'task':[task(1,'DONE'),task(3,'DONE'),task(4,'PENDING')]})
        create(self.root/'target',self.root/'next',self.root/'delta2')
        materialize(self.root/'restored',self.root/'delta2',self.root/'restored2')
        self.assertEqual((self.root/'restored2/task.jsonl').read_bytes(),(self.root/'next/task.jsonl').read_bytes())

    def test_audit_append_delta(self):
        first=[1,None,'SYNTHETIC',None,None,datetime.datetime(2026,10,1)]
        second=[2,None,'SYNTHETIC',None,None,datetime.datetime(2026,10,2)]
        snapshot(self.root/'base',{'audit_log':[first]},'audit')
        snapshot(self.root/'target',{'audit_log':[first,second]},'audit')
        self.assertEqual(create(self.root/'base',self.root/'target',self.root/'delta'),1)
        self.assertEqual(materialize(self.root/'base',self.root/'delta',self.root/'out')['scope'],'audit')

    def test_append_only_update_and_delete_rejected(self):
        row=[1,None,'SYNTHETIC',None,None,None]
        snapshot(self.root/'base',{'audit_log':[row]},'audit')
        changed=copy.deepcopy(row); changed[2]='CHANGED'
        snapshot(self.root/'changed',{'audit_log':[changed]},'audit')
        snapshot(self.root/'deleted',{},'audit')
        for target in ('changed','deleted'):
            with self.assertRaises(ValueError): create(self.root/'base',self.root/target,self.root/(target+'delta'))

    def test_missing_table_manifest_rejected(self):
        data=snapshot(self.root/'base'); data['tables'].pop()
        (self.root/'base/manifest.json').write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError): validate(self.root/'base')

    def test_changed_rows_rejected_by_checksum(self):
        snapshot(self.root/'base',{'task':[task(1,'PENDING')]})
        (self.root/'base/task.jsonl').write_text(row_text(task(1,'DONE')),encoding='utf-8')
        with self.assertRaises(ValueError): validate(self.root/'base')

    def test_duplicate_keys_rejected(self):
        snapshot(self.root/'base',{'task':[task(1,'PENDING'),task(1,'PENDING')]})
        with self.assertRaises(ValueError): validate(self.root/'base')

    def test_row_width_and_path_escape_rejected(self):
        snapshot(self.root/'base',{'task':[[1]]})
        with self.assertRaises(ValueError): validate(self.root/'base')
        data=json.loads((self.root/'base/manifest.json').read_text())
        data['tables'][0]['file']='../outside.jsonl'
        (self.root/'base/manifest.json').write_text(json.dumps(data),encoding='utf-8')
        with self.assertRaises(ValueError): validate(self.root/'base')

    def test_wrong_base_or_tampered_delta_rejected_before_output(self):
        snapshot(self.root/'base',{'task':[task(1,'PENDING')]})
        snapshot(self.root/'target',{'task':[task(1,'DONE')]})
        snapshot(self.root/'other')
        create(self.root/'base',self.root/'target',self.root/'delta')
        with self.assertRaises(ValueError): materialize(self.root/'other',self.root/'delta',self.root/'bad')
        self.assertFalse((self.root/'bad').exists())
        with (self.root/'delta/task.delta.jsonl').open('a') as stream: stream.write('{}\n')
        with self.assertRaises(ValueError): materialize(self.root/'base',self.root/'delta',self.root/'bad2')
        self.assertFalse((self.root/'bad2').exists())

    def test_existing_output_never_overwritten(self):
        snapshot(self.root/'base'); snapshot(self.root/'target')
        (self.root/'output').mkdir(); (self.root/'output/keep').write_text('keep')
        with self.assertRaises(FileExistsError): create(self.root/'base',self.root/'target',self.root/'output')
        self.assertEqual((self.root/'output/keep').read_text(),'keep')

    def test_matching_hash_does_not_allow_invalid_nullable_or_plaintext_rows(self):
        snapshot(self.root/'bad_amount',{'txn':[[1,1,1,datetime.datetime(2026,10,1),'in',None,None,'SYNTHETIC','D***',1]]})
        snapshot(self.root/'bad_name',{'staff_user':[[1,'UNMASKED RAW NAME',None,None]]})
        for folder in ('bad_amount','bad_name'):
            with self.assertRaises(ValueError): validate(self.root/folder)


if __name__ == '__main__': unittest.main()
