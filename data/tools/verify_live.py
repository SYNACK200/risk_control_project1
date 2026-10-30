"""Read-only contract/DDL/live-field comparison; outputs identifiers only."""
import argparse
import json
from pathlib import Path
import re


def column_matches(definition, column):
    name,sql_type,nullable,extra,charset,collation,default=column
    expected=re.match(r'^([A-Z]+(?:\([0-9,]+\))?(?: UNSIGNED)?)',definition)[1].lower()
    if expected=='boolean': expected='tinyint(1)'
    if sql_type.lower()!=expected or nullable!=('NO' if 'NOT NULL' in definition else 'YES'):
        return False
    if extra.lower()!=('auto_increment' if 'AUTO_INCREMENT' in definition else '') or default is not None:
        return False
    if expected.startswith(('char(', 'varchar(', 'text')):
        return (charset,collation)==(('ascii','ascii_bin') if 'CHARACTER SET ascii' in definition else ('utf8mb4','utf8mb4_0900_ai_ci'))
    return True


def main():
    import subprocess
    import sys
    parser = argparse.ArgumentParser()
    parser.add_argument('--user', required=True)
    args = parser.parse_args()
    # Compatibility CLI: all credentials are now read by the native secure entry.
    script = Path(__file__).resolve().parents[1] / 'bootstrap/08_core_schema.ps1'
    raise SystemExit(subprocess.call(['pwsh', '-NoProfile', '-File', str(script),
                                    '-PythonExe', sys.executable, '-Mode', 'Verify', '-AdminUser', args.user]))


if __name__ == '__main__':
    try: main()
    except Exception: raise SystemExit('Live verification failed; no row data disclosed')
