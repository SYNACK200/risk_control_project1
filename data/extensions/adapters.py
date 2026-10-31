"""Isolated synthetic-only prototypes, NOT approved public interfaces or tables.

No interest calculation, OCR invocation, external network, or core schema change.
"""
import copy
import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import uuid
from validation import check_text


class DemoRateCatalog:
    def __init__(self, document, allow_demo=False):
        if not allow_demo or document.get('synthetic_only') is not True:
            raise ValueError('Explicit synthetic-only opt-in required')
        self.records = copy.deepcopy(document['records'])
        for record in self.records:
            if set(record) != {'bank_code','effective_from','effective_to','rate','rate_unit','day_count_basis','source','version'}:
                raise ValueError('Prototype rate fields mismatch')
            start = datetime.date.fromisoformat(record['effective_from'])
            end = datetime.date.fromisoformat(record['effective_to'])
            if start >= end or type(record['version']) is not int or record['version'] <= 0:
                raise ValueError('Invalid prototype period/version')
            if not isinstance(record['rate'],str) or not Decimal(record['rate']).is_finite():
                raise ValueError('Exact prototype rate required')
            if not all(isinstance(record[key],str) and record[key] for key in ('bank_code','rate_unit','day_count_basis','source')):
                raise ValueError('Explicit source and units required')
        for index,left in enumerate(self.records):
            for right in self.records[index+1:]:
                if left['bank_code'] == right['bank_code'] and left['version'] == right['version'] and max(left['effective_from'],right['effective_from']) < min(left['effective_to'],right['effective_to']):
                    raise ValueError('Ambiguous prototype effective periods')

    def lookup(self, bank_code, day, version):
        datetime.date.fromisoformat(day)
        hits=[record for record in self.records if record['bank_code']==bank_code and record['version']==version and record['effective_from']<=day<record['effective_to']]
        if len(hits) != 1: raise LookupError('No unique supplied Demo rate')
        return copy.deepcopy(hits[0])


def canonical(document):
    return json.dumps(document,sort_keys=True,ensure_ascii=True,allow_nan=False,separators=(',',':')).encode('utf-8')


def validate_ocr(document):
    if document.get('synthetic_only') is not True or type(document.get('file_id')) is not int or document['file_id']<=0:
        raise ValueError('Synthetic prototype file identity required')
    if not isinstance(document.get('parser_version'),str) or not document['parser_version']:
        raise ValueError('Parser version required')
    if not isinstance(document.get('lines'),list) or not document['lines']: raise ValueError('Nonempty line collection required')
    for line in document['lines']:
        if set(line) != {'page_no','bbox_normalized','confidence','masked_text'}:
            raise ValueError('Prototype OCR fields mismatch')
        if type(line['page_no']) is not int or line['page_no']<=0: raise ValueError('Invalid page')
        box=line['bbox_normalized']
        if not isinstance(box,list) or len(box)!=4 or any(type(v) not in (int,float) or not 0<=v<=1 for v in box): raise ValueError('Invalid normalized box')
        if box[0]>=box[2] or box[1]>=box[3]: raise ValueError('Inverted/empty box')
        confidence=line['confidence']
        if type(confidence) not in (int,float) or not 0<=confidence<=1: raise ValueError('Invalid confidence')
        if not isinstance(line['masked_text'],str): raise ValueError('Masked text required')
        check_text(line['masked_text'])
    canonical(document)


def append_ocr(directory, document):
    validate_ocr(document)
    payload=copy.deepcopy(document)
    digest=hashlib.sha256(canonical(payload)).hexdigest()
    folder=Path(directory).resolve()
    if not folder.is_dir(): raise ValueError('Caller must provide a pre-protected artifact directory')
    path=folder/('ocr-'+uuid.uuid4().hex+'.json')
    with path.open('x',encoding='utf-8') as stream:
        json.dump({'prototype_format':1,'artifact_sha256':digest,'payload':payload},stream,ensure_ascii=True,indent=2)
        stream.write('\n')
    return path


def read_ocr(path):
    data=json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('prototype_format')!=1 or hashlib.sha256(canonical(data['payload'])).hexdigest()!=data['artifact_sha256']:
        raise ValueError('Prototype artifact checksum mismatch')
    validate_ocr(data['payload'])
    return data['payload']
