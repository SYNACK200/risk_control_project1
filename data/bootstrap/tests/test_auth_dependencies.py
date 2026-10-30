"""Read-only unit tests: AST-extracted dependency checker, fake modules, no MySQL imports."""
import ast
import builtins
import contextlib
import io
import pathlib
import re
import types

code = (pathlib.Path(__file__).resolve().parents[1] / "authenticate_pipe.py").read_text(encoding="utf-8")
tree = ast.parse(code)
definition = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "dependencies")
isolated = ast.Module(body=[definition])
if "type_ignores" in ast.Module._fields:
    isolated.type_ignores = []
compiled = compile(ast.fix_missing_locations(isolated), "<dependency-check-only>", "exec")

def scenario(driver="1.1.1", crypto="46.0.0", missing=None, rsa=True, backend=True, python=(3, 12)):
    versions = {"PyMySQL": driver, "cryptography": crypto}
    auth = types.SimpleNamespace(_have_cryptography=rsa,
        sha2_rsa_encrypt=lambda: None, caching_sha2_password_auth=lambda: None)
    pymysql = types.SimpleNamespace()
    modules = {
        "re": re,
        "importlib.metadata": types.SimpleNamespace(version=lambda name: versions[name]),
        "pymysql": types.SimpleNamespace(_auth=auth),
        "cryptography.hazmat.backends": types.SimpleNamespace(
            default_backend=lambda: types.SimpleNamespace(rsa_padding_supported=lambda value: backend)),
        "cryptography.hazmat.primitives": types.SimpleNamespace(
            hashes=types.SimpleNamespace(SHA1=lambda: object())),
        "cryptography.hazmat.primitives.asymmetric": types.SimpleNamespace(
            padding=types.SimpleNamespace(MGF1=lambda value: value, OAEP=lambda **kw: kw)),
    }
    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if missing and name.startswith(missing):
            raise ImportError("simulated missing dependency")
        if name == "pymysql" and not fromlist:
            return pymysql
        if name not in modules:
            raise AssertionError("Unexpected import: " + name)
        return modules[name]
    safe_builtins = dict(vars(builtins))
    safe_builtins["__import__"] = fake_import
    namespace = {"__builtins__": safe_builtins, "re": re, "sys": types.SimpleNamespace(version_info=python) }
    exec(compiled, namespace)
    with contextlib.redirect_stdout(io.StringIO()):
        return namespace["dependencies"]()

cases = [
    ("accepted interface/version policy", {}, True),
    ("missing driver", {"missing": "pymysql"}, False),
    ("missing cryptography", {"missing": "cryptography"}, False),
    ("old driver version", {"driver": "1.0.3"}, False),
    ("unreviewed driver major", {"driver": "2.0.0"}, False),
    ("unreviewed crypto major", {"crypto": "50.0.0"}, False),
    ("driver missing RSA support", {"rsa": False}, False),
    ("backend missing OAEP support", {"backend": False}, False),
]
for name, kwargs, expected in cases:
    try:
        scenario(**kwargs)
        accepted = True
    except (ImportError, RuntimeError, ValueError):
        accepted = False
    assert accepted == expected, name
    print("PASS: " + name)

for candidate in [(3, 7), (3, 10), (3, 11), (3, 12), (3, 13), (3, 15), (4, 0)]:
    try:
        scenario(python=candidate)
        accepted = True
    except ValueError:
        accepted = False
    assert accepted == (candidate in ((3, 11), (3, 12)))
    print("PASS: Python version admission " + str(candidate))
print("Dependency tests: 15 PASS; fake imports only; no connection")
