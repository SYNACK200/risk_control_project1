"""Fake console only: never reads a terminal or connects to MySQL."""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from windows_console import read_hidden_line, ConsoleInputError

class Fake:
    mode = 0x207
    def __init__(self, text, fail=False):
        self.it = iter(text)
        self.events = []
        self.fail = fail
    def set_mode(self, m): self.events.append(("mode", m))
    def flush(self): self.events.append(("flush",))
    def write(self, text): self.events.append(("prompt",))
    def close(self): self.events.append(("close",))
    def read(self):
        if self.fail: raise OSError("synthetic failure")
        return next(self.it)

cases = [("ascii", "Synthetic!@#$%^&*()\r", "Synthetic!@#$%^&*()"),
         ("spaces", "  synthetic  \r", "  synthetic  "),
         ("unicode", "合成密碼é\r", "合成密碼é"),
         ("surrogate", "x\ud83d\ude00\r", "x😀"),
         ("paste-single-line", "Synthetic-Paste-42!\r\n", "Synthetic-Paste-42!"),
         ("backspace", "ab\bc\r", "ac"),
         ("empty", "\r", ConsoleInputError),
         ("control-v", "x\x16y\r", ConsoleInputError),
         ("tab", "x\ty\r", ConsoleInputError),
         ("escape", "x\x1by\r", ConsoleInputError),
         ("cancel", "x\x03", KeyboardInterrupt),
         ("eof", "x\x1a", EOFError)]
for name, text, expected in cases:
    fake = Fake(text)
    try:
        result = read_hidden_line("fixed prompt", lambda: fake)
        assert isinstance(expected, str) and result == expected
    except (ConsoleInputError, KeyboardInterrupt, EOFError) as error:
        assert isinstance(expected, type) and isinstance(error, expected)
    assert fake.events[:3] == [("mode", 0), ("flush",), ("prompt",)]
    assert fake.events[-3:] == [("flush",), ("mode", fake.mode), ("close",)]
    print("PASS: " + name)
fake = Fake("", fail=True)
try:
    read_hidden_line("fixed prompt", lambda: fake)
except OSError:
    pass
else:
    raise AssertionError("read failure swallowed")
assert fake.events[-2:] == [("mode", fake.mode), ("close",)]
print("PASS: mode restored after read failure")
print("Windows console tests: 13 PASS; fake console only; no real input")
