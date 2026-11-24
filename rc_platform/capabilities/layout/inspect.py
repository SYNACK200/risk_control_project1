"""标注用的「扩散报告」：把版面分析的中间结果原样交给人看。

为什么需要它：模板不再记死坐标，只声明「我需要卡号、交易日期、金额」这些列。
系统在新文件上要自己找到它们——先靠关键词定位文字，再靠版面把同一列往下扩。
那这个过程必须可见、可纠正，否则标注员只能盲签。

三个动作：
  inspect(data)            整页扩散：所有被识别出来的列带 + 每条列带下面的单元格
  spread(data, keyword)    单关键词扩散：只按给定的词（如「卡号」）去找位置、往下扩
  cells(...)               给定 x 范围与起始行，取出该列的所有单元格

坐标一律用页面点（pt），前端画布直接用；保存模板时再归一化到 0-1。
"""
from __future__ import annotations

import re

from . import detect, ocr_words
from . import keywords as kw
from .words import Line, PageWords, Word, adaptive_group_lines, merge_tokens, read_pages

MIN_HITS = 2
MAX_MISSES = 12
# 页脚/小计行不能当成数据：它们也在同一列上，但意思是「这一页结束了」
FOOTER_WORDS = ("本页", "合计", "小计", "共计", "以上", "打印", "第", "页码", "制表")
_STRICT_SHAPE_FIELDS = frozenset({"txn_date", "amount", "amount_in", "amount_out", "balance", "direction", "reference_no"})


def _tokens(pages: list[PageWords]) -> list[list[list[Word]]]:
    return [[merge_tokens(line) for line in adaptive_group_lines(page.words)] for page in pages]


def _header_line_index(tokens_per_line: list[list[Word]]) -> int:
    """找表头所在行：前 30 行里，能被认成表头词的 token 最多的那一行。

    不能用「页面前 40% 的行数」当上限：短页面（样例只有 8 行）会把真正的表头切掉，
    于是表头那一行被当成数据，画面上就是「列名也进了第一个红框」。
    """
    limit = min(len(tokens_per_line), 30)
    best_index, best_hits = 0, 0
    for index, tokens in enumerate(tokens_per_line[:limit]):
        hits = 0
        for token in tokens:
            if kw.match_header_field(token.text):
                hits += 1
        if hits > best_hits:
            best_index, best_hits = index, hits
    return best_index if best_hits >= 1 else -1


def _value_like(text: str) -> bool:
    """判断一段文字像不像「值」而不是「另一个表头」。"""
    body = (text or "").strip()
    if not body:
        return False
    digits = sum(1 for ch in body if ch.isdigit())
    if digits == 0:
        return False
    return digits >= 2 or len(body) <= 6


def _cell(word: Word) -> dict:
    return {
        "text": word.text,
        "x0": round(word.x0, 2),
        "x1": round(word.x1, 2),
        "y0": round(word.top, 2),
        "y1": round(word.bottom, 2),
    }


def _collect_cells(
    tokens_per_line: list[list[Word]],
    start: int,
    center: float,
    half: float,
    page_width: float,
    *,
    field: str = "",
    left_limit: float | None = None,
    right_limit: float | None = None,
    end: int | None = None,
) -> list[dict]:
    """从 start 行开始，往下收集中心落在 [center-half, center+half] 的词，按行成组。"""
    cells: list[dict] = []
    misses = 0
    previous_bottom = None
    gaps: list[float] = []
    strict = field in _STRICT_SHAPE_FIELDS
    for tokens in tokens_per_line[start:end]:
        best = None
        distance = None
        for token in tokens:
            delta = abs(token.cx - center)
            if delta > half:
                continue
            if left_limit is not None and token.cx < left_limit:
                continue
            if right_limit is not None and token.cx > right_limit:
                continue
            if distance is None or delta < distance:
                best, distance = token, delta
        if best is None:
            misses += 1
            if misses > MAX_MISSES and cells:
                break
            continue

        # 页脚行：同列但不是数据，遇到就收手（否则「本页交易笔数：3」会变成最后一笔金额）
        if any(word in best.text for word in FOOTER_WORDS):
            break

        if strict and not kw.shape_ok(field, best.text):
            misses += 1
            if misses > MAX_MISSES and cells:
                break
            continue

        # 行距突变：流水表行距稳定，突然空出一大段说明换区了（表格结束了/换页眉了）
        if previous_bottom is not None:
            gap = best.top - previous_bottom
            gaps.append(gap)
            if len(gaps) >= 3:
                median = sorted(gaps)[len(gaps) // 2]
                if median > 0 and gap > median * 3.5:
                    break
        previous_bottom = best.bottom
        cells.append(_cell(best))
        misses = 0
    return cells


def _region_bands(
    page: PageWords,
    tokens_per_line: list[list[Word]],
    region,
    header_hint: int | None = None,
) -> tuple[float | None, int, list[dict]]:
    header_y = region.header_y
    if header_y is not None and header_y <= 1.0:
        header_y = header_y * page.height
    header_index = header_hint if header_hint is not None else _header_line_index(tokens_per_line)
    if header_index >= 0 and header_index < len(tokens_per_line):
        start_row = detect.data_start_after_header(tokens_per_line, header_index)
    else:
        start_row = 0

    ordered_cols = sorted(region.columns, key=lambda c: c.x)
    centers = [(c.x + c.w / 2) * page.width for c in ordered_cols]
    bands: list[dict] = []
    for idx, column in enumerate(ordered_cols):
        x0 = column.x * page.width
        x1 = (column.x + column.w) * page.width
        center = (x0 + x1) / 2
        left_limit = ((centers[idx - 1] + center) / 2 - page.width * 0.008) if idx > 0 else None
        right_limit = ((center + centers[idx + 1]) / 2 + page.width * 0.008) if idx + 1 < len(centers) else None
        cells = _collect_cells(
            tokens_per_line,
            start_row,
            center,
            max((x1 - x0) / 2, page.width * 0.01) + page.width * 0.015,
            page.width,
            field=column.field,
            left_limit=left_limit,
            right_limit=right_limit,
        )
        if cells:
            x0 = min([x0] + [item["x0"] for item in cells])
            x1 = max([x1] + [item["x1"] for item in cells])
        bands.append({
            "field": column.field,
            "source": region.source,
            "confidence": round(column.confidence, 3),
            "x0": round(x0, 2),
            "x1": round(x1, 2),
            "cells": cells,
        })
    return header_y, header_index, bands


def _page_report(index: int, page: PageWords, tokens_per_line: list[list[Word]], regions: list) -> dict:
    header_y = None
    bands: list[dict] = []
    region_reports: list[dict] = []
    header_index = -1

    for r_idx, region in enumerate(regions):
        h_hint = None
        if r_idx > 0 and region.header_y is not None:
            target_y = region.header_y * page.height if region.header_y <= 1.0 else region.header_y
            h_hint = min(
                range(len(tokens_per_line)),
                key=lambda i: abs(tokens_per_line[i][0].top - target_y) if tokens_per_line[i] else 1e9,
                default=None,
            )
        r_hy, r_hidx, r_bands = _region_bands(page, tokens_per_line, region, header_hint=h_hint)
        if r_idx == 0:
            header_y = r_hy
            header_index = r_hidx
            bands = r_bands
        ax, ay, aw, ah = region.area
        region_reports.append({
            "area": {"x": round(ax, 4), "y": round(ay, 4), "w": round(aw, 4), "h": round(ah, 4)},
            "header_y": None if r_hy is None else round(r_hy, 2),
            "bands": r_bands,
        })

    return {
        "index": index,
        "width": round(page.width, 2),
        "height": round(page.height, 2),
        "lines": len(tokens_per_line),
        "header_y": None if header_y is None else round(header_y, 2),
        "header_index": header_index,
        "bands": bands,
        "regions": region_reports,
        "has_text": bool(page.words),
    }


def inspect(
    data: bytes,
    password: str | None = None,
    *,
    ocr_fallback: bool = True,
    ocr_page: int = 0,
) -> dict:
    pages = read_pages(data, password)
    ocr_used = False
    ocr_pages: list[int] = []
    if ocr_fallback and pages:
        target_indices = [ocr_page] if 0 <= ocr_page < len(pages) else [0]
        need_ocr = [idx for idx in target_indices if not pages[idx].has_text]
        if need_ocr:
            try:
                ocr_list = ocr_words.read_pages_via_ocr(
                    data, dpi=150, password=password, page_indices=need_ocr,
                )
                by_no = {p.page_no: p for p in ocr_list}
                pages = [by_no.get(p.page_no, p) for p in pages]
                ocr_used = any(p.has_text for p in ocr_list)
                ocr_pages = [p.page_no for p in ocr_list if p.has_text]
            except Exception:  # noqa: BLE001 - OCR 不可用时不阻塞纯手动框选
                ocr_used = False

    tokens = _tokens(pages)
    reports = []
    for index, page in enumerate(pages):
        try:
            regions = detect.detect_page_regions(page)
        except Exception:  # noqa: BLE001 - 单页识别失败不该让整份样本看不出东西
            regions = []
        report = _page_report(index, page, tokens[index], regions)
        column_fields = {band["field"] for reg in report.get("regions", []) for band in reg["bands"]} or {
            band["field"] for band in report["bands"]
        }
        report["singles"] = _singles(
            index, page, tokens[index], column_fields, header_index=report.get("header_index", -1),
        )
        reports.append(report)
    return {
        "pages": reports,
        "page_count": len(reports),
        "text_layer": any(item["has_text"] for item in reports),
        "ocr_used": ocr_used,
        "ocr_pages": ocr_pages,
    }


def spread(data: bytes, keyword: str, page_index: int | None = None, password: str | None = None) -> dict:
    """按关键词扩散出一列。

    典型用法是「卡号」：它可能出现在表头单元格里（卡号 | 6222…），
    也可能出现在说明行里（卡号：6222…）。两种都要能起步：
      - 同行右侧有值 -> 先收下这个值，再以它的中心往下扩
      - 同行右侧没值 -> 以关键词自己的中心往下扩
    """
    pages = read_pages(data, password)
    if pages:
        if page_index is not None:
            targets = [page_index] if 0 <= page_index < len(pages) and not pages[page_index].has_text else []
        elif not any(p.has_text for p in pages):
            targets = [0]
        else:
            targets = [i for i, p in enumerate(pages) if not p.has_text]
        if targets:
            try:
                ocr_list = ocr_words.read_pages_via_ocr(data, dpi=150, password=password, page_indices=targets)
                by_no = {p.page_no: p for p in ocr_list}
                pages = [by_no.get(p.page_no, p) for p in pages]
            except Exception:  # noqa: BLE001
                pass
    tokens = _tokens(pages)
    hits: list[dict] = []

    for index, page in enumerate(pages):
        if page_index is not None and index != page_index:
            continue
        found = False
        for line_no, tokens_line in enumerate(tokens[index]):
            if found:
                break
            for token in tokens_line:
                if keyword and keyword in token.text:
                    inline = None
                    for other in tokens_line:
                        if other is token or other.cx <= token.cx:
                            continue
                        if other.x0 - token.x1 > page.width * 0.35:
                            continue
                        # 只有「像值」的才当成同行取值：紧邻的往往是下一列表头
                        if not _value_like(other.text):
                            continue
                        inline = other
                        break
                    anchor = inline or token
                    start = line_no if inline is not None else detect.data_start_after_header(tokens[index], line_no)
                    cells = _collect_cells(tokens[index], start,
                                           anchor.cx, page.width * 0.06, page.width)
                    if inline is not None:
                        cells = [_cell(inline)] + cells
                    left = min([anchor.x0] + [item["x0"] for item in cells])
                    right = max([anchor.x1] + [item["x1"] for item in cells])
                    hits.append({
                        "page": index,
                        "width": round(page.width, 2),
                        "height": round(page.height, 2),
                        "keyword": _cell(token),
                        "anchor": _cell(anchor),
                        "x0": round(left, 2),
                        "x1": round(right, 2),
                        "cells": cells,
                        "source": "inline" if inline else "column",
                    })
                    found = True   # 一页一段起步即可，避免同一列被重复扩
                    break

    return {"keyword": keyword, "page_count": len(pages), "bands": hits}

# ---------------------------------------------------------------- 单值字段
# 不是所有要提取的东西都是「列」。卡号、户名、开户行这类属性整份文件只有一个，
# 按列扩散会得到一条只有一格的列带，语义是错的——它们是「页内的一个框」。
SINGLE_LABELS: list[tuple[str, str]] = [
    ("卡号", "account_no"),
    ("账号", "account_no"),
    ("账户号", "account_no"),
    ("户名", "account_name"),
    ("账户名称", "account_name"),
    ("客户名称", "account_name"),
    ("开户行", "bank_branch"),
    ("开户机构", "bank_branch"),
    ("账户类型", "account_type"),
]
SINGLE_FIELD_LABEL = {
    "account_no": "卡号或账号",
    "account_name": "户名",
    "bank_branch": "开户行",
    "account_type": "账户类型",
}


def _merge_spaced_labels(tokens: list[Word], page_width: float) -> list[Word]:
    """把被空格拉开的标签短词（如「户   名：」「开   户   行：」）拼回一个词再匹配单值。"""
    max_gap = page_width * 0.055
    merged: list[Word] = []
    for word in tokens:
        if merged and len(merged[-1].text) <= 4 and word.x0 - merged[-1].x1 <= max_gap:
            prev = merged[-1]
            merged[-1] = Word(
                text=prev.text + word.text,
                x0=prev.x0, x1=max(prev.x1, word.x1),
                top=min(prev.top, word.top), bottom=max(prev.bottom, word.bottom),
                size=max(prev.size, word.size),
            )
        else:
            merged.append(word)
    return merged


def _strip_single_prefix(body: str, label: str) -> str:
    """去掉「卡号/账号:」「户名：」这类组合前缀，只留纯值。"""
    if ":" in body or "：" in body:
        head, tail = re.split(r"[:：]", body, maxsplit=1)
        if label in head:
            return tail.strip(" ：:　")
    return body.split(label, 1)[1].strip(" ：:　")


def _match_single_in_token(body: str) -> tuple[str, str, str] | None:
    """识别单值字段前缀（含 OCR 粘连串中夹带的「账号/卡号：…」）。"""
    label = next((text for text, _ in SINGLE_LABELS if body.startswith(text)), None)
    if label is not None:
        return label, dict(SINGLE_LABELS)[label], _strip_single_prefix(body, label)
    for text, field in SINGLE_LABELS:
        m = re.search(rf"{re.escape(text)}(?:[^:：\s]*)\s*[:：]\s*([^\s]+)", body)
        if m:
            return text, field, m.group(1).strip(" ：:　")
    return None


def _is_another_label(text: str) -> bool:
    stripped = text.strip()
    if any(stripped.startswith(lbl) for lbl, _ in SINGLE_LABELS):
        return True
    return any(tag in stripped for tag in ("币种：", "币种:", "打印时间", "查询起日", "页码"))


def _singles(
    page_index: int,
    page: PageWords,
    tokens_per_line: list[list[Word]],
    column_fields: set[str],
    header_index: int = -1,
) -> list[dict]:
    """在一个页面上找「单值字段」：标签 + 紧邻的值，且该标签不构成一列。

    判据三条，缺一不可：
      ① 命中预设标签（卡号/户名/开户行…）；
      ② 同一标签在整页只出现一次（出现多次说明它其实是一列的表头）；
      ③ 能取到值（同行右侧优先，其次正下方）。
    """
    found: list[dict] = []
    seen_fields: set[str] = set()
    scan_limit = header_index if header_index >= 0 else len(tokens_per_line)
    prepared_lines = [_merge_spaced_labels(line, page.width) for line in tokens_per_line[:scan_limit]]

    for line_no, tokens in enumerate(prepared_lines):
        for token in tokens:
            body = token.text.strip()
            matched = _match_single_in_token(body)
            if matched is None:
                continue
            label, field, rest = matched
            if field in seen_fields or field in column_fields:
                continue

            # ② 以标签开头的词在全页只出现一次（出现多次说明它是一列的表头）
            occurrences = sum(
                1 for other_line in prepared_lines for other in other_line
                if other.text.strip().startswith(label)
            )
            if occurrences > 1:
                continue

            # ③ 取值：标签词自带的值 + 同一行右侧紧跟的词；都没有就取正下方（不跨入表头）
            value_words: list[Word] = []
            if rest:
                value_words = [Word(text=rest, x0=token.x0, x1=token.x1, top=token.top, bottom=token.bottom)]
            cursor = value_words[-1].x1 if value_words else token.x1
            for other in tokens:
                if other is token or other.x0 <= cursor:
                    continue
                if other.x0 - cursor > page.width * 0.06:      # 同行但隔得远 = 另一个字段
                    break
                if _is_another_label(other.text) or ":" in other.text or "：" in other.text:
                    break
                value_words.append(other)
                cursor = other.x1
            if not value_words and line_no + 1 < len(prepared_lines):
                below = [
                    other for other in prepared_lines[line_no + 1]
                    if abs(other.x0 - token.x0) < page.width * 0.12 and not _is_another_label(other.text)
                ]
                value_words = below[:1]

            if not value_words:
                continue

            value = "".join(word.text for word in value_words).strip()
            if not value:
                continue

            left = max(0.0, min([token.x0] + [word.x0 for word in value_words]) - 2)
            right = min(page.width, max([token.x1] + [word.x1 for word in value_words]) + 2)
            top = max(0.0, min([token.top] + [word.top for word in value_words]) - 2)
            bottom = min(page.height, max([token.bottom] + [word.bottom for word in value_words]) + 2)
            seen_fields.add(field)
            found.append({
                "field": field,
                "label": SINGLE_FIELD_LABEL.get(field, field),
                "page": page_index,
                "value": value,
                # 归一化：与模板 meta_boxes 的口径一致（左上原点，0-1）
                "x": round(left / page.width, 4) if page.width > 0 else 0.0,
                "y": round(top / page.height, 4) if page.height > 0 else 0.0,
                "w": round(max(0.0, right - left) / page.width, 4) if page.width > 0 else 0.0,
                "h": round(max(0.0, bottom - top) / page.height, 4) if page.height > 0 else 0.0,
                # 点坐标：画布直接用
                "x0": round(left, 2),
                "x1": round(right, 2),
                "y0": round(top, 2),
                "y1": round(bottom, 2),
            })
    return found
