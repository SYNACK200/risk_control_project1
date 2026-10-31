"""Windows console-only secret input. Never uses stdin pipes or console history."""
import ctypes
import os
from ctypes import wintypes

class ConsoleInputError(RuntimeError):
    pass

class WindowsConsole:
    def __init__(self):
        if os.name != "nt":
            raise ConsoleInputError("CONSOLE_UNAVAILABLE")
        k = self.k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        for name, args in {
            "GetConsoleMode": [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)],
            "SetConsoleMode": [wintypes.HANDLE, wintypes.DWORD],
            "FlushConsoleInputBuffer": [wintypes.HANDLE],
            "CloseHandle": [wintypes.HANDLE],
            "ReadConsoleW": [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p],
            "WriteConsoleW": [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p],
        }.items():
            fn = getattr(k, name)
            fn.argtypes = args
            fn.restype = wintypes.BOOL
        self.input = self.output = None
        try:
            self.input = self.open("CONIN$")
            self.output = self.open("CONOUT$")
            mode = wintypes.DWORD()
            if not k.GetConsoleMode(self.input, ctypes.byref(mode)):
                raise ConsoleInputError("CONSOLE_UNAVAILABLE")
            self.mode = mode.value
        except BaseException:
            self.close()
            raise

    def open(self, device):
        h = self.k.CreateFileW(device, 0xC0000000, 3, None, 3, 0, None)
        if h == ctypes.c_void_p(-1).value:
            raise ConsoleInputError("CONSOLE_UNAVAILABLE")
        return h

    def set_mode(self, mode):
        if not self.k.SetConsoleMode(self.input, mode):
            raise ConsoleInputError("CONSOLE_MODE_FAILURE")

    def flush(self):
        if not self.k.FlushConsoleInputBuffer(self.input):
            raise ConsoleInputError("CONSOLE_FLUSH_FAILURE")

    def write(self, text):
        n = wintypes.DWORD()
        if not self.k.WriteConsoleW(self.output, text, len(text), ctypes.byref(n), None):
            raise ConsoleInputError("CONSOLE_OUTPUT_FAILURE")

    def read(self):
        buf = ctypes.create_unicode_buffer(2)
        n = wintypes.DWORD()
        try:
            if not self.k.ReadConsoleW(self.input, buf, 1, ctypes.byref(n), None):
                raise ConsoleInputError("CONSOLE_READ_FAILURE")
            if not n.value:
                raise EOFError()
            return buf[0]
        finally:
            ctypes.memset(ctypes.addressof(buf), 0, ctypes.sizeof(buf))

    def close(self):
        for h in (self.input, self.output):
            if h is not None:
                self.k.CloseHandle(h)
        self.input = self.output = None


def read_hidden_line(prompt, factory=WindowsConsole):
    console = factory()
    chars = []
    try:
        # Raw Unicode input: no echo, cooked-line history, processed Ctrl+C or VT escapes.
        console.set_mode(console.mode & ~(0x1 | 0x2 | 0x4 | 0x200))
        console.flush()  # discard stale/type-ahead input BEFORE displaying the prompt
        console.write(prompt)
        while True:
            char = console.read()
            if char in ("\r", "\n"):
                break
            if char == "\x03":
                raise KeyboardInterrupt()
            if char == "\x1a":
                raise EOFError()
            if char == "\b":
                if chars:
                    chars.pop()
                continue
            if ord(char) < 32 or ord(char) == 127:
                raise ConsoleInputError("CONTROL_CHARACTER")
            chars.append(char)
            if len(chars) > 4096:
                raise ConsoleInputError("INPUT_LIMIT")
        # Recombine UTF-16 surrogate pairs returned by ReadConsoleW; no normalization.
        value = "".join(chars).encode("utf-16-le", "surrogatepass").decode("utf-16-le")
        if not value:
            raise ConsoleInputError("EMPTY_INPUT")
        return value
    finally:
        chars.clear()
        try:
            console.flush()  # remove trailing pasted lines before restoring echo
        finally:
            try:
                console.set_mode(console.mode)
            finally:
                console.close()
