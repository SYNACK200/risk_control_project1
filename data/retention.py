"""Retention candidate list only. Never deletes or connects to any service."""
import datetime


def retention_preview(records, now, retention_days):
    # Duration must be supplied by the caller; no unapproved production default.
    if type(retention_days) is not int or retention_days <= 0:
        raise ValueError('An explicit positive retention period is required')
    if not isinstance(now, datetime.datetime) or now.utcoffset() is None:
        raise ValueError('Reference time must have an offset')
    cutoff = now - datetime.timedelta(days=retention_days)
    output = []
    for record in records:
        kind, identifier, created = record['kind'], record['id'], record['created_at']
        if kind not in {'file','txn','report','audit'} or type(identifier) is not int:
            raise ValueError('Unsupported retention record')
        if not isinstance(created, datetime.datetime) or created.utcoffset() is None:
            raise ValueError('Creation time must have an offset')
        if kind == 'audit':
            output.append({'kind':kind, 'id':identifier, 'action':'retain'})
        elif created <= cutoff:
            output.append({'kind':kind, 'id':identifier, 'action':'archive_review'})
    return output
