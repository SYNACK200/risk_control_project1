# -*- coding: utf-8 -*-
"""第一批修复（T1–T7）全量内部回归验证测试套件。"""
from __future__ import annotations

import datetime
import json
import py_compile
import sys
import types
import unittest
from decimal import Decimal
from pathlib import Path

# 路径按本文件位置推导：原脚本写死了作者沙箱的绝对路径，换机器就必然 FileNotFoundError
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# 本机装的是真 pymupdf：原来那段 fitz 桩会盖掉真模块，导致 PDF 回归用例直接失效。
# 只有在确实缺 pymupdf 的环境里才装桩。
try:  # pragma: no cover - 取决于运行环境
    import pymupdf  # noqa: F401
except ImportError:  # pragma: no cover
    fake_fitz = types.ModuleType("fitz")

    class _Rect:
        def __init__(self, x0, y0, x1, y1):
            self.x0, self.y0, self.x1, self.y1 = float(x0), float(y0), float(x1), float(y1)
            self.width = self.x1 - self.x0
            self.height = self.y1 - self.y0

    fake_fitz.Rect = _Rect
    sys.modules["fitz"] = fake_fitz
    sys.modules["pymupdf"] = fake_fitz

from algorithm.ocr.models import MetaBox, Template  # noqa: E402
from algorithm.ocr.table import (  # noqa: E402
    Word,
    apply_template,
    build_columns,
    build_columns_from_layout,
    canonical_field,
)
from algorithm.ocr.parse import (  # noqa: E402
    _clip_for_page,
    _layout_area_for,
    _layout_table_for,
    _parse_pdf_pages,
    _transactions_from_pages,
)
from rc_platform.capabilities.parse_v2.table_reader import _row_from_cells  # noqa: E402
from rc_platform.capabilities.layout.words import Word as RcWord  # noqa: E402
from backend.services.template_parse import build_template  # noqa: E402


class TestBatch1T1ToT7(unittest.TestCase):
    # ---- 语法编译检查 ----
    def test_00_py_compile_all_modified_python_files(self):
        py_files = [
            "algorithm/ocr/table.py",
            "algorithm/ocr/parse.py",
            "rc_platform/capabilities/parse_v2/table_reader.py",
            "backend/services/template_parse.py",
            "backend/routers/templates.py",
            "backend/services/task_runner.py",
            "backend/routers/tasks.py",
        ]
        for rel in py_files:
            py_compile.compile(str(ROOT / rel), doraise=True)

    # ---- T1: _extract_meta 合并同行完整词且不误框表格首行 ----
    def test_01_t1_extract_meta_merges_words_and_respects_header_y(self):
        # 直接加载 _extract_meta 与 _META_PATTERNS 而不依赖 sqlalchemy
        src = (ROOT / "backend/routers/templates.py").read_text(encoding="utf-8")
        ns: dict = {}
        start = src.index("_META_PATTERNS = [")
        end = src.index("@router.post(\"/decrypt\")")
        exec(src[start:end], ns)
        _extract_meta = ns["_extract_meta"]

        words = [
            # 页眉第 1 行 (y=40..52)
            {"x0": 40, "x1": 65, "top": 40, "bottom": 52, "text": "卡号"},
            {"x0": 70, "x1": 180, "top": 40, "bottom": 52, "text": "6222033202008237627"},
            {"x0": 210, "x1": 240, "top": 40, "bottom": 52, "text": "户名："},
            {"x0": 242, "x1": 280, "top": 40, "bottom": 52, "text": "张三"},
            {"x0": 320, "x1": 410, "top": 40, "bottom": 52, "text": "起止日期：2026-04-14"},
            {"x0": 415, "x1": 425, "top": 40, "bottom": 52, "text": "—"},
            {"x0": 430, "x1": 490, "top": 40, "bottom": 52, "text": "2026-10-14"},
            # 表头行在 y=100..112，表格首行在 y=120..132 含 "人民币"
            {"x0": 220, "x1": 250, "top": 120, "bottom": 132, "text": "人民币"},
        ]
        meta = _extract_meta("ignored", words, 600.0, 800.0, header_y=100.0)
        # 账号框应完整覆盖 40..180（而不是仅 40..65）
        self.assertIn("account_no", meta)
        self.assertAlmostEqual(meta["account_no"]["rect"]["x"], 40 / 600.0, places=3)
        self.assertAlmostEqual(meta["account_no"]["rect"]["w"], 140 / 600.0, places=3)
        # 交易期间框应完整覆盖 320..490（含结束日期）
        self.assertIn("period", meta)
        self.assertAlmostEqual(meta["period"]["rect"]["x"], 320 / 600.0, places=3)
        self.assertAlmostEqual(meta["period"]["rect"]["w"], 170 / 600.0, places=3)
        # 表格首行的“人民币”在 header_y=100 之下，不应被误框为页眉币种
        self.assertNotIn("currency", meta)

    # ---- T2: counterparty_name 与 counterparty 贯通 ----
    def test_02_t2_counterparty_name_normalization(self):
        self.assertEqual(canonical_field("counterparty_name"), "counterparty")
        tokens = [
            Word("交易日期", 10, 60, 100, 110),
            Word("对方户名", 100, 160, 100, 110),
            Word("发生额", 200, 260, 100, 110),
            Word("余额", 300, 360, 100, 110),
        ]
        mapping = apply_template(tokens, {0: "txn_date", 1: "counterparty", 2: "amount", 3: "balance"},
                                 {"counterparty_name": "对方户名"})
        self.assertEqual(mapping[1], "counterparty")

        layout = {
            "page_size": {"w": 500.0, "h": 800.0},
            "tables": [{
                "page": 0, "slot": "first",
                "area": {"x": 0.0, "y": 0.1, "w": 1.0, "h": 0.8},
                "headerY": 0.15,
                "columns": [
                    {"field": "txn_date", "x": 0.0, "w": 0.18},
                    {"field": "counterparty_name", "x": 0.18, "w": 0.20},
                    {"field": "amount", "x": 0.38, "w": 0.20},
                    {"field": "balance", "x": 0.58, "w": 0.20},
                ],
            }],
        }
        cols = build_columns(tokens, mapping, layout=layout, page_no=0, total_pages=1)
        cp_col = [c for c in cols if c.field == "counterparty"][0]
        self.assertAlmostEqual(cp_col.left, 90.0)
        self.assertAlmostEqual(cp_col.right, 190.0)

        # template_parse 归一化
        pt = build_template(bank_code="ICBC", version=1,
                            field_map={"counterparty_name": "对方户名"}, layout=layout)
        self.assertIn("counterparty", pt.field_map)
        self.assertNotIn("counterparty_name", pt.field_map)

        # parse_v2 table_reader 兼容 counterparty_name 且不漏进 extra
        row = _row_from_cells({
            "txn_date": [RcWord("2026-05-01", 10, 50, 200, 210)],
            "counterparty_name": [RcWord("字节跳动", 100, 150, 200, 210)],
            "amount": [RcWord("1000.00", 200, 250, 200, 210)],
            "balance": [RcWord("5000.00", 300, 350, 200, 210)],
        }, page_no=1, row_no=1)
        self.assertIsNotNone(row)
        self.assertEqual(row.counterparty_name, "字节跳动")
        self.assertIsNone(row.extra)

        # 主解析 _transactions_from_pages 端到端验证
        page_words = tokens + [
            Word("2026-05-01", 10, 60, 140, 150),
            Word("华为技术有限公司", 100, 170, 140, 150),
            Word("+5000.00", 200, 260, 140, 150),
            Word("15000.00", 300, 360, 140, 150),
        ]
        txns, _, _, _ = _transactions_from_pages([(1, page_words)], pt, [])
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].counterparty_name, "华为技术有限公司")
        self.assertIsNone(txns[0].extra)

    # ---- T3: 页眉单值框（meta_boxes）不被表格区提前裁掉 ----
    def test_03_t3_meta_boxes_preserved_above_table_area(self):
        layout = {
            "page_size": {"w": 600.0, "h": 800.0},
            "tables": [{
                "page": 0, "slot": "first",
                # 表格区从 y=0.35 开始（0.35 - 0.12 = 0.23，旧逻辑会裁掉 y=0.05 处的页眉！）
                "area": {"x": 0.05, "y": 0.35, "w": 0.90, "h": 0.60},
                "headerY": 0.38,
                "columns": [
                    {"field": "txn_date", "x": 0.05, "w": 0.20},
                    {"field": "summary", "x": 0.25, "w": 0.25},
                    {"field": "amount", "x": 0.50, "w": 0.20},
                    {"field": "balance", "x": 0.70, "w": 0.20},
                ],
            }],
        }
        mboxes = [
            MetaBox(field="account_no", page=1, x=0.05, y=0.04, w=0.30, h=0.04),
            MetaBox(field="bank_branch", page=1, x=0.40, y=0.04, w=0.30, h=0.04),
        ]
        rect = sys.modules["fitz"].Rect(0, 0, 600, 800)
        clip = _clip_for_page(layout, 0, rect, total_pages=1, meta_boxes=mboxes)
        self.assertIsNotNone(clip)
        self.assertEqual(clip.y0, 0.0)

        tmpl = Template(
            bank_code="ICBC", version=1, field_map={}, layout=layout,
            meta_boxes=mboxes, page_size=(600.0, 800.0),
        )
        words = [
            # 页眉单值在 y=40 (0.05 * 800)，远高于 table area y=280 (0.35 * 800)
            Word("6222021001123456789", 50, 180, 36, 48),
            Word("北京朝阳支行", 260, 360, 36, 48),
            # 表头与交易行
            Word("交易日期", 40, 100, 290, 300),
            Word("摘要", 160, 220, 290, 300),
            Word("发生额", 310, 370, 290, 300),
            Word("余额", 430, 490, 290, 300),
            Word("2026-06-01", 40, 100, 320, 330),
            Word("工资", 160, 220, 320, 330),
            Word("+8000.00", 310, 370, 320, 330),
            Word("18000.00", 430, 490, 320, 330),
        ]
        txns, _, _, headers = _transactions_from_pages([(1, words)], tmpl, [])
        self.assertEqual(len(txns), 1)
        self.assertEqual(headers[0].account_no.value, "6222021001123456789")
        self.assertEqual(headers[0].bank_branch.value, "北京朝阳支行")

    # ---- T4: GET /templates 返回 deleted_at ----
    def test_04_t4_list_templates_includes_deleted_at(self):
        src = (ROOT / "backend/routers/templates.py").read_text(encoding="utf-8")
        self.assertIn('"deleted_at": t.deleted_at.isoformat() if t.deleted_at else None', src)

    # ---- T5: 多页槽位 middle / auto 与按页独立列几何 ----
    def test_05_t5_multipage_slots_and_per_page_columns(self):
        layout = {
            "page_size": {"w": 1000.0, "h": 1000.0},
            "tables": [
                {
                    "page": 0, "slot": "first",
                    "area": {"x": 0.0, "y": 0.2, "w": 1.0, "h": 0.7},
                    "columns": [{"field": "amount", "x": 0.50, "w": 0.10}],
                },
                {
                    "page": 1, "slot": "middle",
                    "area": {"x": 0.0, "y": 0.05, "w": 1.0, "h": 0.9},
                    "columns": [{"field": "amount", "x": 0.70, "w": 0.10}],
                },
                {
                    "page": 99, "slot": "last",
                    "area": {"x": 0.0, "y": 0.05, "w": 1.0, "h": 0.5},
                    "columns": [{"field": "amount", "x": 0.80, "w": 0.10}],
                },
            ],
        }
        # 5 页文档：第 0 页->first，第 1/2/3 页->middle，第 4 页->last
        self.assertEqual(_layout_table_for(layout, 0, 5)["slot"], "first")
        self.assertEqual(_layout_table_for(layout, 1, 5)["slot"], "middle")
        self.assertEqual(_layout_table_for(layout, 2, 5)["slot"], "middle")
        self.assertEqual(_layout_table_for(layout, 3, 5)["slot"], "middle")
        self.assertEqual(_layout_table_for(layout, 4, 5)["slot"], "last")

        # 验证 build_columns 不再把第 2 页拍平到第 0 页的列几何
        tokens = [Word("发生额", 520, 560, 100, 110)]
        cols_p0 = build_columns(tokens, {0: "amount"}, layout=layout, page_no=0, total_pages=5)
        cols_p2 = build_columns(tokens, {0: "amount"}, layout=layout, page_no=2, total_pages=5)
        cols_p4 = build_columns(tokens, {0: "amount"}, layout=layout, page_no=4, total_pages=5)
        self.assertAlmostEqual(cols_p0[0].left, 500.0)
        self.assertAlmostEqual(cols_p2[0].left, 700.0)
        self.assertAlmostEqual(cols_p4[0].left, 800.0)

        # 验证 auto 槽位可兜底任意页
        auto_layout = {
            "page_size": {"w": 1000.0, "h": 1000.0},
            "tables": [{"page": 0, "slot": "auto", "area": {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}}],
        }
        self.assertIsNotNone(_layout_area_for(auto_layout, 3, 5))

    # ---- T6: 临时模板构建 layout 且用后清空 / reanalyze 清空 ----
    def test_06_t6_temp_template_layout_and_cleanup(self):
        tr_src = (ROOT / "backend/services/task_runner.py").read_text(encoding="utf-8")
        tasks_src = (ROOT / "backend/routers/tasks.py").read_text(encoding="utf-8")
        self.assertIn("built_layout = tlayout.build_layout(", tr_src)
        self.assertIn('"layout": built_layout', tr_src)
        self.assertIn("task.field_map_override = None", tr_src)
        self.assertIn("task.field_map_override = None", tasks_src)

    # ---- T7: 表头 OCR 失败时按 headerY + layout.columns 兜底解析 ----
    def test_07_t7_header_y_fallback_without_detected_header(self):
        layout = {
            "page_size": {"w": 600.0, "h": 800.0},
            "tables": [{
                "page": 0, "slot": "first",
                "area": {"x": 0.0, "y": 0.10, "w": 1.0, "h": 0.85},
                "headerY": 0.20,  # 160pt：160pt 之上的噪声/乱码表头应被跳过，之下按列框解析
                "columns": [
                    {"field": "txn_date", "x": 0.05, "w": 0.20},
                    {"field": "summary", "x": 0.25, "w": 0.25},
                    {"field": "amount", "x": 0.50, "w": 0.20},
                    {"field": "balance", "x": 0.70, "w": 0.25},
                ],
            }],
        }
        tmpl = Template(bank_code="CUSTOM", version=1, field_map={}, layout=layout)
        words = [
            # 表头行 OCR 严重乱码（find_header 必返回 None），位于 y=130..145 (< 160)
            Word("乱码一", 40, 90, 130, 145),
            Word("乱码二", 170, 220, 130, 145),
            # 160pt 之上的干扰日期行（应被 headerY 过滤掉）
            Word("2026-01-01", 40, 100, 110, 120),
            Word("打印日期", 170, 230, 110, 120),
            # 160pt 之下的真实交易行
            Word("2026-07-15", 40, 100, 180, 192),
            Word("网银转账", 170, 230, 180, 192),
            Word("-250.50", 320, 380, 180, 192),
            Word("9749.50", 450, 520, 180, 192),
        ]
        warnings: list[str] = []
        txns, _, _, _ = _transactions_from_pages([(1, words)], tmpl, warnings)
        self.assertEqual(len(txns), 1)
        self.assertEqual(str(txns[0].txn_date), "2026-07-15")
        self.assertEqual(txns[0].amount, Decimal("250.50"))
        self.assertEqual(txns[0].direction, "out")
        self.assertEqual(txns[0].balance, Decimal("9749.50"))
        self.assertEqual(warnings, [])

    # ---- 真实样例 PDF 端到端回归（pdfplumber） ----
    def test_08_real_pdf_samples_regression(self):
        import pdfplumber

        sample = ROOT / "algorithm/inputs/samples/synthetic/clean/icbc.pdf"
        self.assertTrue(sample.exists())
        with pdfplumber.open(sample) as pdf:
            txns, footer_count, summaries, headers = _parse_pdf_pages(pdf, None, [])
        self.assertGreater(len(txns), 5)
        self.assertTrue(any(t.amount is not None for t in txns))


if __name__ == "__main__":
    unittest.main(verbosity=2)
