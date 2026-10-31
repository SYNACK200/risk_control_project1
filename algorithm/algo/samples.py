from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal

import fitz
from pydantic import BaseModel, Field

SampleLayout = Literal["icbc", "ccb", "cmb", "wechat"]
ForgeryType = Literal[
    "content_amount_tamper",
    "file_incremental_overlay",
    "content_row_deleted",
    "content_page_splice",
    "content_duplicate_reference",
]
Carrier = Literal["electronic", "image", "screenshot"]
SampleVerdict = Literal["未发现异常", "存在不一致", "余额可疑", "来源可疑", "无法判定"]

SAMPLE_LAYOUTS: tuple[str, ...] = ("icbc", "ccb", "cmb", "wechat")
SAMPLE_FORGERY_TYPES: tuple[str, ...] = (
    "content_amount_tamper",
    "file_incremental_overlay",
    "content_row_deleted",
    "content_page_splice",
    "content_duplicate_reference",
)
LAYOUT_LABELS = {
    "icbc": "工行式：借贷标志 + 单列交易金额 + 余额，跨两页",
    "ccb": "建行式：收入金额与支出金额分列 + 账户余额",
    "cmb": "招行式：借贷方向 + 交易金额 + 交易后余额",
    "wechat": "微信账单：收/支 + 金额，无余额列",
}
FORGERY_LABELS = {
    "content_amount_tamper": "内容篡改：改金额不改余额，余额链断",
    "file_incremental_overlay": "文件伪造：增量更新 + 白底覆盖后重写金额",
    "content_row_deleted": "内容篡改：删一笔但保留原页脚，余额链、页合计、笔数同时暴露",
    "content_page_splice": "内容伪造：两个时段拼页，页内各自闭合、接缝余额链断",
    "content_duplicate_reference": "内容篡改：整行复制一笔（含同一参考号），余额链同步改写，重号暴露",
}
SAMPLE_SET_VERSION = 3


class SampleExpectation(BaseModel):
    """eval 断言用的最小期望，不绑定某一层的实现细节。"""

    verdict: SampleVerdict
    txn_count: int | None = None
    fail_codes: list[str] = Field(default_factory=list)


class SampleCase(BaseModel):
    id: str
    path: str
    layout: SampleLayout
    carrier: Carrier = "electronic"
    forgery: ForgeryType | None = None
    expectation: SampleExpectation
    notes: str = ""


class SampleManifest(BaseModel):
    version: int = SAMPLE_SET_VERSION
    generated_by: str = "algorithm.algo.samples"
    cases: list[SampleCase] = Field(default_factory=list)


@dataclass(frozen=True)
class LoadedSample:
    case: SampleCase
    path: Path

    def read_bytes(self) -> bytes:
        return self.path.read_bytes()


_ICBC_HEADER = ["交易日期", "摘要", "对方户名", "借贷标志", "交易金额", "余额"]
_ICBC_XS = [40, 200, 380, 480, 560, 660]
_ICBC_REF_HEADER = [*_ICBC_HEADER, "交易流水号"]
_ICBC_REF_XS = [*_ICBC_XS, 730]
_CCB_HEADER = ["交易日期", "摘要", "对方户名", "收入金额", "支出金额", "账户余额"]
_CCB_XS = [40, 170, 300, 430, 510, 610]
_CMB_HEADER = ["交易日期", "交易类型", "对手方", "借贷方向", "交易金额", "交易后余额"]
_CMB_XS = [40, 170, 300, 400, 500, 620]
_WECHAT_HEADER = [
    "交易时间",
    "交易类型",
    "交易对方",
    "商品",
    "收/支",
    "金额(元)",
    "支付方式",
    "当前状态",
    "交易单号",
]
_WECHAT_XS = [30, 115, 190, 280, 355, 405, 465, 515, 560]

_BANK_ROWS = [
    ("2026-01-05", "工资", "某公司", "贷", "12,500.00", "13,200.00"),
    ("2026-01-06", "消费", "某超市", "借", "300.50", "12,899.50"),
    ("2026-01-07", "转账", "张三", "借", "1,000.00", "11,899.50"),
    ("2026-02-05", "工资", "某公司", "贷", "12,500.00", "24,399.50"),
    ("2026-02-08", "还款", "某银行", "借", "2,000.00", "22,399.50"),
    ("2026-02-10", "消费", "某餐厅", "借", "150.00", "22,249.50"),
]


def _icbc_rows() -> list[tuple[str, ...]]:
    return list(_BANK_ROWS)


def _icbc_duplicate_reference_rows() -> list[tuple[str, ...]]:
    """复制第 2 笔（连参考号一起）并把其后余额整体下调，保证余额链仍闭合。"""
    shift = Decimal(_BANK_ROWS[1][4].replace(",", ""))
    base = [_BANK_ROWS[0], _BANK_ROWS[1], _BANK_ROWS[1], *_BANK_ROWS[2:]]
    references = [f"20260105{index:04d}" for index in (1, 2, 2, 3, 4, 5, 6)]
    rows: list[tuple[str, ...]] = []
    for index, ((day, summary, party, direction, amount, balance), reference) in enumerate(
        zip(base, references)
    ):
        value = Decimal(balance.replace(",", ""))
        if index >= 2:
            value -= shift
        rows.append((day, summary, party, direction, amount, f"{value:,.2f}", reference))
    return rows


def _ccb_rows() -> list[tuple[str, ...]]:
    return [
        (day, summary, party, amount if direction == "贷" else "", amount if direction == "借" else "", balance)
        for day, summary, party, direction, amount, balance in _BANK_ROWS
    ]


def _cmb_rows() -> list[tuple[str, ...]]:
    return [
        (day, summary, party, "贷" if direction == "贷" else "借", amount, balance)
        for day, summary, party, direction, amount, balance in _BANK_ROWS
    ]


def _wechat_rows() -> list[tuple[str, ...]]:
    return [
        ("2026-10-01", "商户消费", "某便利店", "饮料", "支出", "¥12.50", "零钱", "支付成功", "4200001"),
        ("2026-10-02", "转账", "李四", "转账", "收入", "¥200.00", "零钱", "已入账", "4200002"),
        ("2026-10-03", "商户消费", "某餐厅", "午餐", "支出", "¥35.00", "零钱", "支付成功", "4200003"),
        ("2026-10-04", "转账", "王五", "红包", "收入", "¥88.00", "零钱", "已入账", "4200004"),
    ]


_FONT_NAME = "SampleCJK"


@lru_cache(maxsize=1)
def _cjk_font() -> fitz.Font:
    return fitz.Font("china-s")


def _page_totals(rows: list[tuple[str, ...]], layout: SampleLayout) -> tuple[Decimal, Decimal]:
    income = Decimal("0")
    expense = Decimal("0")
    for row in rows:
        if layout == "ccb":
            if row[3]:
                income += Decimal(row[3].replace(",", ""))
            if row[4]:
                expense += Decimal(row[4].replace(",", ""))
        else:
            amount = Decimal(row[4].replace(",", "").replace("¥", ""))
            if row[3] == "贷":
                income += amount
            else:
                expense += amount
    return income, expense


def _bank_footer(rows: list[tuple[str, ...]], layout: SampleLayout) -> list[str]:
    income, expense = _page_totals(rows, layout)
    return [
        f"本页收入合计：{income:,.2f} 本页支出合计：{expense:,.2f}",
        f"本页交易笔数：{len(rows)}",
    ]


def _write_pdf(
    path: Path,
    *,
    title: str,
    header: list[str],
    xs: list[int],
    pages: list[list[tuple[str, ...]]],
    footers: list[list[str]] | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    font = _cjk_font()
    doc = fitz.open()
    for page_index, rows in enumerate(pages):
        page = doc.new_page(width=800, height=1000)
        page.insert_font(fontname=_FONT_NAME, fontbuffer=font.buffer)
        page.insert_text((40, 60), title, fontsize=12, fontname=_FONT_NAME)
        for label, x in zip(header, xs):
            page.insert_text((x, 90), label, fontsize=7, fontname=_FONT_NAME)
        last_y = 90
        for row_index, row in enumerate(rows, start=1):
            last_y = 90 + 18 * row_index
            for value, x in zip(row, xs):
                if value:
                    page.insert_text((x, last_y), value, fontsize=7, fontname=_FONT_NAME)
        footer_y = last_y + 24
        for line in (footers[page_index] if footers else []):
            page.insert_text((40, footer_y), line, fontsize=7, fontname=_FONT_NAME)
            footer_y += 12
    doc.set_metadata(
        {
            "title": title,
            "author": "算法组合成样本",
            "subject": "AL-15 合成流水，非真实客户数据",
            "creator": "SyntheticStatement 1.0",
            "producer": "SyntheticStatement 1.0",
            "creationDate": "D:20260101000000+08'00'",
            "modDate": "D:20260101000000+08'00'",
        }
    )
    doc.subset_fonts()
    doc.save(path)
    doc.close()


def _apply_incremental_overlay(path: Path) -> None:
    """白底覆盖原金额后追加新文本，并以增量更新保存，制造 F3 + F7 两类痕迹。"""
    doc = fitz.open(path)
    page = doc[0]
    rects = page.search_for("300.50") or page.search_for("3 0 0 . 5 0")
    if not rects:
        doc.close()
        raise RuntimeError("样本生成失败：未找到待覆盖金额")
    rect = rects[0]
    page.insert_font(fontname=_FONT_NAME, fontbuffer=_cjk_font().buffer)
    page.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
    page.insert_text(
        (rect.x0, rect.y1 - 1), "30.50", fontsize=7, fontname=_FONT_NAME, overlay=True
    )
    doc.save(path, incremental=True, encryption=fitz.PDF_ENCRYPT_KEEP)
    doc.close()


def _splice_pages(path: Path, first: Path, second: Path) -> None:
    """把两份同版式文件的页面拼成一份，制造跨页接缝。保留首页元数据。"""
    doc = fitz.open(first)
    with fitz.open(second) as other:
        doc.insert_pdf(other)
    doc.save(path)
    doc.close()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _clean_case(
    sample_id: str,
    path: Path,
    root: Path,
    layout: SampleLayout,
    txn_count: int,
    notes: str,
) -> SampleCase:
    return SampleCase(
        id=sample_id,
        path=_relative(path, root),
        layout=layout,
        expectation=SampleExpectation(verdict="未发现异常", txn_count=txn_count),
        notes=notes,
    )


def build_sample_set(directory: str | Path) -> list[LoadedSample]:
    """生成四类版式与两类伪造样本；全部为造数，不含真实客户信息。"""
    root = Path(directory)
    clean = root / "clean"
    forged = root / "forged"

    icbc_pages = [_icbc_rows()[:3], _icbc_rows()[3:]]
    _write_pdf(
        clean / "icbc.pdf",
        title="银行账户交易明细",
        header=_ICBC_HEADER,
        xs=_ICBC_XS,
        pages=icbc_pages,
        footers=[_bank_footer(page, "icbc") for page in icbc_pages],
    )
    ccb_pages = [_ccb_rows()]
    _write_pdf(
        clean / "ccb.pdf",
        title="银行账户交易明细",
        header=_CCB_HEADER,
        xs=_CCB_XS,
        pages=ccb_pages,
        footers=[_bank_footer(page, "ccb") for page in ccb_pages],
    )
    cmb_pages = [_cmb_rows()]
    _write_pdf(
        clean / "cmb.pdf",
        title="银行账户交易明细",
        header=_CMB_HEADER,
        xs=_CMB_XS,
        pages=cmb_pages,
        footers=[_bank_footer(page, "cmb") for page in cmb_pages],
    )
    wechat_pages = [_wechat_rows()]
    _write_pdf(
        clean / "wechat.pdf",
        title="微信支付账单明细",
        header=_WECHAT_HEADER,
        xs=_WECHAT_XS,
        pages=wechat_pages,
        footers=[[f"本页交易笔数：{len(wechat_pages[0])}"]],
    )

    tampered = [list(row) for row in _BANK_ROWS]
    tampered[1][4] = "30.50"
    tampered_pages = [tampered[:3], tampered[3:]]
    _write_pdf(
        forged / "icbc_amount_tamper.pdf",
        title="银行账户交易明细",
        header=_ICBC_HEADER,
        xs=_ICBC_XS,
        pages=tampered_pages,
        footers=[_bank_footer(page, "icbc") for page in tampered_pages],
    )
    overlay_path = forged / "icbc_incremental_overlay.pdf"
    _write_pdf(
        overlay_path,
        title="银行账户交易明细",
        header=_ICBC_HEADER,
        xs=_ICBC_XS,
        pages=icbc_pages,
        footers=[_bank_footer(page, "icbc") for page in icbc_pages],
    )
    _apply_incremental_overlay(overlay_path)

    deleted = [list(row) for row in _BANK_ROWS]
    del deleted[2]
    deleted_pages = [deleted[:2], deleted[2:]]
    _write_pdf(
        forged / "icbc_row_deleted.pdf",
        title="银行账户交易明细",
        header=_ICBC_HEADER,
        xs=_ICBC_XS,
        pages=deleted_pages,
        footers=[
            _bank_footer(list(_BANK_ROWS[:3]), "icbc"),
            _bank_footer(list(_BANK_ROWS[3:]), "icbc"),
        ],
    )

    shifted = [list(row) for row in _BANK_ROWS]
    for row in shifted[3:]:
        row[5] = f"{Decimal(row[5].replace(',', '')) - Decimal('10000'):,.2f}"
    splice_first = forged / "_splice_page_1.pdf"
    splice_second = forged / "_splice_page_2.pdf"
    _write_pdf(
        splice_first,
        title="银行账户交易明细",
        header=_ICBC_HEADER,
        xs=_ICBC_XS,
        pages=[list(_BANK_ROWS[:3])],
        footers=[_bank_footer(list(_BANK_ROWS[:3]), "icbc")],
    )
    _write_pdf(
        splice_second,
        title="银行账户交易明细",
        header=_ICBC_HEADER,
        xs=_ICBC_XS,
        pages=[shifted[3:]],
        footers=[_bank_footer(shifted[3:], "icbc")],
    )
    splice_path = forged / "icbc_page_splice.pdf"
    _splice_pages(splice_path, splice_first, splice_second)
    splice_first.unlink(missing_ok=True)
    splice_second.unlink(missing_ok=True)

    duplicate_rows = _icbc_duplicate_reference_rows()
    duplicate_pages = [duplicate_rows[:4], duplicate_rows[4:]]
    duplicate_path = forged / "icbc_duplicate_reference.pdf"
    _write_pdf(
        duplicate_path,
        title="银行账户交易明细",
        header=_ICBC_REF_HEADER,
        xs=_ICBC_REF_XS,
        pages=duplicate_pages,
        footers=[_bank_footer(page, "icbc") for page in duplicate_pages],
    )

    cases = [
        _clean_case("clean_icbc", clean / "icbc.pdf", root, "icbc", 6, LAYOUT_LABELS["icbc"]),
        _clean_case("clean_ccb", clean / "ccb.pdf", root, "ccb", 6, LAYOUT_LABELS["ccb"]),
        _clean_case("clean_cmb", clean / "cmb.pdf", root, "cmb", 6, LAYOUT_LABELS["cmb"]),
        _clean_case("clean_wechat", clean / "wechat.pdf", root, "wechat", 4, LAYOUT_LABELS["wechat"]),
        SampleCase(
            id="forged_amount_icbc",
            path=_relative(forged / "icbc_amount_tamper.pdf", root),
            layout="icbc",
            forgery="content_amount_tamper",
            expectation=SampleExpectation(
                verdict="存在不一致",
                txn_count=6,
                fail_codes=["C1"],
            ),
            notes=FORGERY_LABELS["content_amount_tamper"],
        ),
        SampleCase(
            id="forged_overlay_icbc",
            path=_relative(overlay_path, root),
            layout="icbc",
            forgery="file_incremental_overlay",
            expectation=SampleExpectation(
                verdict="来源可疑",
                txn_count=None,
                fail_codes=["F3", "F7"],
            ),
            notes=FORGERY_LABELS["file_incremental_overlay"],
        ),
        SampleCase(
            id="forged_row_deleted_icbc",
            path=_relative(forged / "icbc_row_deleted.pdf", root),
            layout="icbc",
            forgery="content_row_deleted",
            expectation=SampleExpectation(
                verdict="存在不一致",
                txn_count=5,
                fail_codes=["C1", "C2", "C3"],
            ),
            notes=FORGERY_LABELS["content_row_deleted"],
        ),
        SampleCase(
            id="forged_page_splice_icbc",
            path=_relative(splice_path, root),
            layout="icbc",
            forgery="content_page_splice",
            expectation=SampleExpectation(
                verdict="存在不一致",
                txn_count=6,
                fail_codes=["C1"],
            ),
            notes=FORGERY_LABELS["content_page_splice"],
        ),
        SampleCase(
            id="forged_duplicate_ref_icbc",
            path=_relative(duplicate_path, root),
            layout="icbc",
            forgery="content_duplicate_reference",
            expectation=SampleExpectation(
                verdict="存在不一致",
                txn_count=7,
                fail_codes=["C6", "C10"],
            ),
            notes=FORGERY_LABELS["content_duplicate_reference"],
        ),
    ]

    manifest = SampleManifest(cases=cases)
    (root / "manifest.json").write_text(
        json.dumps(manifest.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return load_samples(root)


def load_manifest(directory: str | Path) -> SampleManifest:
    path = Path(directory) / "manifest.json"
    if not path.is_file():
        raise FileNotFoundError(f"样本清单不存在：{path}")
    return SampleManifest.model_validate_json(path.read_text(encoding="utf-8"))


def validate_manifest(
    manifest: SampleManifest,
    directory: str | Path,
    *,
    require_coverage: bool = True,
) -> None:
    root = Path(directory).resolve()
    issues: list[str] = []
    seen: set[str] = set()

    for case in manifest.cases:
        if case.id in seen:
            issues.append(f"样本 id 重复：{case.id}")
        seen.add(case.id)
        target = (root / case.path).resolve()
        if not target.is_relative_to(root):
            issues.append(f"{case.id} 路径越界：{case.path}")
        elif not target.is_file():
            issues.append(f"{case.id} 文件不存在：{case.path}")

    if require_coverage:
        layouts = {case.layout for case in manifest.cases}
        missing_layouts = [code for code in SAMPLE_LAYOUTS if code not in layouts]
        if missing_layouts:
            issues.append("缺少版式：" + "、".join(missing_layouts))
        forgeries = {case.forgery for case in manifest.cases if case.forgery}
        missing_forgeries = [code for code in SAMPLE_FORGERY_TYPES if code not in forgeries]
        if missing_forgeries:
            issues.append("缺少伪造类型：" + "、".join(missing_forgeries))

    if issues:
        raise ValueError("样本清单不合法：" + "；".join(issues))


def load_samples(
    directory: str | Path,
    *,
    require_coverage: bool = True,
) -> list[LoadedSample]:
    root = Path(directory).resolve()
    manifest = load_manifest(root)
    validate_manifest(manifest, root, require_coverage=require_coverage)
    return [
        LoadedSample(case=case, path=(root / case.path).resolve())
        for case in manifest.cases
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成或检查算法样本集")
    parser.add_argument(
        "--out",
        default="algorithm/inputs/samples/synthetic",
        help="样本目录，默认 algorithm/inputs/samples/synthetic",
    )
    parser.add_argument("--check", action="store_true", help="只校验清单与文件，不重新生成")
    args = parser.parse_args(argv)

    directory = Path(args.out)
    samples = load_samples(directory) if args.check else build_sample_set(directory)
    print(f"样本目录：{directory}，共 {len(samples)} 份")
    for sample in samples:
        case = sample.case
        forgery = case.forgery or "-"
        print(f"{case.id}\t{case.layout}\t{forgery}\t{case.expectation.verdict}\t{sample.path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
