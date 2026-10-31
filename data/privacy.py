"""Data-side privacy functions. No database, network, file deletion or logging."""
import re

FORBIDDEN_KEYS = {'password', 'passwd', 'token', 'access_token', 'secret', 'private_key',
                  'raw_text', 'full_text', 'ocr_text', 'raw_ocr', 'pdf_bytes', 'file_bytes'}


def mask_account(value):
    if value is None: return None
    if not isinstance(value, str): raise ValueError('Account must be text')
    if '*' in value:
        if not re.fullmatch(r'(?:[0-9]{4}\*+[0-9]{4}|\*{1,8})', value):
            raise ValueError('Unsupported masked account')
        return value
    if not re.fullmatch(r'[0-9]+', value): raise ValueError('Unsupported account representation')
    return value[:4] + '*' * (len(value) - 8) + value[-4:] if len(value) > 8 else '*' * len(value)


def mask_name(value):
    if value is None or value == '': return value
    if not isinstance(value, str): raise ValueError('Name must be text')
    return value if re.fullmatch(r'.\*+', value) else value[0] + '***'


def redact_text(value):
    # Known structured identifiers only; does not claim to detect arbitrary names in prose.
    value = re.sub(r'(?<![0-9])[0-9]{17}[0-9Xx](?![0-9])', '[证件已隐藏]', value)
    value = re.sub(r'(?<![0-9])[0-9]{12,19}(?![0-9])', lambda m: mask_account(m[0]), value)
    return re.sub(r'(?<![0-9])([0-9]{3})[0-9]{4}([0-9]{4})(?![0-9])', r'\1****\2', value)


def redact_payload(value):
    if isinstance(value, bytes): raise ValueError('Binary originals cannot be stored in records')
    if isinstance(value, str): return redact_text(value)
    if isinstance(value, list): return [redact_payload(v) for v in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if not isinstance(key, str): raise ValueError('JSON keys must be text')
            if key.lower() in FORBIDDEN_KEYS: raise ValueError('Credentials or original text cannot be stored')
            if key in ('sample_rows','samples'): continue  # Diagnostic text excerpts are not stored.
            if key in ('amount','balance','opening_balance','closing_balance','value_num','sha256','storage_path','biz_no'):
                result[key] = item
            elif key in ('account_no','bank_account_no'): result[key] = mask_account(item)
            elif key in ('holder_name','customer_name','counterparty_name'): result[key] = mask_name(item)
            elif key in ('id_card','identity_no'): raise ValueError('Use the existing keyed identifier digest before storage')
            else: result[key] = redact_payload(item)
        return result
    return value


def prepare_for_storage(table, record):
    result = redact_payload(record)
    if table == 'staff_user' and result.get('name') is not None:
        result['name'] = mask_name(result['name'])
    return result


def audit_metadata(event, object_id, outcome):
    """No arbitrary detail/message argument: audit only event, reference and outcome."""
    if event not in {'received','password_attempt','parse','report','export'}:
        raise ValueError('Unknown audit event')
    if outcome not in {'success','failure','cancelled'} or type(object_id) is not int:
        raise ValueError('Invalid audit metadata')
    return {'event':event, 'object_id':object_id, 'outcome':outcome}
