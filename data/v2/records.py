"""Contract-field handoff for V2. Does not alter tables or invoke backend startup."""
from decimal import Decimal
import json
from pathlib import Path
from privacy import prepare_for_storage
from validation import money

TABLES = json.loads((Path(__file__).parent / 'contract.json').read_text(encoding='utf-8'))['tables']


def prepare_record(table, record):
    if table not in TABLES or not isinstance(record, dict) or set(record) - set(TABLES[table]):
        raise ValueError('Unknown V2 contract table or field')
    record = dict(record)
    json_fields = {'task':('check_result','hits'), 'report':('layers','limitations','evidence'),
                   'template':('field_map',), 'rule':('threshold',)}
    for field in json_fields.get(table, ()):
        if isinstance(record.get(field),str):
            try: record[field] = json.loads(record[field])
            except ValueError: raise ValueError('Invalid JSON record') from None
    output = prepare_for_storage(table, record)
    for field in ('amount','balance','opening_balance','closing_balance'):
        if output.get(field) is not None:
            output[field] = money(output[field], table == 'txn' and field == 'amount')
    if output.get('value_num') is not None:
        value = output['value_num']
        if isinstance(value, (bool,float)): raise ValueError('Metric requires exact decimal')
        number = Decimal(value)
        if not number.is_finite(): raise ValueError('Metric must be finite')
        output['value_num'] = number
    if table == 'task_file':
        if output.get('role') not in ('original','supplement'): raise ValueError('Invalid material role')
        if any(type(output.get(k)) is not int or output[k] <= 0 for k in ('task_id','file_id','seq')):
            raise ValueError('Material references and sequence are required')
    return output
