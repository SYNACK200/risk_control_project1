"""Offline core DDL builder. Never connects to a database."""
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
TABLES = ['staff_user', 'file_obj', 'task', 'bank_account', 'txn', 'metric_value', 'report', 'template', 'rule', 'appeal', 'audit_log']
DB = {t: 'rc_demo_biz' for t in TABLES}
DB.update(metric_value='rc_demo_report', report='rc_demo_report', audit_log='rc_demo_audit')


def contract_fields():
    text = (ROOT / 'contract.md').read_text(encoding='utf-8')
    rows = re.findall(r'^\| ([a-z_]+) \| ([^|]+) \| ([^|]+) \|', text, re.M)
    return {t: fields.strip().split(chr(12289)) for t, fields, _ in rows if t in TABLES}


def sql_type(field):
    if field in {'amount', 'balance', 'opening_balance', 'closing_balance'}:
        return 'DECIMAL(18,2)'
    if field == 'value_num':
        return 'DECIMAL(30,8)'
    if field == 'sha256':
        return 'CHAR(64) CHARACTER SET ascii COLLATE ascii_bin'
    if field == 'id' or field.endswith('_id'):
        return 'BIGINT UNSIGNED'
    if field in {'period_start', 'period_end', 'txn_date', 'created_at'}:
        return 'DATETIME(6)'
    if field in {'version', 'template_version', 'caliber_version', 'width', 'height', 'pages', 'page_no'}:
        return 'INT UNSIGNED'
    if field == 'has_text_layer':
        return 'BOOLEAN'
    if field in {'check_result', 'hits', 'layers', 'limitations', 'evidence', 'field_map', 'threshold', 'resolution'}:
        return 'JSON'
    if field in {'summary', 'note', 'expr', 'storage_path'}:
        return 'TEXT'
    return 'VARCHAR(255)'


def build():
    fields = contract_fields()
    assert set(fields) == set(TABLES) and sum(map(len, fields.values())) == 82
    statements = []
    metadata = {}
    for table in TABLES:
        columns = []
        metadata[table] = {}
        for field in fields[table]:
            required = field == 'id' or (table == 'txn' and field in {'txn_date', 'amount'}) or (table == 'file_obj' and field == 'sha256') or (table == 'task' and field == 'biz_no')
            definition = sql_type(field) + (' NOT NULL' if required else ' NULL')
            if field == 'id' and table != 'txn':
                definition += ' AUTO_INCREMENT'
            columns.append('  `' + field + '` ' + definition)
            metadata[table][field] = definition
        columns.append('  PRIMARY KEY (`id`, `txn_date`)' if table == 'txn' else '  PRIMARY KEY (`id`)')
        if 'carrier' in fields[table]:
            columns.append("  CHECK (`carrier` IN ('electronic','image','screenshot'))")
        if table == 'task':
            columns.append("  CHECK (`task_type` IN ('credit','batch'))")
        if table == 'staff_user':
            roles = ['\u5ba1\u6279\u4eba', '\u6a21\u677f\u7ba1\u7406\u5458', '\u8fd0\u8425\u7ba1\u7406\u5458', '\u7cfb\u7edf\u7ba1\u7406\u5458']
            columns.append('  CHECK (`role` IN (' + ','.join("'" + role + "'" for role in roles) + '))')
        if table == 'file_obj': columns.append('  UNIQUE KEY uq_file_sha256 (`sha256`)')
        if table == 'bank_account':
            columns.append("  CHECK (`account_no` IS NULL OR REGEXP_LIKE(`account_no`, '^[0-9]{4}[*]+[0-9]{4}$|^[*]{1,8}$'))")
        if table == 'staff_user':
            columns.append("  CHECK (`name` IS NULL OR REGEXP_LIKE(`name`, '^.[*]+$'))")
        if table == 'task':
            columns.extend(['  UNIQUE KEY uq_task_biz_no (`biz_no`)', '  KEY ix_task_status (`status`, `id`)'])
        if table == 'txn':
            columns.extend(['  CHECK (`amount` > 0)', '  KEY ix_txn_task_date (`task_id`, `txn_date`, `id`)'])
            columns.append("  CHECK (`counterparty_name` IS NULL OR REGEXP_LIKE(`counterparty_name`, '^.[*]+$'))")
        if table == 'metric_value': columns.append('  KEY ix_metric_task_code (`task_id`, `metric_code`)')
        if table == 'report': columns.append('  KEY ix_report_task_version (`task_id`, `version`)')
        statement = 'CREATE TABLE `' + DB[table] + '`.`' + table + '` (\n' + ',\n'.join(columns) + '\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci'
        if table == 'txn':
            statement += "\nPARTITION BY RANGE COLUMNS (`txn_date`) (\n PARTITION p_before VALUES LESS THAN ('2026-10-01'),\n PARTITION p202610 VALUES LESS THAN ('2026-11-01'),\n PARTITION p202611 VALUES LESS THAN ('2026-12-01'),\n PARTITION p202612 VALUES LESS THAN ('2027-01-01'),\n PARTITION p_future VALUES LESS THAN (MAXVALUE)\n)"
        statements.append(statement + ';')
    output = ROOT / 'data' / 'core'
    output.mkdir(exist_ok=True)
    (output / 'schema.sql').write_text('-- OFFLINE DEMO DDL. Execute only after approved instance verification.\nSET SESSION time_zone = \'+08:00\';\n\n' + '\n\n'.join(statements) + '\n', encoding='utf-8')
    (output / 'schema.json').write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    dictionary = '# Demo physical dictionary\n\nTechnical proposal, not a replacement for contract.md or PR #3.\nSource reviewed: feat/data-schema commit 137e199; no commits merged or copied.\nOnly 11 tables / 82 existing fields. Business meanings remain in PR #3.\n\n'
    for table in TABLES:
        dictionary += '## ' + table + '\n\n| Field | Physical definition |\n| --- | --- |\n'
        dictionary += ''.join('| ' + f + ' | ' + d + ' |\n' for f, d in metadata[table].items()) + '\n'
    (output / 'physical_dictionary.md').write_text(dictionary.rstrip() + '\n', encoding='utf-8')
    print('Generated: 11 tables, 82 contract fields; no database connection')


if __name__ == '__main__':
    build()
