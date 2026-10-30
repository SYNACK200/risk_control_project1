"""AL-43 跨引擎不一致逐笔排查。

自检 S4 只给「94/102 笔可定位」这类总数，本脚本把不一致的每一笔摊开，回答
「是 pdfplumber 把字符顺序打乱了，还是该行真的少了字符」。

判据（只用原文事实）：
1. pdfplumber 按 y 聚行、行内按 x 排序后，金额数字仍是行内数字的子序列
   → 切分差异（字符交错，数字齐全）；
2. 行内数字不齐 → 抽取错误（该行缺字符）。

用法：python algorithm/diagnose_s4.py <pdf路径> [--password 口令] [--template 模板json]
"""
from __future__ import annotations

import argparse
import io
import json
import pathlib
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pdfplumber
import pymupdf

from algorithm.algo.self_check import _norm, _page_text, _plumber_page_texts
from algorithm.ocr.models import Template
from algorithm.ocr.parse import parse

DIGITS = str.maketrans("", "", "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _token(amount) -> str:
    return _norm(format(Decimal(str(amount)), "f")).lstrip("+")


def _digits(text: str) -> str:
    return "".join(ch for ch in text if ch.isdigit())


def _cell_text(page, bbox, pad: float = 1.0) -> str:
    """取落在该笔 bbox 内的 pdfplumber 字符，按 x0 排序拼回。"""
    if not bbox:
        return ""
    x0, y0, x1, y1 = bbox
    chars = [
        c
        for c in page.chars
        if c["x0"] >= x0 - pad
        and c["x1"] <= x1 + pad
        and c["top"] >= y0 - pad
        and c["bottom"] <= y1 + pad
    ]
    return "".join(c["text"] for c in sorted(chars, key=lambda c: c["x0"]))


def _page_slice(pages: list[str], page_no: int | None) -> str:
    idx = min(max((page_no or 1) - 1, 0), len(pages) - 1)
    return pages[idx]


def classify(token: str, txn, texts: list[str], plumber: list[str], pages) -> tuple[str, str]:
    page_no = getattr(txn, "page_no", None)
    mine = _page_slice(texts, page_no)
    other = _page_slice(plumber, page_no)

    if token not in mine:
        return "抽取错误", "PyMuPDF 该页也没有该金额，解析值不是从本页取到的"
    if token in other:
        return "一致", "两引擎页文本都含该金额"

    page = pages[min(max((page_no or 1) - 1, 0), len(pages) - 1)]
    row = _cell_text(page, getattr(txn, "bbox", None))
    if not row:
        return "抽取错误", "该笔 bbox 内没有 pdfplumber 字符"

    hit = token if token in row else token.lstrip("+-") if token.lstrip("+-") in row else ""
    if hit:
        pos = row.find(hit)
        return "切分差异", f"同一行按 x 重排后金额连续出现：「…{row[max(pos - 10, 0): pos + len(hit) + 20]}…」"

    if sorted(_digits(row)) == sorted(_digits(token)):
        return "切分差异", "行内数字与解析值一致，仅字符顺序被打乱"

    return "抽取错误", f"行内找不到该金额，实际内容「{row[:60]}」"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--password", default=None)
    ap.add_argument("--template", default=None)
    a = ap.parse_args()

    src = pathlib.Path(a.path)
    if not src.exists():
        print(f"文件不存在：{src}", file=sys.stderr)
        return 2

    raw = src.read_bytes()
    doc = pymupdf.open(stream=raw, filetype="pdf")
    if doc.needs_pass:
        if not a.password or doc.authenticate(a.password) <= 0:
            print("PDF 需要口令或口令错误", file=sys.stderr)
            return 3
        tmp = pathlib.Path(tempfile.gettempdir()) / f"plain_{src.stem}.pdf"
        doc.save(tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
        raw = tmp.read_bytes()

    tpl = None
    if a.template:
        data = json.loads(pathlib.Path(a.template).read_text(encoding="utf-8"))
        tpl = Template(
            bank_code=data.get("bank_code", "UNKNOWN"),
            version=data.get("version", 1),
            field_map=data["field_map"],
        )

    parsed = parse(raw, tpl)
    texts = _page_text(raw)
    plumber = _plumber_page_texts(raw, len(texts))
    with pdfplumber.open(io.BytesIO(raw)) as pdf:
        pages = list(pdf.pages[: len(texts)])

    found = []
    for index, txn in enumerate(parsed.transactions):
        amount = getattr(txn, "amount", None)
        if amount is None:
            continue
        token = _token(amount)
        kind, why = classify(token, txn, texts, plumber, pages)
        if kind == "一致":
            continue
        found.append(
            {
                "序号": index + 1,
                "页": getattr(txn, "page_no", None),
                "行": getattr(txn, "row_no", None),
                "日期": str(getattr(txn, "txn_date", "") or ""),
                "金额": token,
                "余额": None if getattr(txn, "balance", None) is None else str(txn.balance),
                "方向": getattr(txn, "direction", None),
                "定性": kind,
                "依据": why,
            }
        )

    tally: dict[str, int] = {}
    for row in found:
        tally[row["定性"]] = tally.get(row["定性"], 0) + 1

    print(f"文件：{src.name}｜页数 {len(texts)}｜明细 {len(parsed.transactions)} 笔｜S4 不一致 {len(found)} 笔")
    print(f"定性汇总：{tally or '无不一致'}")
    for row in found:
        print(
            f"  第 {row['序号']} 笔｜第 {row['页']} 页 行 {row['行']}｜{row['日期']}｜"
            f"{row['方向']} {row['金额']}｜余额 {row['余额']}｜{row['定性']}：{row['依据']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
