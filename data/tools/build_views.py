"""Generate masking views and explicit grants offline; never apply SQL."""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
core = ROOT / 'data' / 'core'
schema = json.loads((core / 'schema.json').read_text())
output = ['-- Apply only through an approved guarded migration after all core tables exist.']
for table, fields in schema.items():
    database = 'rc_demo_audit' if table == 'audit_log' else 'rc_demo_report' if table in ('metric_value', 'report') else 'rc_demo_biz'
    columns = []
    for field in fields:
        expression = '`' + field + '`'
        if field == 'account_no':
            expression = "CASE WHEN account_no IS NULL THEN NULL WHEN CHAR_LENGTH(account_no)<=8 THEN REPEAT('*',CHAR_LENGTH(account_no)) ELSE CONCAT(LEFT(account_no,4),REPEAT('*',CHAR_LENGTH(account_no)-8),RIGHT(account_no,4)) END"
        if field in ('name', 'counterparty_name'):
            expression = "CONCAT(LEFT(`" + field + "`,1),'***')"
        if field in ('summary', 'resolution', 'note', 'storage_path', 'expr', 'check_result', 'hits', 'layers', 'evidence', 'limitations', 'field_map', 'threshold'):
            expression = "NULL"
        columns.append(expression + ' AS `' + field + '`')
    view = '`' + database + '`.`v_' + table + '`'
    output.append('CREATE SQL SECURITY DEFINER VIEW ' + view + ' AS SELECT ' + ', '.join(columns) + ' FROM `' + database + '`.`' + table + '`;')
    if table == 'audit_log':
        output.append("GRANT INSERT ON rc_demo_audit.audit_log TO 'rc_role_audit_writer'@'localhost';")
    else:
        permissions = 'SELECT, INSERT' if table in ('report', 'metric_value', 'template', 'rule') else 'SELECT, INSERT, UPDATE'
        output.append('GRANT ' + permissions + ' ON `' + database + '`.`' + table + "` TO 'rc_role_app'@'localhost';")
        output.append('GRANT SELECT ON ' + view + " TO 'rc_role_reader'@'localhost';")
(core / 'views_grants.sql').write_text('\n\n'.join(output) + '\n')
print('Generated views and table-level grants; not applied or runtime verified')
