"""版式检测主干：锚点扩散 + 几何聚类。

两条路都产出同一种东西——「列带」（band）：这一列在页面上的横向范围 + 它装的是哪个字段。

锚点扩散（主路）：
  表头里认出 >=2 个字段当种子 -> 顺着 y 往下找同形态的值 -> 用命中词的包络把带宽长出来。
  关键词只负责起步，形态负责收敛，所以「同一字段在不同行叫不同的名字」不影响它。

几何聚类（兜底）：
  没有可用表头时，找「连续多行、每行 >=3 个 token、含日期与金额」的表格段，
  按横向间隙切列，再按位置与形态推字段名。表头坏了的件走这条。

两条路的差别只在起点，收敛逻辑共用，避免两套口径。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ...core.contracts import ColumnBand, LayoutPlan, TableRegion
from . import keywords as kw
from .words import Line, PageWords, Word, group_lines, merge_tokens

MIN_HITS = 3               # 一列至少命中这么多行才算成立
MAX_MISSES = 8             # 连续这么多行不命中就认为列结束
HEADER_SCAN_LINES = 30     # 表头只在前若干行里找


@dataclass
class Band:
    field: str
    source: str                 # header / shape
    x0: float
    x1: float
    hits: list[Word] = field(default_factory=list)

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def width(self) -> float:
        return self.x1 - self.x0


def _expand_header_tokens(tokens: list[Word]) -> list[tuple[str, Word]]:
    """把表头行拆成 (field, seed_word) 列表，兼容 OCR 粘连成整块的复合表头。"""
    seeds: list[tuple[str, Word]] = []
    seen: set[str] = set()
    for token in tokens:
        splits = kw.split_header_token(token.text)
        if splits:
            width = max(1.0, token.x1 - token.x0)
            for field, r0, r1 in splits:
                if field in seen:
                    continue
                sub_word = Word(
                    text=field,
                    x0=token.x0 + width * r0,
                    x1=token.x0 + width * r1,
                    top=token.top,
                    bottom=token.bottom,
                    size=token.size,
                )
                seeds.append((field, sub_word))
                seen.add(field)
            continue
        hit = kw.match_header_field(token.text)
        if hit and hit not in seen:
            seeds.append((hit, token))
            seen.add(hit)
    return seeds


def _find_header(tokens_per_line: list[list[Word]]) -> tuple[int, list[tuple[str, Word]]] | None:
    best: tuple[int, int, list[tuple[str, Word]]] | None = None
    for index, tokens in enumerate(tokens_per_line[:HEADER_SCAN_LINES]):
        seeds = _expand_header_tokens(tokens)
        if len(seeds) < 2:
            continue
        score = len(seeds)
        if best is None or score > best[0]:
            best = (score, index, seeds)
    if best is None:
        return None
    return best[1], best[2]


def _tolerance(field_name: str, page_width: float) -> float:
    """金额列右对齐、日期列左对齐，与表头词中心天然有偏移，给大一点的初始容差。"""
    return page_width * (0.035 if field_name in kw.MONEY_FIELDS else 0.015)


def data_start_after_header(tokens_per_line: list[list[Word]], header_index: int) -> int:
    """跳过英文副表头或换行表头行，从真正的首行交易数据开始收集。"""
    start = header_index + 1
    limit = min(len(tokens_per_line), header_index + 5)
    while start < limit:
        texts = [token.text for token in tokens_per_line[start]]
        if kw.is_header_continuation(texts):
            start += 1
        else:
            break
    return start


def _spread(
    tokens_per_line: list[list[Word]],
    header_index: int,
    seeds: list[tuple[str, Word]],
    page_width: float,
) -> list[Band]:
    ordered_seeds = sorted(seeds, key=lambda item: item[1].cx)
    seed_cxs = [item[1].cx for item in ordered_seeds]
    start_row = data_start_after_header(tokens_per_line, header_index)
    bands: list[Band] = []
    for idx, (field_name, seed) in enumerate(ordered_seeds):
        left, right = seed.x0, seed.x1
        center = seed.cx
        prev_cx = seed_cxs[idx - 1] if idx > 0 else None
        next_cx = seed_cxs[idx + 1] if idx + 1 < len(seed_cxs) else None
        hits: list[Word] = []
        misses = 0
        for tokens in tokens_per_line[start_row:]:
            tolerance = _tolerance(field_name, page_width)
            half = max((right - left) / 2, page_width * 0.008) + tolerance
            candidate: Word | None = None
            best_distance = None
            for token in tokens:
                distance = abs(token.cx - center)
                if distance > half:
                    continue
                if prev_cx is not None and token.cx < seed.cx and (seed.cx - token.cx) > (token.cx - prev_cx) + page_width * 0.01:
                    continue
                if next_cx is not None and token.cx > seed.cx and (token.cx - seed.cx) > (next_cx - token.cx) + page_width * 0.01:
                    continue
                if best_distance is None or distance < best_distance:
                    candidate, best_distance = token, distance
            if candidate is not None and kw.shape_ok(field_name, candidate.text):
                hits.append(candidate)
                left = min(left, candidate.x0)
                right = max(right, candidate.x1)
                center = (left + right) / 2
                misses = 0
            else:
                misses += 1
                if misses > MAX_MISSES and hits:
                    break
        if len(hits) >= MIN_HITS:
            bands.append(Band(field_name, "header", left, right, hits))
        elif hits:
            # 命中不足但确实读到过值：保留几何，交给人/下游判断
            bands.append(Band(field_name, "header_weak", left, right, hits))
        else:
            # 表头认出来了、这一段没有值（例如建行的收入金额列在这页全空）：
            # 仍然保留列带。删掉它会让「收入金额」的值被就近吸进「支出金额」，方向直接判反。
            bands.append(Band(field_name, "header_empty", left, right, []))
    return _dedupe_bands(bands)


def _header_only_bands(seeds: list[tuple[str, Word]]) -> list[Band]:
    """兜底档：数据行不足（短页/末页）时，用表头词自己的位置当列带。

    这不比旧解析器差——旧解析器本来就是「按表头词中心推算列边界」；
    有了它，短页不会被整页丢掉。命中数为 0 表示「只有几何，没有值佐证」。
    """
    bands = [Band(field_name, "header_only", token.x0, token.x1, []) for field_name, token in seeds]
    return _dedupe_bands(bands)


def _dedupe_bands(bands: list[Band]) -> list[Band]:
    """同一字段长出多条时保留命中最多的那条。"""
    best: dict[str, Band] = {}
    for band in bands:
        current = best.get(band.field)
        if current is None or len(band.hits) > len(current.hits):
            best[band.field] = band
    return sorted(best.values(), key=lambda b: b.x0)


def _clusters(values: list[float], gap: float) -> list[tuple[float, float]]:
    if not values:
        return []
    ordered = sorted(values)
    groups: list[list[float]] = [[ordered[0]]]
    for value in ordered[1:]:
        if value - groups[-1][-1] > gap:
            groups.append([value])
        else:
            groups[-1].append(value)
    return [(g[0], g[-1]) for g in groups]


def _geometry(tokens_per_line: list[list[Word]], page_width: float) -> list[Band]:
    """没有表头时：先找表格段，再按横向间隙切列，最后按位置推字段。"""
    row_like: list[int] = []
    for index, tokens in enumerate(tokens_per_line):
        if len(tokens) < 3:
            continue
        has_date = any(kw.is_date(t.text) for t in tokens)
        has_money = any(kw.is_money(t.text) for t in tokens)
        if has_date and has_money:
            row_like.append(index)
    if len(row_like) < MIN_HITS:
        return []

    # 最长连续段（允许隔一行，页码/分隔行偶尔插在中间）
    best_start = best_end = row_like[0]
    start = prev = row_like[0]
    for index in row_like[1:]:
        if index - prev <= 2:
            prev = index
        else:
            if prev - start > best_end - best_start:
                best_start, best_end = start, prev
            start = prev = index
    if prev - start > best_end - best_start:
        best_start, best_end = start, prev

    segment = tokens_per_line[best_start:best_end + 1]
    tokens = [t for line in segment for t in line]
    if len(tokens) < MIN_HITS * 2:
        return []

    gap = page_width * 0.012
    spans = _clusters([t.cx for t in tokens], gap)
    bands: list[Band] = []
    for low, high in spans:
        members = [t for t in tokens if low - 1e-6 <= t.cx <= high + 1e-6]
        if len(members) < MIN_HITS:
            continue
        fields = _classify(members)
        if fields is None:
            continue
        x0 = min(m.x0 for m in members)
        x1 = max(m.x1 for m in members)
        bands.append(Band(fields, "shape", x0, x1, members))

    mapping = _assign_by_position(bands, page_width)
    for index, band in enumerate(bands):
        band.field = mapping.get(index, band.field)
    return _dedupe_bands([b for b in bands if b.field])


def _classify(members: list[Word]) -> str | None:
    """一个横向簇里主要是什么形态。"""
    total = len(members)
    dates = sum(kw.is_date(m.text) for m in members)
    money = sum(kw.is_money(m.text) for m in members)
    direction = sum(kw.is_direction(m.text) for m in members)
    ref = sum(kw.is_reference(m.text) for m in members)
    if dates / total >= 0.6:
        return "txn_date"
    if money / total >= 0.6:
        return "money"
    if direction / total >= 0.6:
        return "direction"
    if ref / total >= 0.6:
        return "reference_no"
    return "text"


def _assign_by_position(bands: list[Band], page_width: float) -> dict[int, str]:
    """几何路的字段推断：最左日期、最右金额=余额、最宽文本=摘要。"""
    mapping: dict[int, str] = {}
    money_index = [i for i, b in enumerate(bands) if b.field == "money"]
    text_index = sorted(
        [i for i, b in enumerate(bands) if b.field == "text"],
        key=lambda i: -(bands[i].width),
    )
    for index, band in enumerate(bands):
        if band.field in ("txn_date", "direction", "reference_no"):
            mapping[index] = band.field
    if len(money_index) >= 2:
        mapping[money_index[-1]] = "balance"
        for index in money_index[:-1]:
            mapping[index] = "amount"
    elif money_index:
        mapping[money_index[0]] = "amount"
    for rank, index in enumerate(text_index[:2]):
        mapping[index] = "summary" if rank == 0 else "counterparty"
    return mapping


def _confidence(bands: list[Band], source: str, rows: int) -> float:
    fields = {b.field for b in bands}
    score = 0.30 + 0.08 * min(len(bands), 5)
    score += 0.15 if "txn_date" in fields else 0.0
    score += 0.15 if fields & kw.MONEY_FIELDS else 0.0
    score += 0.10 if "balance" in fields else 0.0
    score += 0.10 * min(rows / 10, 1.0)
    if source == "geometry":
        score -= 0.15
    elif source == "header_only":
        score -= 0.35
    return round(max(0.05, min(0.98, score)), 3)


def _build_region(
    page: PageWords,
    bands: list[Band],
    source: str,
    header_line: Line | None,
) -> TableRegion | None:
    if not bands:
        return None
    rows = max((len(b.hits) for b in bands), default=0)
    x0 = min(b.x0 for b in bands)
    x1 = max(b.x1 for b in bands)
    first_values = [w for b in bands for w in b.hits]
    if first_values:
        top = min(w.top for w in first_values)
        bottom = max(w.bottom for w in first_values)
    else:
        # 只有表头：向下给一个宽松范围，让裁切不把数据行切掉
        top = header_line.top if header_line is not None else 0.0
        bottom = page.height * 0.9
    if header_line is not None:
        top = min(top, header_line.top)

    pad_x = page.width * 0.015
    pad_y = page.height * 0.01
    area = (
        max(0.0, (x0 - pad_x)) / page.width,
        max(0.0, (top - pad_y)) / page.height,
        min(1.0, (x1 - x0 + 2 * pad_x) / page.width),
        min(1.0, (bottom - top + 2 * pad_y) / page.height),
    )
    columns = [
        ColumnBand(field=b.field, x=b.x0 / page.width, w=max(b.width / page.width, 0.005),
                   confidence={"header": 1.0, "header_weak": 0.5}.get(b.source, 0.4))
        for b in bands
    ]
    return TableRegion(
        page=page.page_no,
        slot="auto",
        area=area,
        header_y=(header_line.top / page.height) if header_line is not None else None,
        columns=columns,
        source=source,
        confidence=_confidence(bands, source, rows),
    )


def detect_page_regions(page: PageWords) -> list[TableRegion]:
    """检测一页内的全部表格区域（支持同页上下多张表格）。"""
    if not page.has_text:
        return []
    heights = sorted(word.bottom - word.top for word in page.words)
    tolerance = max(2.0, heights[len(heights) // 2] * 0.6)
    lines: list[Line] = group_lines(page.words, y_tol=tolerance)
    tokens_per_line = [merge_tokens(line) for line in lines]

    header = _find_header(tokens_per_line)
    bands: list[Band] = []
    source = "none"
    header_line: Line | None = None
    header_index = -1
    if header is not None:
        header_index, seeds = header
        bands = _spread(tokens_per_line, header_index, seeds, page.width)
        if len(bands) >= 2:
            source = "anchor_spread"
            header_line = lines[header_index]
    if len(bands) < 2:
        bands = _geometry(tokens_per_line, page.width)
        source = "geometry" if len(bands) >= 2 else "none"
    if len(bands) < 2 and header is not None and len(header[1]) >= 2:
        bands = _header_only_bands(header[1])
        source = "header_only"
        header_line = lines[header[0]]
    primary = _build_region(page, bands, source, header_line)
    if primary is None:
        return []

    regions = [primary]
    primary_bottom = (primary.area[1] + primary.area[3]) * page.height
    tail_start = next((i for i, line in enumerate(lines) if line.top > primary_bottom + page.height * 0.02), None)
    if tail_start is not None and tail_start < len(tokens_per_line) - 3:
        tail_header = _find_header(tokens_per_line[tail_start:])
        if tail_header is not None:
            rel_idx, tail_seeds = tail_header
            abs_idx = tail_start + rel_idx
            if abs_idx > header_index:
                tail_bands = _spread(tokens_per_line, abs_idx, tail_seeds, page.width)
                if sum(1 for b in tail_bands if len(b.hits) >= MIN_HITS) >= 2:
                    second = _build_region(page, tail_bands, "anchor_spread", lines[abs_idx])
                    if second is not None:
                        regions.append(second)
    return regions


def detect_page(page: PageWords) -> TableRegion | None:
    regions = detect_page_regions(page)
    return regions[0] if regions else None


def detect_layout(pages: list[PageWords]) -> LayoutPlan:
    regions = [r for p in pages for r in detect_page_regions(p)]
    text_pages = [p for p in pages if p.has_text]
    size = (pages[0].width, pages[0].height) if pages else None
    if not regions:
        reason = "没有文本层，需要走 OCR 通道" if not text_pages else "没有认出可用的表格结构"
        return LayoutPlan(page_size=size, page_count=len(pages), regions=[], confidence=0.0,
                          method="none", reasons=[reason])
    method = "anchor_spread" if any(r.source == "anchor_spread" for r in regions) else "geometry"
    confidence = round(sum(r.confidence for r in regions) / len(regions), 3)
    reasons = [f"第 {r.page + 1} 页：{r.source}，{len(r.columns)} 列" for r in regions]
    return LayoutPlan(page_size=size, page_count=len(pages), regions=regions,
                      confidence=confidence, method=method, reasons=reasons)
