"""Synthetic-only framing and read-only authentication tests."""
import contextlib
import io
import json
import pathlib
import struct
import sys
import types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import authenticate_pipe as target

def frame(value):
    payload = json.dumps({'password': value}, ensure_ascii=False).encode('utf-8')
    return struct.pack('<I', len(payload)) + payload

for i, value in enumerate(['Synthetic-42!', '  spaces  ', '!"\\$`&|<>', '合成é😀']):
    assert target.receive_secret(io.BytesIO(frame(value))) == value
    print('PASS: synthetic roundtrip ' + str(i + 1))
bad = [frame(''), frame('x\x16y'), frame('x\ny'), frame('x\x7fy'), frame('x\x85y'),
       b'', b'\x01', struct.pack('<I', 65537), frame('abc')[:-1], frame('abc') + b'x', frame(None)]
for i, payload in enumerate(bad):
    try:
        target.receive_secret(io.BytesIO(payload))
    except (ValueError, TypeError):
        pass
    else:
        raise AssertionError('invalid input accepted')
    print('PASS: invalid frame/input ' + str(i + 1))

queries = []
class Cursor:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql): queries.append(sql)
    def fetchone(self): return ('8.4.13', 3307, 'D:\\RiskControlDemo\\mysql84\\data\\', 'root@localhost')
class Connection:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return Cursor()
def connect(**kwargs):
    assert kwargs['host'] == '127.0.0.1' and kwargs['port'] == 3307
    assert kwargs['password'] == '合成é😀'.encode('utf-8')
    return Connection()
target.dependencies = lambda: types.SimpleNamespace(connect=connect)
old_stdin, old_argv = sys.stdin, sys.argv
try:
    sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(frame('合成é😀')))
    sys.argv = ['test', 'authenticate']
    output = io.StringIO()
    with contextlib.redirect_stdout(output): assert target.main() == 0
    assert output.getvalue() == 'AUTHENTICATION PASS\n'
    assert len(queries) == 1 and queries[0].startswith('SELECT ')
    print('PASS: authentication uses SELECT only, fixed success output')
    def fail(**kwargs): raise RuntimeError(1045, 'SYNTHETIC-DO-NOT-RENDER')
    target.dependencies = lambda: types.SimpleNamespace(connect=fail)
    sys.stdin = types.SimpleNamespace(buffer=io.BytesIO(frame('synthetic')))
    output = io.StringIO()
    with contextlib.redirect_stdout(output): assert target.main() == 1
    assert output.getvalue() == 'AUTHENTICATION FAIL: AUTHENTICATION_REJECTED\n'
    print('PASS: 1045 safe category, exception text suppressed')
    class Cancel:
        def read(self, count): raise KeyboardInterrupt()
    sys.stdin = types.SimpleNamespace(buffer=Cancel())
    output = io.StringIO()
    with contextlib.redirect_stdout(output): assert target.main() == 1
    assert output.getvalue() == 'AUTHENTICATION FAIL: INPUT_REJECTED\n'
    print('PASS: cancellation without traceback')
finally:
    sys.stdin, sys.argv = old_stdin, old_argv
print('Credential pipe Python: 18 PASS; no real terminal, credentials or database')
