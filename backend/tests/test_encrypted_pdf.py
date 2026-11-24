"""加密件：解出明文副本这一步必须可靠。

背景：算法侧 parse 只认明文，而且它会把 pymupdf 的加密异常吞掉，
表现为「成功返回 0 笔」。所以加密件不在这里解，就会变成一份看起来正常、实际空的解析。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pymupdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.analysis import EncryptedFile, password_opens, plain_bytes  # noqa: E402

SAMPLE = Path(__file__).resolve().parents[2] / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "ccb.pdf"


def encrypted_source() -> bytes:
    doc = pymupdf.open(SAMPLE)
    tmp = Path(__file__).with_suffix(".tmp.pdf")
    doc.save(str(tmp), encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="1234", owner_pw="1234")
    doc.close()
    data = tmp.read_bytes()
    tmp.unlink(missing_ok=True)
    return data


@pytest.fixture(scope="module")
def enc() -> bytes:
    return encrypted_source()


def test_plain_file_passes_through():
    raw = SAMPLE.read_bytes()
    assert plain_bytes(raw, None) == raw


def test_correct_password_yields_openable_bytes(enc):
    out = plain_bytes(enc, "1234")
    assert out[:4] == b"%PDF"
    doc = pymupdf.open(stream=out, filetype="pdf")
    try:
        assert doc.needs_pass == 0
        assert doc.page_count >= 1
    finally:
        doc.close()


def test_missing_password_raises(enc):
    with pytest.raises(EncryptedFile):
        plain_bytes(enc, None)


def test_wrong_password_raises(enc):
    with pytest.raises(EncryptedFile):
        plain_bytes(enc, "9999")


def test_password_opens_agrees(enc):
    assert password_opens(enc, "1234") is True
    assert password_opens(enc, "9999") is False
    assert password_opens(SAMPLE.read_bytes(), "anything") is True
