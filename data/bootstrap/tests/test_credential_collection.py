"""Synthetic collection regression for the current anonymous-pipe implementation."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import provision_core as core
existing = {u: False for u, r in core.pairs}
for label, error in [("eof", EOFError()), ("cancel", KeyboardInterrupt()), ("input", core.SafeFailure("INPUT_REJECTED"))]:
    asked = []
    def ask(user, phase, minimum=1):
        asked.append((user, phase))
        if user == "rc_demo_reader": raise error
        return "Synthetic-" + user + "-42!"
    try:
        core.collect_credentials(existing, ask)
        raise AssertionError("failure not propagated")
    except BaseException as actual:
        assert type(actual) is type(error)
        assert asked[-1] == ("rc_demo_reader", "new") and len(asked) == 3
    print("PASS: middle-account " + label)
result = core.collect_credentials(existing, lambda user, phase, minimum=1: "Synthetic-" + user + "-42!")
assert len(result) == 3 and len(set(result.values())) == 3
result.clear()
print("PASS: three distinct confirmed credentials")
for reuse, expected in [(False, "CONFIRMATION_MISMATCH"), (True, "REUSED_CREDENTIAL")]:
    def ask(user, phase, minimum=1): return "Synthetic-" + ("same" if reuse else phase) + "-42!"
    try:
        core.collect_credentials(existing, ask)
        raise AssertionError("invalid confirmation accepted")
    except core.SafeFailure as error:
        assert error.args == (expected,)
    print("PASS: " + expected)
print("Credential collection: 6 PASS; synthetic only; no connection")
