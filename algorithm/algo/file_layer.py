from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable

import fitz
from pydantic import BaseModel, Field

from .evidence import page_evidence
from .models import CheckResult, Evidence, LayerConclusion

MAX_EVIDENCE = 20

GROUP_GENERATION = ("F1", "F2", "F3", "F4")
GROUP_LAYOUT = ("F5", "F6", "F7", "F9")
GROUP_OVERALL = ("F8", "F10", "F11")

OFFICE_MARKERS = (
    "microsoft",
    "word",
    "wps",
    "libreoffice",
    "openoffice",
    "google docs",
    "google drive",
    "chrome",
    "firefox",
    "safari",
    "msedge",
    "canva",
    "ilovepdf",
    "smallpdf",
    "pdf24",
    "sejda",
    "pdfescape",
)
EDITOR_MARKERS = (
    "acrobat",
    "pdf-xchange",
    "master pdf",
    "pdf editor",
    "pdfelement",
    "foxit",
    "nitro",
)
BASE14_FONTS = {
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-Oblique",
    "Times-Roman",
    "Times-Bold",
    "Times-Italic",
    "Courier",
    "Courier-Bold",
    "Symbol",
    "ZapfDingbats",
}
SAFE_NONEMBEDDED = BASE14_FONTS | {
    "Arial",
    "TimesNewRoman",
    "TimesNewRomanPSMT",
    "SimSun",
    "宋体",
    "SimHei",
    "黑体",
    "MicrosoftYaHei",
    "微软雅黑",
}
SUBSET_PREFIX = re.compile(r"^[A-Z]{6}\+")
PDF_DATE = re.compile(r"D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?")


class FileBaseline(BaseModel):
    """同一银行版式的真件基线；没有基线时 F4/F10 只能跳过。"""

    producer: str | None = None
    creator: str | None = None
    page_sizes: list[tuple[float, float]] = Field(default_factory=list)
    font_families: list[str] = Field(default_factory=list)
    bytes_per_page: float | None = None


def _first_line(detail: str) -> str:
    return detail.split("；")[0]


def _parse_pdf_date(value: str | None) -> datetime | None:
    if not value:
        return None
    match = PDF_DATE.match(value)
    if not match:
        return None
    parts = [int(part) if part else 0 for part in match.groups()]
    year, month, day, hour, minute, second = parts
    try:
        return datetime(year, max(month, 1), max(day, 1), hour, minute, second)
    except ValueError:
        return None


def _family(basefont: str) -> str:
    return SUBSET_PREFIX.sub("", basefont or "")


def _page_no(page: fitz.Page) -> int:
    return page.number + 1


def _text(spans: Iterable[dict]) -> str:
    result = []
    for span in spans:
        for char in span.get("chars", ()):
            result.append(chr(char[0]))
    return "".join(result)


def _check_producer(metadata: dict) -> CheckResult:
    code, name = "F1", "生成器指纹"
    values = " ".join(
        str(metadata.get(key) or "") for key in ("producer", "creator", "author")
    ).strip()
    lowered = values.lower()
    if any(marker in lowered for marker in OFFICE_MARKERS):
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=f"生成器像办公/在线工具：{values}",
            evidence=[page_evidence(1, None, code)],
        )
    if any(marker in lowered for marker in EDITOR_MARKERS):
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"生成器为 PDF 编辑工具：{values}，需核对原件",
        )
    if not values:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail="Producer / Creator / Author 为空，生成器指纹缺失",
        )
    return CheckResult(code=code, name=name, status="pass", detail=f"生成器：{values}")


def _check_times(metadata: dict) -> CheckResult:
    code, name = "F2", "创建与修改时间"
    created = _parse_pdf_date(metadata.get("creationDate"))
    modified = _parse_pdf_date(metadata.get("modDate"))
    if created is None or modified is None:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail="创建或修改时间缺失，未核对",
        )
    delta = modified - created
    if delta.total_seconds() < 0:
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=f"修改时间早于创建时间：{created} → {modified}",
            evidence=[page_evidence(1, None, code)],
        )
    if delta.total_seconds() > 24 * 3600:
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=f"修改时间晚于创建时间 {delta}：{created} → {modified}",
            evidence=[page_evidence(1, None, code)],
        )
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail=f"创建与修改间隔 {delta.total_seconds():.0f} 秒",
    )


SIGNATURE_MARKERS = (b"/Type/Sig", b"/Type /Sig")
BYTE_RANGE = re.compile(rb"/ByteRange\s*\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]")
SIGNATURE_TAIL_TOLERANCE = 8


def _signature_state(file_bytes: bytes) -> str:
    """none / signed / appended / malformed；signed 指 ByteRange 覆盖到文件尾。"""
    has_signature = any(marker in file_bytes for marker in SIGNATURE_MARKERS)
    match = BYTE_RANGE.search(file_bytes)
    if not has_signature and match is None:
        return "none"
    if match is None:
        return "malformed"
    start1, span1, start2, span2 = (int(group) for group in match.groups())
    if start1 != 0 or start2 < span1:
        return "malformed"
    if start2 + span2 >= len(file_bytes) - SIGNATURE_TAIL_TOLERANCE:
        return "signed"
    return "appended"


def _check_incremental(file_bytes: bytes) -> CheckResult:
    code, name = "F3", "增量更新痕迹"
    eof_count = file_bytes.count(b"%%EOF")
    xref_count = file_bytes.count(b"startxref")
    if eof_count <= 1 and xref_count <= 1:
        return CheckResult(code=code, name=name, status="pass", detail="单次保存，无增量更新痕迹")
    state = _signature_state(file_bytes)
    if state == "signed":
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=(
                f"文件内有 {eof_count} 个 %%EOF、{xref_count} 个 startxref，"
                "增量更新来自数字签名（ByteRange 覆盖至文件尾），签名未验签"
            ),
        )
    if state == "appended":
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=(
                f"签名范围未覆盖文件尾部，疑似签名后追加内容"
                f"（{eof_count} 个 %%EOF、{xref_count} 个 startxref）"
            ),
            evidence=[page_evidence(1, None, code)],
        )
    if state == "malformed":
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail="存在签名字段但 ByteRange 缺失或异常，增量来源无法判断",
        )
    return CheckResult(
        code=code,
        name=name,
        status="fail",
        detail=f"文件内有 {eof_count} 个 %%EOF、{xref_count} 个 startxref，疑似增量更新",
        evidence=[page_evidence(1, None, code)],
    )


def _check_structure(
    doc: fitz.Document,
    metadata: dict,
    baseline: FileBaseline | None,
) -> CheckResult:
    code, name = "F4", "结构指纹"
    if baseline is None:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail="无该行真件基线，结构指纹未比对",
        )

    mismatches: list[str] = []
    producer = str(metadata.get("producer") or "")
    creator = str(metadata.get("creator") or "")
    if baseline.producer and not producer.startswith(baseline.producer):
        mismatches.append(f"Producer {producer!r} ≠ 基线 {baseline.producer!r}")
    if baseline.creator and not creator.startswith(baseline.creator):
        mismatches.append(f"Creator {creator!r} ≠ 基线 {baseline.creator!r}")

    if baseline.page_sizes:
        sizes = {(round(page.rect.width, 1), round(page.rect.height, 1)) for page in doc}
        for size in sizes:
            if not any(abs(size[0] - b[0]) <= 1 and abs(size[1] - b[1]) <= 1 for b in baseline.page_sizes):
                mismatches.append(f"页面尺寸 {size} 不在基线内")

    if baseline.font_families:
        allowed = set(baseline.font_families)
        families = {
            _family(font[3])
            for page in doc
            for font in page.get_fonts(full=True)
        }
        extra = sorted(families - allowed)
        if extra:
            mismatches.append(f"字体族 {extra} 不在基线内")

    if mismatches:
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail="结构指纹与基线不一致：" + "；".join(mismatches[:3]),
            evidence=[page_evidence(1, None, code)],
        )
    return CheckResult(code=code, name=name, status="pass", detail="Producer、页面尺寸与字体族符合基线")


def _check_fonts(doc: fitz.Document) -> CheckResult:
    code, name = "F5", "字体一致性"
    fonts = [font for page in doc for font in page.get_fonts(full=True)]
    if not fonts:
        return CheckResult(code=code, name=name, status="skipped", detail="无文字层字体")

    non_embedded: set[str] = set()
    embedded_types: set[str] = set()
    for font in fonts:
        ext = (font[1] or "").lower()
        basefont = _family(font[3] or "")
        if ext in ("", "n/a", "none"):
            if basefont not in SAFE_NONEMBEDDED:
                non_embedded.add(basefont)
        else:
            embedded_types.add((font[2] or "").lower())

    if non_embedded:
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=f"存在未嵌入的非标准字体：{sorted(non_embedded)}",
            evidence=[page_evidence(1, None, code)],
        )
    if {"type1", "truetype"} <= embedded_types:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail="嵌入字体同时含 Type1 与 TrueType",
        )
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail=f"{len(fonts)} 个字体对象，嵌入或基础字体",
    )


def _iou(a: fitz.Rect, b: fitz.Rect) -> float:
    intersection = a & b
    if intersection.is_empty:
        return 0.0
    area = a.width * a.height
    return (intersection.width * intersection.height) / area if area else 0.0


def _check_hidden_text(doc: fitz.Document) -> CheckResult:
    code, name = "F6", "隐藏文字层"
    hits: list[Evidence] = []
    for page in doc:
        visible: dict[str, list[fitz.Rect]] = {}
        for span in page.get_texttrace():
            text = _text([span]).strip()
            if not text:
                continue
            bbox = fitz.Rect(span["bbox"])
            if span.get("type") == 3 or span.get("opacity", 1) == 0:
                hits.append(page_evidence(_page_no(page), tuple(bbox), code))
                continue
            if len(text) >= 2:
                visible.setdefault(text, []).append(bbox)
        for rects in visible.values():
            matched = False
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    if _iou(rects[i], rects[j]) >= 0.9:
                        hits.append(page_evidence(_page_no(page), tuple(rects[j]), code))
                        matched = True
                        break
                if matched:
                    break

    if hits:
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=f"命中 {len(hits)} 处隐藏文字或同位置重叠文本",
            evidence=hits[:MAX_EVIDENCE],
        )
    return CheckResult(code=code, name=name, status="pass", detail="无可提取的隐藏文字与重叠文本")


STAMP_MIN_AREA = 3000.0
STAMP_MIN_TEXTS = 3


def _check_overlay(doc: fitz.Document) -> CheckResult:
    code, name = "F7", "覆盖图元"
    hits: list[Evidence] = []
    stamps: list[Evidence] = []
    for page in doc:
        seen_text: list[fitz.Rect] = []
        for kind, rect in page.get_bboxlog():
            bbox = fitz.Rect(rect)
            if kind in ("fill-text", "stroke-text"):
                seen_text.append(bbox)
                continue
            if kind not in ("fill-path", "fill-image"):
                continue
            covered = [text_rect for text_rect in seen_text if _iou(text_rect, bbox) >= 0.8]
            if not covered:
                continue
            area = bbox.width * bbox.height
            if kind == "fill-image" and area >= STAMP_MIN_AREA and len(covered) >= STAMP_MIN_TEXTS:
                stamps.append(page_evidence(_page_no(page), tuple(covered[0]), code))
            else:
                hits.append(page_evidence(_page_no(page), tuple(covered[0]), code))

    if hits:
        detail = f"命中 {len(hits)} 处图元覆盖文字（数字区可能被贴补）"
        if stamps:
            detail += f"；另有 {len(stamps)} 处大尺寸印章/水印图像覆盖，仅记录"
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=detail,
            evidence=(hits + stamps)[:MAX_EVIDENCE],
        )
    if stamps:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail=f"{len(stamps)} 处大尺寸印章/水印图像覆盖文字，按印章记录，不计为贴补",
            evidence=stamps[:MAX_EVIDENCE],
        )
    return CheckResult(code=code, name=name, status="pass", detail="无填充图元或位图覆盖文字")


def _check_signature(doc: fitz.Document) -> CheckResult:
    code, name = "F8", "签名与时间戳"
    flags = doc.get_sigflags()
    if flags is not None and flags > 0 and flags & 1:
        return CheckResult(
            code=code,
            name=name,
            status="partial",
            detail="存在签名字段，证书链与签名后修改未校验",
        )
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail="无 PAdES 签名（银行流水常见），未做密码学校验",
    )


def _text_bounds(page: fitz.Page) -> tuple[float, float, str] | None:
    """返回 (左边距, 顶边距, 首行文字)；文字块不足 5 块视为无可比版面。"""
    blocks = [b for b in page.get_text("blocks") if b[4].strip()]
    if len(blocks) < 5:
        return None
    top_block = min(blocks, key=lambda b: b[1])
    first = re.sub(r"\s+", "", top_block[4].splitlines()[0])[:20] if top_block[4].strip() else ""
    return min(b[0] for b in blocks), top_block[1], first


def _check_layout(doc: fitz.Document) -> CheckResult:
    code, name = "F9", "版面一致性"
    if doc.page_count < 2:
        return CheckResult(code=code, name=name, status="pass", detail="单页，无跨页版面可比")

    first = doc[0]
    for page in doc:
        if abs(page.rect.width - first.rect.width) > 1 or abs(page.rect.height - first.rect.height) > 1:
            return CheckResult(
                code=code,
                name=name,
                status="fail",
                detail=f"第 {_page_no(page)} 页尺寸 {page.rect.width:.0f}×{page.rect.height:.0f} 与首页不一致",
                evidence=[page_evidence(_page_no(page), tuple(page.rect), code)],
            )
        if page.rotation != first.rotation:
            return CheckResult(
                code=code,
                name=name,
                status="fail",
                detail=f"第 {_page_no(page)} 页旋转 {page.rotation}° 与首页 {first.rotation}° 不一致",
                evidence=[page_evidence(_page_no(page), tuple(page.rect), code)],
            )

    bounds = [(page, _text_bounds(page)) for page in doc]
    bounds = [(page, bound) for page, bound in bounds if bound is not None]
    if len(bounds) >= 2:
        lefts = sorted(bound[0] for _, bound in bounds)
        median_left = lefts[len(lefts) // 2]
        # 只有起始行相同的页才比顶边距：续页不重复抬头时起点天然不同，不是拼页痕迹
        tops: dict[str, list[float]] = {}
        for _, bound in bounds:
            tops.setdefault(bound[2], []).append(bound[1])
        top_text = max(tops, key=lambda key: (len(tops[key]), key))
        top_sorted = sorted(tops[top_text])
        median_top = top_sorted[len(top_sorted) // 2]
        skipped_top = 0
        for page, (left, top, first_text) in bounds:
            if abs(left - median_left) > 3:
                return CheckResult(
                    code=code,
                    name=name,
                    status="fail",
                    detail=f"第 {_page_no(page)} 页左边距偏离 {abs(left - median_left):.1f} pt",
                    evidence=[page_evidence(_page_no(page), tuple(page.rect), code)],
                )
            if first_text == top_text and abs(top - median_top) > 3:
                return CheckResult(
                    code=code,
                    name=name,
                    status="fail",
                    detail=f"第 {_page_no(page)} 页顶边距偏离 {abs(top - median_top):.1f} pt",
                    evidence=[page_evidence(_page_no(page), tuple(page.rect), code)],
                )
            if first_text != top_text:
                skipped_top += 1
        detail = "页尺寸、旋转与左边距一致"
        if skipped_top:
            detail += f"（{skipped_top} 页起始行与首页不同，顶边距未比对）"
        return CheckResult(code=code, name=name, status="pass", detail=detail)
    return CheckResult(code=code, name=name, status="pass", detail="页尺寸、旋转与左边距一致")


def _check_volume(
    file_bytes: bytes, doc: fitz.Document, baseline: FileBaseline | None
) -> CheckResult:
    code, name = "F10", "体量与页密度"
    if baseline is None or not baseline.bytes_per_page:
        return CheckResult(
            code=code,
            name=name,
            status="skipped",
            detail="无同类版式基线，体量与页密度未比对",
        )
    per_page = len(file_bytes) / max(doc.page_count, 1)
    ratio = per_page / baseline.bytes_per_page
    if ratio < 0.5 or ratio > 2.0:
        return CheckResult(
            code=code,
            name=name,
            status="fail",
            detail=f"每页 {per_page:.0f} 字节，为基线 {baseline.bytes_per_page:.0f} 的 {ratio:.2f} 倍",
            evidence=[page_evidence(1, None, code)],
        )
    return CheckResult(code=code, name=name, status="pass", detail=f"每页字节数为基线的 {ratio:.2f} 倍")


def _check_image_mix(doc: fitz.Document) -> CheckResult:
    code, name = "F11", "图像与矢量混排"
    images = 0
    for page in doc:
        text = page.get_text("text").strip()
        area = abs(page.rect.width * page.rect.height)
        for info in page.get_image_info():
            images += 1
            bbox = fitz.Rect(info["bbox"])
            if area and bbox.width * bbox.height / area > 0.8 and len(text) > 50:
                return CheckResult(
                    code=code,
                    name=name,
                    status="fail",
                    detail=f"第 {_page_no(page)} 页整页图像与文字层混排",
                    evidence=[page_evidence(_page_no(page), tuple(bbox), code)],
                )
    if images == 0:
        return CheckResult(code=code, name=name, status="pass", detail="无图像对象，纯文字/矢量件")
    return CheckResult(
        code=code,
        name=name,
        status="pass",
        detail=f"{images} 个图像对象，均未覆盖正文",
    )


def _empty(detail: str) -> LayerConclusion:
    return LayerConclusion(layer="file", status="skipped", detail=detail)


def analyze_file(
    file_bytes: bytes,
    *,
    carrier: str = "electronic",
    baseline: FileBaseline | None = None,
) -> LayerConclusion:
    """电子件结构取证 F1–F11；影像件与截图件不做结构取证。"""
    if carrier != "electronic":
        return _empty(f"载体为 {carrier}，不做结构取证")
    if not file_bytes.startswith(b"%PDF"):
        return _empty("非 PDF，结构取证不适用")

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as exc:
        return _empty(f"PDF 打开失败，结构取证未做：{exc}")
    if doc.needs_pass:
        doc.close()
        return _empty("PDF 已加密，结构取证未做")

    try:
        metadata = doc.metadata or {}
        checks = [
            _check_producer(metadata),
            _check_times(metadata),
            _check_incremental(file_bytes),
            _check_structure(doc, metadata, baseline),
            _check_fonts(doc),
            _check_hidden_text(doc),
            _check_overlay(doc),
            _check_signature(doc),
            _check_layout(doc),
            _check_volume(file_bytes, doc, baseline),
            _check_image_mix(doc),
        ]
    except Exception as exc:
        return _empty(f"结构取证执行失败：{exc}")
    finally:
        doc.close()

    by_code = {check.code: check for check in checks}
    group1 = [by_code[code] for code in GROUP_GENERATION if by_code[code].status == "fail"]
    group2 = [by_code[code] for code in GROUP_LAYOUT if by_code[code].status == "fail"]
    group3 = [by_code[code] for code in GROUP_OVERALL if by_code[code].status == "fail"]

    limitations = [
        f"{check.code} {check.name}：{check.detail}"
        for check in checks
        if check.status in ("skipped", "partial")
    ]
    if group3:
        limitations.extend(
            f"{check.code} {check.name}：{check.detail}（仅记录，不单独定性）"
            for check in group3
        )
    if len(group2) == 1:
        limitations.append(f"{group2[0].code} {group2[0].name}：{group2[0].detail}（单项命中，记录不阻断）")
    if by_code["F8"].detail.startswith("无 PAdES 签名"):
        limitations.append("F8 签名与时间戳：文件未签名，无法做密码学校验")

    if group1 or len(group2) >= 2:
        hits = group1 + group2
        details = "；".join(f"{check.code} {_first_line(check.detail)}" for check in hits)
        return LayerConclusion(
            layer="file",
            status="fail",
            detail=f"结构取证命中：{details}",
            outcome="来源可疑",
            checks=checks,
            limitations=limitations,
            evidence=[item for check in hits for item in check.evidence][:MAX_EVIDENCE],
        )

    executed = sum(1 for check in checks if check.status in ("pass", "fail"))
    if limitations:
        return LayerConclusion(
            layer="file",
            status="limited",
            detail=f"结构取证完成 {executed}/11 项，未发现来源可疑痕迹",
            checks=checks,
            limitations=limitations,
        )
    return LayerConclusion(
        layer="file",
        status="pass",
        detail="结构取证 11 项全部执行，未发现来源可疑痕迹",
        checks=checks,
    )
