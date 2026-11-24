"""模板智能字段分析引擎：短字段（就近匹配）+ 标题字段（版式分析）。

面向银行后台人员：只需上传样例流水 PDF 并输入两类目标字段：
1. 短字段（short_fields）：如卡号、户名、开户行、起止日期、币种等页眉/单值信息；
   采用「锚点词定位 + 同行右侧/正下方就近匹配」提取键值与归一化坐标框（meta_boxes）。
2. 标题字段（header_fields）：如交易日期、摘要、发生额、余额、对方户名等明细列；
   采用「表头行评分定位 + 相邻列间隙切分 + 数据行投影校正」自动产出表格区、表头线、
   列带坐标（layout.tables）与结构化试解析预览行。

优先使用 PyMuPDF（生产高性能），环境缺少 PyMuPDF 时自动回退 pdfplumber（零外网依赖）。
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0


@dataclass
class _Line:
    words: list[_Word]
    top: float
    bottom: float

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2.0

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


_TRADITIONAL_BANK_HINTS: list[tuple[str, str]] = [
    ("中国工商银行", "ICBC"),
    ("工商银行", "ICBC"),
    ("中国建设银行", "CCB"),
    ("建设银行", "CCB"),
    ("招商银行", "CMB"),
    ("中国农业银行", "ABC"),
    ("农业银行", "ABC"),
    ("中国银行", "BOC"),
    ("交通银行", "BCM"),
    ("广发银行", "CGB"),
    ("邮储银行", "PSBC"),
    ("邮政储蓄", "PSBC"),
    ("浦发银行", "SPDB"),
    ("平安银行", "PAB"),
    ("光大银行", "CEB"),
    ("中信银行", "CITIC"),
    ("兴业银行", "CIB"),
    ("民生银行", "CMBC"),
]

_THIRD_PARTY_HINTS: list[tuple[str, str]] = [
    ("微信支付", "WECHAT"),
    ("支付宝", "ALIPAY"),
]

_FOOTER_RE = re.compile(r"(?:本页(?:支出|收入|交易|合计)|合计|总计|共\s*\d+\s*笔|第\s*\d+\s*页|打印时间|下单时间)")
_DATE_LIKE_RE = re.compile(r"(?:20\d{2}[-/年.]\d{1,2}[-/月.]\d{1,2}|(?<!\d)20\d{6}(?!\d))")
_MONEY_LIKE_RE = re.compile(r"[-+]?[¥￥]?\d[\d,]*\.\d{2}")


def _norm(text: str) -> str:
    trans = str.maketrans({"（": "(", "）": ")", "／": "/", "：": ":", "　": " "})
    return "".join(str(text or "").translate(trans).split()).lower()


def _split_keywords(raw: str | list[str] | None) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        items = raw
    else:
        items = re.split(r"[,，、/|;；\n]+", str(raw))
    out: list[str] = []
    for item in items:
        s = str(item or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _one_edit_apart(a: str, b: str) -> bool:
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la > lb:
        a, b, la, lb = b, a, lb, la
    i = 0
    while i < la and a[i] == b[i]:
        i += 1
    if la == lb:
        return a[i + 1:] == b[i + 1:]
    return a[i:] == b[i + 1:]


def _group_lines(words: list[_Word], y_tol: float = 3.5) -> list[_Line]:
    lines: list[_Line] = []
    for w in sorted(words, key=lambda item: (item.cy, item.x0)):
        if lines and abs(w.cy - lines[-1].cy) <= y_tol:
            lines[-1].words.append(w)
            lines[-1].top = min(lines[-1].top, w.top)
            lines[-1].bottom = max(lines[-1].bottom, w.bottom)
        else:
            lines.append(_Line(words=[w], top=w.top, bottom=w.bottom))
    for ln in lines:
        ln.words.sort(key=lambda item: item.x0)
    return lines


def _merge_close_words(words: list[_Word], gap: float = 2.5) -> list[_Word]:
    merged: list[_Word] = []
    for w in words:
        if merged and (w.x0 - merged[-1].x1) <= gap:
            prev = merged[-1]
            merged[-1] = _Word(
                text=prev.text + w.text,
                x0=prev.x0,
                x1=max(prev.x1, w.x1),
                top=min(prev.top, w.top),
                bottom=max(prev.bottom, w.bottom),
            )
        else:
            merged.append(w)
    return merged


def _merge_spaced_labels(words: list[_Word], max_gap: float = 14.0) -> list[_Word]:
    """合并被空格或字体拆开的短中文标签（如 '户'+'名：' 或 '开户'+'行：XXX' → '开户行：XXX'）。"""
    if len(words) < 2:
        return words
    out: list[_Word] = []
    for w in words:
        head = re.split(r"[:：]", w.text, maxsplit=1)[0]
        if (
            out
            and ":" not in out[-1].text
            and "：" not in out[-1].text
            and w.x0 - out[-1].x1 <= max_gap
            and len(out[-1].text) <= 2
            and len(head) <= 2
            and any("\u4e00" <= ch <= "\u9fff" for ch in out[-1].text)
            and any("\u4e00" <= ch <= "\u9fff" for ch in head)
        ):
            prev = out[-1]
            out[-1] = _Word(
                text=prev.text + w.text,
                x0=prev.x0,
                x1=max(prev.x1, w.x1),
                top=min(prev.top, w.top),
                bottom=max(prev.bottom, w.bottom),
            )
        else:
            out.append(w)
    return out


def _is_image_bytes(raw: bytes) -> bool:
    return raw.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"RIFF"))


def _ocr_fallback_pages(
    raw: bytes,
    page_indices: list[int],
    password: str | None = None,
) -> dict[int, tuple[list[_Word], tuple[float, float], str]]:
    """对无文字层 PDF 页或图片使用 RapidOCR（ocr_words）取词，保持坐标系与页面尺寸一致。"""
    from rc_platform.capabilities.layout import ocr_words  # noqa: PLC0415

    ocr_list = ocr_words.read_pages_via_ocr(raw, dpi=180, password=password, page_indices=page_indices)
    out: dict[int, tuple[list[_Word], tuple[float, float], str]] = {}
    for pw in ocr_list:
        ws = [
            _Word(text=w.text.strip(), x0=float(w.x0), x1=float(w.x1), top=float(w.top), bottom=float(w.bottom))
            for w in pw.words
            if str(w.text or "").strip()
        ]
        txt = " ".join(w.text for w in ws)
        out[pw.page_no] = (ws, (float(pw.width), float(pw.height)), txt)
    return out


def _extract_table_col_hints_fitz(pg) -> list[list[tuple[float, float]]]:
    """用 PyMuPDF find_tables() 提取显式表格线的列边界提示。"""
    try:
        finder = pg.find_tables()
        tables = getattr(finder, "tables", None) or []
    except Exception:  # noqa: BLE001
        return []
    out: list[list[tuple[float, float]]] = []
    for tb in tables:
        try:
            cells = getattr(tb, "cells", None) or []
            if not cells:
                continue
            # 收集每个单元格的 (x0, x1) 形成去重列边界
            col_ranges = sorted({(round(float(c[0]), 1), round(float(c[2]), 1)) for c in cells if len(c) >= 4})
            if len(col_ranges) >= 3:
                out.append(col_ranges)
        except Exception:  # noqa: BLE001
            continue
    return out


def _extract_pdf_words(
    raw: bytes,
    password: str | None = None,
    max_pages: int = 3,
) -> tuple[list[list[_Word]], list[tuple[float, float]], int, str, dict[str, Any]]:
    """抽取前 max_pages 页词坐标、表格列线提示与整页文本；支持 PDF、加密 PDF、扫描 PDF 与图片。"""
    if _is_image_bytes(raw):
        ocr_map = _ocr_fallback_pages(raw, [0], password=None)
        if 0 not in ocr_map or not ocr_map[0][0]:
            raise ValueError("图片未识别出可用文字，请确认图片清晰度或改用标准流水 PDF")
        ws, size, txt = ocr_map[0]
        return [ws], [size], 1, txt, {"ocr_used": True, "engine": "rapidocr_image", "table_hints": [[]]}

    if raw[:4] != b"%PDF":
        raise ValueError("不支持的文件格式，请上传 PDF 或 JPG/PNG 图片流水")

    # 1. 优先尝试 PyMuPDF + find_tables()
    try:
        import pymupdf  # noqa: PLC0415

        doc = pymupdf.open(stream=raw, filetype="pdf")
        try:
            if doc.needs_pass:
                if not password or doc.authenticate(password) <= 0:
                    raise PermissionError("PDF 受口令保护，请提供正确的打开口令")
            total_pages = doc.page_count
            pages_words: list[list[_Word]] = []
            page_sizes: list[tuple[float, float]] = []
            full_texts: list[str] = []
            table_hints: list[list[list[tuple[float, float]]]] = []
            need_ocr: list[int] = []
            for idx in range(min(total_pages, max_pages)):
                pg = doc[idx]
                mtx = pg.rotation_matrix
                ws: list[_Word] = []
                for x0, y0, x1, y1, tx, *_rest in pg.get_text("words"):
                    t = tx.strip()
                    if not t:
                        continue
                    r = pymupdf.Rect(x0, y0, x1, y1) * mtx
                    ws.append(_Word(text=t, x0=float(r.x0), x1=float(r.x1), top=float(r.y0), bottom=float(r.y1)))
                pages_words.append(ws)
                page_sizes.append((float(pg.rect.width), float(pg.rect.height)))
                full_texts.append(pg.get_text("text") or "")
                table_hints.append(_extract_table_col_hints_fitz(pg))
                if len(ws) < 6:
                    need_ocr.append(idx)
        finally:
            doc.close()

        ocr_used = False
        if need_ocr:
            try:
                ocr_map = _ocr_fallback_pages(raw, need_ocr, password=password)
                for idx, (ows, osize, otxt) in ocr_map.items():
                    if ows and idx < len(pages_words):
                        # 将像素坐标按目标页面尺寸缩放对齐（若存在页面尺寸则归一化到点坐标）
                        pw, ph = page_sizes[idx]
                        ow, oh = osize
                        sx = (pw / ow) if (pw > 0 and ow > 0) else 1.0
                        sy = (ph / oh) if (ph > 0 and oh > 0) else 1.0
                        pages_words[idx] = [
                            _Word(text=w.text, x0=w.x0 * sx, x1=w.x1 * sx, top=w.top * sy, bottom=w.bottom * sy)
                            for w in ows
                        ]
                        full_texts[idx] = otxt
                        ocr_used = True
            except Exception:  # noqa: BLE001 - OCR 不可用时保留原文
                pass

        return (
            pages_words,
            page_sizes,
            total_pages,
            "\n".join(full_texts),
            {"ocr_used": ocr_used, "engine": "rapidocr+pymupdf" if ocr_used else "pymupdf+tables", "table_hints": table_hints},
        )
    except ImportError:
        pass

    # 2. 回退 pdfplumber
    import pdfplumber  # noqa: PLC0415

    try:
        with pdfplumber.open(io.BytesIO(raw), password=password or "") as pdf:
            total_pages = len(pdf.pages)
            pages_words = []
            page_sizes = []
            full_texts = []
            for idx in range(min(total_pages, max_pages)):
                pg = pdf.pages[idx]
                raw_ws = pg.extract_words(x_tolerance=2.0, y_tolerance=2.5, keep_blank_chars=False) or []
                ws = [
                    _Word(
                        text=str(w["text"]).strip(),
                        x0=float(w["x0"]),
                        x1=float(w["x1"]),
                        top=float(w["top"]),
                        bottom=float(w["bottom"]),
                    )
                    for w in raw_ws
                    if str(w.get("text") or "").strip()
                ]
                pages_words.append(ws)
                page_sizes.append((float(pg.width), float(pg.height)))
                full_texts.append(pg.extract_text() or "")
            return (
                pages_words,
                page_sizes,
                total_pages,
                "\n".join(full_texts),
                {"ocr_used": False, "engine": "pdfplumber", "table_hints": [[] for _ in pages_words]},
            )
    except Exception as exc:  # noqa: BLE001
        if "password" in str(exc).lower() or "encrypt" in str(exc).lower():
            raise PermissionError("PDF 受口令保护，请提供正确的打开口令") from exc
        raise


def _detect_bank(
    full_text: str,
    header_text: str = "",
    filename: str | None = None,
) -> tuple[str | None, str | None]:
    """优先从页眉与正文识别传统银行，其次参考文件名；微信/支付宝仅限页眉或文件名命中，避免被明细摘要误导。"""
    top_text = header_text or full_text[:260]
    fname = filename or ""
    for scope in (top_text, full_text, fname):
        if not scope:
            continue
        for alias, code in _TRADITIONAL_BANK_HINTS:
            if alias in scope:
                return code, alias
    for scope in (top_text, fname):
        if not scope:
            continue
        for alias, code in _THIRD_PARTY_HINTS:
            if alias in scope:
                return code, alias
    return None, None


def _match_keyword(token_text: str, keywords: list[str]) -> tuple[str, float] | None:
    """判断单个词/短语是否命中关键词列表，返回 (命中的关键词, 匹配得分)。"""
    nt = _norm(token_text)
    if not nt:
        return None
    best: tuple[str, float] | None = None
    for kw in keywords:
        nk = _norm(kw)
        if not nk:
            continue
        if nt == nk:
            return kw, 1.0
        # 去掉末尾冒号后的精确命中（如「户名：」）
        if nt.rstrip(":") == nk:
            return kw, 0.98
        if nk in nt and len(nk) >= 2:
            score = 0.85 if len(nt) <= len(nk) + 6 else 0.72
            if best is None or score > best[1]:
                best = (kw, score)
        elif nt in nk and len(nt) >= 2:
            score = 0.78
            if best is None or score > best[1]:
                best = (kw, score)
        elif len(nk) >= 3 and len(nt) <= len(nk) + 2 and _one_edit_apart(nt, nk):
            score = 0.70
            if best is None or score > best[1]:
                best = (kw, score)
    return best


def _extract_inline_value(text: str, kw: str) -> str | None:
    """处理「户名：张三」「卡号/账号:6217...」「客户名称：刘先生」等标签与值粘连情况。"""
    idx = text.find(kw)
    if idx >= 0:
        rest = text[idx + len(kw):]
        # 若标签后缀还有细分词和冒号（如「卡号/账号:6217...」或「客户名称：刘先生」），取冒号后的纯值
        m_after = re.search(r"^[^:：]{0,8}[:：]\s*(.+)$", rest)
        if m_after and m_after.group(1).strip():
            return m_after.group(1).strip()
        stripped = rest.lstrip(" :：")
        if stripped:
            return stripped
    # 回退：未直接定位到 kw（如 1-edit 模糊命中），从最后一个冒号后取非时间戳文本
    m = re.search(r"[:：]\s*([^:：]+)$", text)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return None


def _analyze_page_headers(
    words: list[_Word],
    pw: float,
    ph: float,
    header_fields: list[dict[str, Any]],
    *,
    col_hints: list[list[tuple[float, float]]] | None = None,
    page_no: int = 0,
    slot: str = "first",
) -> dict[str, Any]:
    """对单页做标题字段版式分析：合并拆字 + 表头定位 + 表格线/间隙切分 + 数据行投影。"""
    lines = _group_lines(words, y_tol=3.5)

    best_line: _Line | None = None
    best_tokens: list[_Word] = []
    best_matches: dict[int, tuple[dict[str, Any], str, float]] = {}
    best_score = 0.0

    for ln in lines[:30]:
        tokens = _merge_close_words(ln.words, gap=3.0)
        line_matches: dict[int, tuple[dict[str, Any], str, float]] = {}
        used_fields: set[str] = set()
        score_sum = 0.0
        for t_idx, tok in enumerate(tokens):
            best_f: tuple[dict[str, Any], str, float] | None = None
            for hf in header_fields:
                fkey = str(hf.get("field") or "").strip()
                if not fkey or fkey in used_fields:
                    continue
                kws = _split_keywords(hf.get("keywords") or hf.get("label") or fkey)
                hit = _match_keyword(tok.text, kws)
                if hit and (best_f is None or hit[1] > best_f[2]):
                    best_f = (hf, hit[0], hit[1])
            if best_f is not None:
                line_matches[t_idx] = best_f
                used_fields.add(str(best_f[0]["field"]))
                score_sum += best_f[2]
        if len(line_matches) >= 2 and score_sum > best_score:
            best_score = score_sum
            best_line = ln
            best_tokens = tokens
            best_matches = line_matches

    if best_line is None or not best_matches:
        return {
            "header_found": False,
            "header_results": [
                {
                    "field": str(hf.get("field") or ""),
                    "label": str(hf.get("label") or hf.get("field") or ""),
                    "keywords": _split_keywords(hf.get("keywords") or hf.get("label")),
                    "matched": False,
                    "header_text": None,
                    "x": None,
                    "w": None,
                    "sample_values": [],
                    "hit_rows": 0,
                    "confidence": 0.0,
                }
                for hf in header_fields
            ],
            "table_area": None,
            "preview_rows": [],
            "field_map": {},
            "table_layout": None,
            "header_y_pt": None,
        }

    # 结合 PyMuPDF find_tables() 显式格子线（若命中同一行多列表格），否则退回整行相邻间隙切分
    flat_hints: list[tuple[float, float]] = []
    if col_hints:
        best_group = max(col_hints, key=len)
        flat_hints = best_group

    tok_bounds: list[tuple[float, float]] = []
    n_tok = len(best_tokens)
    for i, tok in enumerate(best_tokens):
        tw = max(tok.x1 - tok.x0, 12.0)
        if i == 0:
            left = max(0.0, tok.x0 - 0.25 * tw)
        else:
            left = (best_tokens[i - 1].x1 + tok.x0) / 2.0
        if i == n_tok - 1:
            right = min(pw, tok.x1 + 0.6 * tw)
        else:
            right = (tok.x1 + best_tokens[i + 1].x0) / 2.0
        # 若显式表格边框覆盖此表头中心，优先对齐表格纵线边界（防跨列串字）
        for hx0, hx1 in flat_hints:
            if hx0 <= tok.cx <= hx1 and (hx1 - hx0) >= 12.0 and (hx1 - hx0) <= pw * 0.48:
                left, right = max(0.0, hx0), min(pw, hx1)
                break
        if right <= left:
            left, right = tok.x0, max(tok.x1, tok.x0 + 12.0)
        tok_bounds.append((left, right))

    header_top = best_line.top
    header_bottom = best_line.bottom
    data_lines: list[_Line] = []
    last_data_bottom = header_bottom + 20.0

    for ln in lines:
        if ln.top <= header_bottom + 1.0:
            continue
        txt = ln.text.strip()
        if not txt:
            continue
        if _FOOTER_RE.search(txt) and not _DATE_LIKE_RE.search(txt):
            break
        data_lines.append(ln)
        last_data_bottom = max(last_data_bottom, ln.bottom)

    field_map: dict[str, str] = {}
    col_specs: list[tuple[str, float, float, str, float]] = []

    for t_idx in sorted(best_matches.keys()):
        hf, _kw, conf = best_matches[t_idx]
        fkey = str(hf["field"]).strip()
        tok = best_tokens[t_idx]
        left, right = tok_bounds[t_idx]
        col_specs.append((fkey, left, right, tok.text, conf))
        field_map[fkey] = tok.text

    samples_by_field: dict[str, list[str]] = {f: [] for f, *_ in col_specs}
    hits_by_field: dict[str, int] = {f: 0 for f, *_ in col_specs}
    preview_rows: list[dict[str, Any]] = []

    for ln in data_lines:
        row_cells: dict[str, str] = {}
        for fkey, left, right, _ht, _cf in col_specs:
            cell_ws = [w for w in ln.words if left <= w.cx < right]
            if cell_ws:
                val = " ".join(w.text for w in cell_ws).strip()
                if val:
                    row_cells[fkey] = val
                    hits_by_field[fkey] += 1
                    if len(samples_by_field[fkey]) < 4 and val not in samples_by_field[fkey]:
                        samples_by_field[fkey].append(val)
        if len(row_cells) >= 2 and len(preview_rows) < 15:
            preview_rows.append({"page_no": page_no + 1, "cells": row_cells})

    matched_by_field = {f: (left, right, ht, cf) for f, left, right, ht, cf in col_specs}
    header_results: list[dict[str, Any]] = []
    layout_columns: list[dict[str, Any]] = []

    for hf in header_fields:
        fkey = str(hf.get("field") or "").strip()
        flabel = str(hf.get("label") or fkey)
        kws = _split_keywords(hf.get("keywords") or flabel)
        if fkey in matched_by_field:
            left, right, ht, conf = matched_by_field[fkey]
            nx = round(max(0.0, left / pw), 4)
            nw = round(min(1.0 - nx, max(0.02, (right - left) / pw)), 4)
            header_results.append({
                "field": fkey,
                "label": flabel,
                "keywords": kws,
                "matched": True,
                "header_text": ht,
                "x": nx,
                "w": nw,
                "sample_values": samples_by_field.get(fkey, [])[:3],
                "hit_rows": hits_by_field.get(fkey, 0),
                "confidence": round(conf, 2),
            })
            layout_columns.append({
                "field": fkey,
                "fields": [fkey],
                "label": flabel,
                "header_text": ht,
                "x": nx,
                "w": nw,
            })
        else:
            header_results.append({
                "field": fkey,
                "label": flabel,
                "keywords": kws,
                "matched": False,
                "header_text": None,
                "x": None,
                "w": None,
                "sample_values": [],
                "hit_rows": 0,
                "confidence": 0.0,
            })

    layout_columns.sort(key=lambda c: c["x"])
    area_x = round(max(0.0, min(b[0] for b in tok_bounds) / pw - 0.005), 4)
    area_x1 = round(min(1.0, max(b[1] for b in tok_bounds) / pw + 0.005), 4)
    area_y = round(max(0.0, (header_top - 3.0) / ph), 4)
    area_y1 = round(min(0.98, (last_data_bottom + 6.0) / ph), 4)
    header_y_norm = round(min(area_y1, max(area_y, (header_bottom + 1.0) / ph)), 4)

    table_area = {
        "x": area_x,
        "y": area_y,
        "w": round(max(0.05, area_x1 - area_x), 4),
        "h": round(max(0.05, area_y1 - area_y), 4),
        "headerY": header_y_norm,
    }
    table_layout = {
        "page": page_no,
        "slot": slot,
        "area": {k: table_area[k] for k in ("x", "y", "w", "h")},
        "headerY": header_y_norm,
        "columns": layout_columns,
    }
    return {
        "header_found": True,
        "header_results": header_results,
        "table_area": table_area,
        "preview_rows": preview_rows,
        "field_map": field_map,
        "table_layout": table_layout,
        "header_y_pt": header_top,
    }


def analyze_header_fields(
    pages_words: list[list[_Word]],
    page_sizes: list[tuple[float, float]],
    header_fields: list[dict[str, Any]],
    *,
    table_hints: list[list[list[tuple[float, float]]]] | None = None,
) -> dict[str, Any]:
    """标题字段版式分析：定位首页与续页表头、融合表格边框与间隙切分列并输出预览。"""
    if not pages_words or not header_fields:
        return {
            "header_found": False,
            "header_results": [],
            "table_area": None,
            "preview_rows": [],
            "field_map": {},
            "table_layout": None,
            "extra_tables": [],
            "header_y_pt": None,
        }

    first = _analyze_page_headers(
        pages_words[0],
        page_sizes[0][0],
        page_sizes[0][1],
        header_fields,
        col_hints=(table_hints[0] if table_hints else None),
        page_no=0,
        slot="first",
    )
    extra_tables: list[dict[str, Any]] = []
    if first["header_found"] and len(pages_words) > 1:
        base_hy = float((first["table_layout"] or {}).get("headerY") or 0)
        for p_idx in range(1, min(len(pages_words), 3)):
            if not pages_words[p_idx]:
                continue
            sub = _analyze_page_headers(
                pages_words[p_idx],
                page_sizes[p_idx][0],
                page_sizes[p_idx][1],
                header_fields,
                col_hints=(table_hints[p_idx] if table_hints and p_idx < len(table_hints) else None),
                page_no=p_idx,
                slot="middle",
            )
            if sub["header_found"] and sub["table_layout"]:
                sub_hy = float(sub["table_layout"].get("headerY") or 0)
                if abs(sub_hy - base_hy) >= 0.04 or p_idx == 1:
                    extra_tables.append(sub["table_layout"])
                    break
    first["extra_tables"] = extra_tables
    return first


_STD_HEADER_KEYS = {
    "txn_date", "trade_time", "reference_no", "summary", "counterparty", "counterparty_name",
    "direction", "amount", "amount_in", "amount_out", "balance", "currency", "channel", "account_no",
}
_STD_SHORT_KEYS = {
    "account_no", "account_name", "bank_branch", "account_type", "period", "currency",
}


def _scan_short_field(
    sf: dict[str, Any],
    lines: list[_Line],
    pw: float,
    ph: float,
    all_stop_kws: list[str],
    page_no: int = 0,
) -> tuple[float, dict[str, Any], dict[str, Any]] | None:
    fkey = str(sf.get("field") or "").strip()
    flabel = str(sf.get("label") or fkey)
    kws = _split_keywords(sf.get("keywords") or flabel)
    best_candidate: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    _title_noise = ("明细", "流水", "证明", "清单", "对账单")

    for ln_idx, ln in enumerate(lines):
        prep_words = _merge_spaced_labels(ln.words, max_gap=14.0)
        for w_idx, w in enumerate(prep_words):
            hit = _match_keyword(w.text, kws)
            if not hit:
                continue
            kw_hit, conf = hit
            has_colon = (":" in w.text) or ("：" in w.text)
            if not has_colon and any(t in w.text for t in _title_noise) and len(w.text) >= len(kw_hit) + 4:
                continue
            inline_val = _extract_inline_value(w.text, kw_hit)
            val_words: list[_Word] = [w]
            method = "inline"

            if inline_val:
                right_extra: list[str] = [inline_val]
                prev_x1 = w.x1
                for nw in prep_words[w_idx + 1:]:
                    if nw.x0 - prev_x1 > 28.0:
                        break
                    if _match_keyword(nw.text, [k for k in all_stop_kws if k not in kws]):
                        break
                    val_words.append(nw)
                    right_extra.append(nw.text)
                    prev_x1 = nw.x1
                value = " ".join(right_extra).strip()
            else:
                method = "right_neighbor"
                collected: list[_Word] = []
                prev_x1 = w.x1
                for nw in prep_words[w_idx + 1:]:
                    if nw.text in (":", "："):
                        prev_x1 = nw.x1
                        continue
                    gap_limit = 90.0 if not collected else 28.0
                    if nw.x0 - prev_x1 > gap_limit:
                        break
                    if _match_keyword(nw.text, [k for k in all_stop_kws if k not in kws]):
                        break
                    collected.append(nw)
                    prev_x1 = nw.x1
                if collected:
                    val_words = collected
                    value = " ".join(x.text for x in collected).strip()
                else:
                    method = "below_neighbor"
                    below_ws: list[_Word] = []
                    if ln_idx + 1 < len(lines):
                        next_ln = lines[ln_idx + 1]
                        if 0 <= next_ln.top - ln.bottom <= 24.0:
                            below_ws = [
                                bw for bw in next_ln.words
                                if bw.x1 >= w.x0 - 15.0 and bw.x0 <= w.x1 + 60.0
                            ]
                    if below_ws:
                        val_words = below_ws
                        value = " ".join(x.text for x in below_ws).strip()
                    else:
                        value = w.text

            x0 = min(x.x0 for x in val_words)
            y0 = min(x.top for x in val_words)
            x1 = max(x.x1 for x in val_words)
            y1 = max(x.bottom for x in val_words)
            if method == "inline" and inline_val and len(w.text) > len(inline_val):
                # 尽量将边框收缩到值区域起点，避免整段标签被圈进框内
                label_ratio = max(0.0, min(0.75, 1.0 - len(inline_val) / max(1, len(w.text))))
                x0 = min(w.x1 - 8.0, w.x0 + (w.x1 - w.x0) * label_ratio * 0.85)
            rect = {
                "x": round(max(0.0, x0 / pw), 4),
                "y": round(max(0.0, y0 / ph), 4),
                "w": round(min(1.0 - max(0.0, x0 / pw), max(0.02, (x1 - x0) / pw)), 4),
                "h": round(min(1.0 - max(0.0, y0 / ph), max(0.015, (y1 - y0) / ph)), 4),
            }
            cand_score = conf + (0.25 if has_colon else 0.0)
            if method == "inline" and has_colon:
                cand_score += 0.20
            elif method == "right_neighbor":
                cand_score += 0.15
            elif method == "below_neighbor":
                cand_score += 0.05
            cand_item = {
                "field": fkey,
                "label": flabel,
                "keywords": kws,
                "matched": True,
                "anchor_text": w.text,
                "value": value,
                "page": page_no,
                "rect": rect,
                "method": method,
                "confidence": round(min(1.0, conf), 2),
            }
            cand_box = {
                "field": fkey,
                "label": flabel,
                "value": value,
                "page": page_no,
                **rect,
            }
            if best_candidate is None or cand_score > best_candidate[0]:
                best_candidate = (cand_score, cand_item, cand_box)
    return best_candidate


def match_short_fields(
    pages_words: list[list[_Word]],
    page_sizes: list[tuple[float, float]],
    short_fields: list[dict[str, Any]],
    header_y_pt: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """短字段就近匹配：先在首页页眉定位，未命中时兜底扫描首页页尾及全页。"""
    if not pages_words or not short_fields:
        return [], []

    words0 = pages_words[0]
    pw, ph = page_sizes[0]
    zone_words = [w for w in words0 if header_y_pt is None or w.bottom <= header_y_pt + 4.0]
    header_lines = _group_lines(zone_words or words0, y_tol=4.5)
    # 兜底全页扫描时排除明细表头行本身（避免把表格列名「币种」「交易日期」误当独立短字段）
    fallback_words = (
        [w for w in words0 if w.bottom < header_y_pt - 2.0 or w.top > header_y_pt + 22.0]
        if header_y_pt is not None
        else words0
    )
    full_lines = _group_lines(fallback_words, y_tol=4.5)

    all_stop_kws: list[str] = []
    for sf in short_fields:
        all_stop_kws.extend(_split_keywords(sf.get("keywords") or sf.get("label")))

    results: list[dict[str, Any]] = []
    meta_boxes: list[dict[str, Any]] = []

    for sf in short_fields:
        fkey = str(sf.get("field") or "").strip()
        flabel = str(sf.get("label") or fkey)
        kws = _split_keywords(sf.get("keywords") or flabel)
        best = _scan_short_field(sf, header_lines, pw, ph, all_stop_kws, page_no=0)
        if best is None and header_y_pt is not None:
            best = _scan_short_field(sf, full_lines, pw, ph, all_stop_kws, page_no=0)
        if best:
            results.append(best[1])
            meta_boxes.append(best[2])
        else:
            results.append({
                "field": fkey,
                "label": flabel,
                "keywords": kws,
                "matched": False,
                "anchor_text": None,
                "value": None,
                "page": 0,
                "rect": None,
                "method": None,
                "confidence": 0.0,
            })

    return results, meta_boxes


def analyze_template_fields(
    raw: bytes,
    short_fields: list[dict[str, Any]],
    header_fields: list[dict[str, Any]],
    *,
    password: str | None = None,
    bank_code: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """端到端模板智能分析：标题字段多页版式分析 + 短字段全页就近匹配 + OCR/真实解析兜底。"""
    pages_words, page_sizes, page_count, full_text, meta_info = _extract_pdf_words(
        raw, password=password, max_pages=3,
    )
    hdr_out = analyze_header_fields(
        pages_words,
        page_sizes,
        header_fields,
        table_hints=meta_info.get("table_hints"),
    )

    header_y_pt = hdr_out["header_y_pt"]
    if pages_words and header_y_pt is not None:
        header_text = " ".join(w.text for w in pages_words[0] if w.bottom <= header_y_pt + 4.0)
    else:
        header_text = full_text[:260]
    detected_code, detected_name = _detect_bank(full_text, header_text=header_text, filename=filename)
    final_bank = (bank_code or detected_code or "UNKNOWN").strip().upper()
    short_results, meta_boxes = match_short_fields(
        pages_words, page_sizes, short_fields, header_y_pt=hdr_out["header_y_pt"],
    )

    pw, ph = page_sizes[0] if page_sizes else (595.0, 842.0)
    tables: list[dict[str, Any]] = []
    if hdr_out["table_layout"]:
        tables.append(hdr_out["table_layout"])
    tables.extend(hdr_out.get("extra_tables") or [])

    header_sig = "|".join(
        str(c.get("header_text") or c.get("label") or "")
        for c in ((tables[0].get("columns") or []) if tables else [])
    )
    layout_hash = hashlib.sha256(header_sig.encode("utf-8")).hexdigest()[:16] if header_sig else ""

    custom_fields: list[dict[str, str]] = []
    seen_cf: set[str] = set()
    for hf in header_fields:
        fk = str(hf.get("field") or "").strip()
        if fk and fk not in _STD_HEADER_KEYS and fk not in seen_cf:
            seen_cf.add(fk)
            custom_fields.append({"key": fk, "label": str(hf.get("label") or fk), "kind": "header"})
    for sf in short_fields:
        fk = str(sf.get("field") or "").strip()
        if fk and fk not in _STD_SHORT_KEYS and fk not in seen_cf:
            seen_cf.add(fk)
            custom_fields.append({"key": fk, "label": str(sf.get("label") or fk), "kind": "short"})

    layout = {
        "page_size": {"w": round(pw, 1), "h": round(ph, 1)},
        "page_count": page_count,
        "page_base": 0,
        **({"layout_hash": layout_hash} if layout_hash else {}),
        "tables": tables,
        "meta_boxes": meta_boxes,
        **({"custom_fields": custom_fields} if custom_fields else {}),
    }

    return {
        "bank_code": final_bank,
        "bank_name": detected_name,
        "page_count": page_count,
        "page_size": {"w": round(pw, 1), "h": round(ph, 1)},
        "ocr_used": bool(meta_info.get("ocr_used")),
        "engine": meta_info.get("engine") or "pymupdf",
        "header_found": hdr_out["header_found"],
        "short_results": short_results,
        "header_results": hdr_out["header_results"],
        "table_area": hdr_out["table_area"],
        "preview_rows": hdr_out["preview_rows"],
        "field_map": hdr_out["field_map"],
        "layout": layout,
    }
