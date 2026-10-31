"""Optional data-side validation, not bank risk/business judgement.

No logging of rejected values. JSON/free-text scanning is heuristic and cannot
replace an upstream approved sanitizer or role authorization.
"""
import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
from pathlib import Path
import re

SCHEMA = json.loads((Path(__file__).resolve().parent / 'core/schema.json').read_text(encoding='utf-8'))
MONEY = {'amount', 'balance', 'opening_balance', 'closing_balance'}
UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def money(value, positive=False):
    if isinstance(value, (float, bool)) or not isinstance(value, (str, Decimal, int)):
        raise ValueError('Money must be a decimal string, integer or Decimal')
    if not re.fullmatch(r'-?[0-9]+(?:\.[0-9]{1,2})?', str(value)):
        raise ValueError('Money scale or representation rejected')
    amount = Decimal(value)
    if not amount.is_finite() or abs(amount) >= Decimal('10000000000000000') or (positive and amount <= 0):
        raise ValueError('Money range rejected')
    return amount.quantize(Decimal('0.01'))


def timestamp(value):
    try: value = datetime.datetime.fromisoformat(value) if isinstance(value, str) else value
    except ValueError: raise ValueError('Invalid timestamp') from None
    if not isinstance(value, datetime.datetime) or value.utcoffset() != datetime.timedelta(hours=8):
        raise ValueError('Timestamp must carry an explicit UTC+8 offset')
    return value.astimezone(UTC8).replace(tzinfo=None)


def mask_phone(value):
    if value is None: return None
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{11}', value): raise ValueError('Unsupported phone representation')
    return value[:3] + '****' + value[-4:]


def identity_digest(value, key):
    """Keyed hash only. Key is supplied by an approved external secret provider."""
    if not isinstance(key, bytes) or len(key) < 32: raise ValueError('External hash key must be at least 32 bytes')
    if not isinstance(value, str) or not value: raise ValueError('Empty identifier')
    return hmac.new(key, value.encode('utf-8'), hashlib.sha256).hexdigest()


def check_text(value):
    if isinstance(value, str):
        if re.search(r'(?<![0-9])[0-9]{11,19}(?![0-9])', value):
            raise ValueError('Possible unmasked identifier in text')
    elif isinstance(value, dict):
        for key, item in value.items(): check_text(key); check_text(item)
    elif isinstance(value, (list, tuple)):
        for item in value: check_text(item)


def validate_record(table, record):
    if table not in SCHEMA or not isinstance(record, dict) or set(record) - set(SCHEMA[table]):
        raise ValueError('Unknown table or field')
    output = dict(record)
    from privacy import FORBIDDEN_KEYS
    def check_storage_keys(value):
        if isinstance(value, bytes): raise ValueError('Binary originals cannot be stored in records')
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in FORBIDDEN_KEYS: raise ValueError('Credentials or original text cannot be stored')
                check_storage_keys(item)
        elif isinstance(value, (list, tuple)):
            for item in value: check_storage_keys(item)
    check_storage_keys(output)
    for field, definition in SCHEMA[table].items():
        value = output.get(field)
        if value is None:
            if 'NOT NULL' in definition and not ('AUTO_INCREMENT' in definition and field not in output):
                raise ValueError('Required field missing: ' + table + '.' + field)
            continue
        if field in MONEY: output[field] = money(value, table == 'txn' and field == 'amount')
        elif definition.startswith('DATETIME'): output[field] = timestamp(value)
        elif definition.startswith(('BIGINT', 'INT')):
            limit = 2**64 if definition.startswith('BIGINT') else 2**32
            if type(value) is not int or not 0 <= value < limit: raise ValueError('Unsigned integer rejected')
        elif definition.startswith('BOOLEAN'):
            if type(value) is not bool: raise ValueError('Boolean rejected')
        elif definition.startswith('JSON'):
            if isinstance(value, str):
                try: value = json.loads(value)
                except ValueError: raise ValueError('Invalid JSON') from None
            check_storage_keys(value)
            check_text(value)
            output[field] = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        elif field == 'value_num':
            if isinstance(value, (bool, float)): raise ValueError('Metric requires exact decimal')
            try: number = Decimal(value)
            except (InvalidOperation, TypeError, ValueError): raise ValueError('Invalid metric decimal') from None
            if not number.is_finite() or abs(number) >= Decimal(10)**22 or number.as_tuple().exponent < -8:
                raise ValueError('Metric decimal range/scale rejected')
            output[field] = number
        else:
            if not isinstance(value, str): raise ValueError('Expected text')
            if definition.startswith('VARCHAR') and len(value) > 255: raise ValueError('Text length rejected')
            if field == 'sha256':
                if not re.fullmatch(r'[0-9a-f]{64}', value): raise ValueError('SHA256 representation rejected')
            else: check_text(value)
    for field in ('name', 'counterparty_name'):
        if output.get(field) is not None and not re.fullmatch(r'.\*+', output[field]): raise ValueError('Name must already be masked')
    if output.get('account_no') is not None and not re.fullmatch(r'(?:[0-9]{4}\*+[0-9]{4}|\*{1,8})', output['account_no']):
        raise ValueError('Account must already be masked')
    if output.get('carrier') not in (None,'electronic','image','screenshot'): raise ValueError('Unknown carrier')
    if table == 'task' and output.get('task_type') not in (None,'credit','batch'): raise ValueError('Unknown task type')
    return output
