"""Offline syntax/structural checks, not a MySQL SQL parser or runtime substitute."""
import ast
import json
from pathlib import Path
import re

DATA = Path(__file__).resolve().parents[1]
python_files = list(DATA.rglob('*.py'))
for file in python_files: ast.parse(file.read_text(encoding='utf-8'), filename=str(file))
print('Python AST files=' + str(len(python_files)) + ' errors=0')
sql_files = list(DATA.rglob('*.sql'))
for file in sql_files:
    sql = '\n'.join(line for line in file.read_text(encoding='utf-8').splitlines() if not line.startswith('--'))
    # Generated SQL contains no escapes/semicolons inside strings. Check quote balance.
    assert sql.count('`') % 2 == 0 and sql.count("'") % 2 == 0, file
    assert not re.search(r'(?i)DROP\s+DATABASE|TRUNCATE\s', sql), file
print('SQL structural files=' + str(len(sql_files)) + '; balanced delimiters/no database deletion; MySQL syntax NOT executed')
core = (DATA / 'core/schema.sql').read_text(encoding='utf-8')
assert core.count('CREATE TABLE ') == 11
assert all(name in core for name in ('ix_task_status', 'ix_txn_task_date', 'ix_metric_task_code', 'ix_report_task_version'))
assert 'PARTITION BY RANGE COLUMNS (`txn_date`)' in core
views = (DATA / 'core/views_grants.sql').read_text()
assert views.count('CREATE SQL SECURITY DEFINER VIEW ') == 11
for table in ('report', 'metric_value', 'template', 'rule'):
    assert not re.search(r'GRANT[^;]*(?:UPDATE|DELETE)[^;]*`' + table + '`', views)
assert not re.search(r'GRANT[^;]*(?:UPDATE|DELETE)[^;]*audit_log', views)
assert not re.search(r"GRANT[^;]*(?:INSERT|UPDATE|DELETE)[^;]*rc_role_reader", views)
print('Partition/index/view/append-only grant structure PASS; runtime pruning/grants still required')
for file in DATA.rglob('*'):
    if not file.is_file() or file.suffix not in ('.py','.sql','.ps1','.ini','.env','.json','.md','.txt','.example'): continue
    source = file.read_text(encoding='utf-8')
    assert not any(line.rstrip() != line for line in source.splitlines()), 'Trailing whitespace: ' + str(file)
    assert not source.endswith('\n\n'), 'Extra blank line at EOF: ' + str(file)
    assert not re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}', source), file
    assert not re.search(r'''(?i)password\s*=\s*['"][^'"\s]+['"]''', source), file
print('Credential pattern scan PASS (heuristic; not proof of absence)')
manifest = json.loads((DATA / 'inputs/demo_images/manifest.json').read_text())
from PIL import Image
for item in manifest:
    with Image.open(DATA / 'inputs/demo_images' / item['file']) as image:
        assert image.size == (item['width'], item['height']) and image.format == 'PNG'
        image.verify()
assert len(manifest) == 9 and all(item['synthetic'] for item in manifest)
print('Synthetic image fixtures=9 PNG decode/dimensions PASS; carrier classification NOT verified')
