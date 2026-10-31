"""Run offline checks and capture actual stdout/stderr/exit codes in data/evidence."""
import datetime
import argparse
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser()
parser.add_argument('--evidence-name',default='20261029-continuation.txt')
args=parser.parse_args()
if Path(args.evidence_name).name!=args.evidence_name or not args.evidence_name.endswith('.txt'):
    parser.error('Evidence must be a plain .txt filename inside data/evidence')
commands = [[sys.executable, '-B', 'data/tools/' + file] for file in (
    'check_core.py', 'check_static.py', 'test_synthetic.py',
    'test_backup_format.py', 'test_integration.py', 'test_migration_guards.py',
    'test_snapshots.py','test_restore_flow.py','test_validation.py','test_benchmark.py',
    'test_partitions.py','test_extensions.py','test_synthetic_audit.py','test_live_metadata.py','test_schema_checker.py','test_carrier_evaluator.py')]
commands += [[sys.executable, '-B', 'data/tools/audit_synthetic.py'],
             ['pwsh', '-NoProfile', '-File', 'data/tools/check_powershell.ps1'],
             ['pwsh', '-NoProfile', '-File', 'data/bootstrap/tests/Test-Preflight.ps1'],
             [sys.executable, '-B', 'data/bootstrap/tests/test_auth_dependencies.py'],
             [sys.executable, '-B', 'data/bootstrap/tests/test_auth_input.py'],
             [sys.executable, '-B', 'data/bootstrap/tests/test_credential_collection.py'],
             [sys.executable, '-B', 'data/bootstrap/tests/test_credential_pipe.py'],
             [sys.executable, '-B', 'data/bootstrap/tests/test_provision.py'],
             ['pwsh', '-NoProfile', '-File', 'data/bootstrap/tests/Test-ProvisionDialogue.ps1', '-PythonExe', sys.executable],
             [sys.executable, '-B', 'data/bootstrap/tests/test_core_schema.py'],
             [sys.executable, '-B', 'data/bootstrap/tests/test_migration_env.py'],
             ['pwsh', '-NoProfile', '-File', 'data/bootstrap/tests/Test-CoreDialogue.ps1', '-PythonExe', sys.executable],
             ['git', 'diff', '--check'], ['git', 'status', '--short', '--untracked-files=all']]
output = ['Offline validation at ' + datetime.datetime.now().isoformat(),
          'No DB connections, service operations or Git index writes.\n']
failed = 0
for command in commands:
    result = subprocess.run(command, cwd=str(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    text = result.stdout.decode('utf-8', errors='replace').replace('\r\n', '\n')
    line = '> ' + subprocess.list2cmdline(command) + '\n' + text + '\nEXIT=' + str(result.returncode)
    print(line)
    output.append(line)
    failed += result.returncode != 0
output.append('COMMANDS=' + str(len(commands)) + ' FAILED=' + str(failed))
folder = root / 'data/evidence'
folder.mkdir(exist_ok=True)
(folder / args.evidence_name).write_text('\n\n'.join(output) + '\n', encoding='utf-8')
print(output[-1])
raise SystemExit(bool(failed))
