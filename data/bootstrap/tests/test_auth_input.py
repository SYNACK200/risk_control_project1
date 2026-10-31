"""Synthetic input and fixed-connection tests for the current provision core."""
import contextlib
import io
import pathlib
import sys
import types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import provision_core as core
cases = [("", False), ("Synthetic!42", True), ("  synthetic  ", True),
         ("Synthetic-\u6f22\u5b57", True), ("x\x16y", False), ("x\ny", False),
         ("x\ry", False), ("x\x00y", False), ("x\x7fy", False)]
for i, (value, accepted) in enumerate(cases):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = core.request_secret("root", "login", reader=lambda stream: value)
        assert result == value
        actual = True
    except core.SafeFailure:
        actual = False
    assert actual == accepted
    print("PASS: synthetic input case " + str(i + 1))
captured = {}
def connect(**kwargs):
    captured.update(kwargs)
    return object()
core.pymysql = types.SimpleNamespace(connect=connect)
core.connect("root", "Synthetic-\u00e9-\u6f22")
assert captured["host"] == "127.0.0.1" and captured["port"] == 3307
assert captured["user"] == "root" and captured["password"] == "Synthetic-\u00e9-\u6f22".encode("utf-8")
assert captured["local_infile"] is False
print("Auth input tests: 10 PASS; synthetic only; no connection")
