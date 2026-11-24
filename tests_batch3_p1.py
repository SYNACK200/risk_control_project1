# -*- coding: utf-8 -*-
"""第三批修复（T8–T13 + B7–B12 + F8–F13）全量内部回归验证测试套件。"""
from __future__ import annotations

import py_compile
import sys
import types
import unittest
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # 原脚本写死作者沙箱绝对路径，换机器必 FileNotFoundError
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))

# 本机装了真 pymupdf：桩只在确实缺它时才装，否则会盖掉真模块
try:  # pragma: no cover
    import pymupdf  # noqa: F401
except ImportError:  # pragma: no cover
    fake_fitz = types.ModuleType("pymupdf")
    sys.modules["pymupdf"] = fake_fitz
    sys.modules["fitz"] = fake_fitz

from backend.services.custom_metric_eval import _to_view  # noqa: E402
from backend.services.template_match import compute_layout_hash, header_jaccard, pick_best_template  # noqa: E402
from backend.services.template_parse import build_template  # noqa: E402


class TestBatch3P1(unittest.TestCase):
    def test_00_py_compile_all_batch3_python_files(self):
        py_files = [
            "backend/services/custom_metric_eval.py",
            "backend/services/template_parse.py",
            "backend/services/template_match.py",
            "algorithm/ocr/parse.py",
            "backend/routers/templates.py",
            "backend/services/template_layout.py",
            "backend/routers/tasks.py",
            "rc_platform/api/app.py",
            "backend/routers/reports.py",
            "backend/routers/auth.py",
            "backend/services/ocr_routing.py",
            "backend/services/verify.py",
        ]
        for rel in py_files:
            py_compile.compile(str(ROOT / rel), doraise=True)

    # ---- T9: layout_hash 与表头 Jaccard 匹配 ----
    def test_01_t9_template_jaccard_and_hash_matching(self):
        @dataclass
        class _Tpl:
            id: int
            layout: dict
            header_columns: list[str]
            field_map: dict

        h1 = ["交易日期", "摘要", "收入/支出金额", "余额", "对方户名"]
        h2 = ["记账日", "交易类型", "借方发生额", "贷方发生额", "账户余额"]
        t1 = _Tpl(1, {"layout_hash": compute_layout_hash(h1)}, h1, {})
        t2 = _Tpl(2, {"layout_hash": compute_layout_hash(h2)}, h2, {})

        matched, score, reason = pick_best_template([t1, t2], h1)
        self.assertEqual(matched.id, 1)
        self.assertEqual(score, 1.0)
        self.assertEqual(reason, "layout_hash_exact")

        # 轻微变动仍满足 Jaccard >= 0.6
        matched2, score2, reason2 = pick_best_template([t1, t2], ["交易日期", "摘要", "收入/支出金额", "余额"])
        self.assertEqual(matched2.id, 1)
        self.assertGreaterEqual(score2, 0.6)
        self.assertEqual(reason2, "header_jaccard_match")

        # 完全不匹配且多模板时返回 None
        matched3, score3, reason3 = pick_best_template([t1, t2], ["未知A", "未知B", "未知C"])
        self.assertIsNone(matched3)
        self.assertEqual(reason3, "jaccard_below_threshold")

    # ---- T10: page_base=0 时仅第 2 页画单值框不误判为 1-based ----
    def test_02_t10_meta_box_page_base_zero_second_page(self):
        pt = build_template(
            bank_code="ICBC",
            version=1,
            field_map={},
            layout={
                "page_base": 0,
                "page_size": {"w": 600, "h": 800},
                "meta_boxes": [{"field": "account_no", "page": 1, "x": 0.1, "y": 0.05, "w": 0.2, "h": 0.03}],
            },
        )
        # 0-based page=1 -> 1-based page=2
        self.assertEqual(pt.meta_boxes[0].page, 2)

    # ---- B7: custom_metric_eval 读取 counterparty_name ----
    def test_03_b7_custom_metric_eval_counterparty_name(self):
        @dataclass
        class _Txn:
            txn_date: str
            amount: Decimal
            balance: Decimal
            direction: str
            counterparty_name: str
            summary: str

        views = _to_view([_Txn("2026-05-01", Decimal("100"), Decimal("500"), "in", "招商证券", "转账")])
        self.assertEqual(views[0]["counterparty"], "招商证券")

    # ---- B10: API Key 加密/解密与明文向后兼容 ----
    def test_04_b10_api_key_encryption_roundtrip(self):
        src = (ROOT / "backend/services/ocr_routing.py").read_text(encoding="utf-8")
        ns: dict = {"base64": __import__("base64"), "hashlib": __import__("hashlib")}
        start = src.index("_ENC_PREFIX = ")
        end = src.index("def get_config(")
        exec(src[start:end], ns)
        enc = ns["encrypt_api_key"]("sk-secret-token-2026")
        self.assertTrue(enc.startswith("enc:v1:"))
        self.assertNotIn("sk-secret-token-2026", enc)
        self.assertEqual(ns["decrypt_api_key"](enc), "sk-secret-token-2026")
        self.assertEqual(ns["decrypt_api_key"]("legacy-plain-key"), "legacy-plain-key")

    # ---- T11 + B8 + B9 + B10 + B11 + B12 静态契约验证 ----
    def test_05_backend_p1_contracts(self):
        tpl_src = (ROOT / "backend/routers/templates.py").read_text(encoding="utf-8")
        self.assertIn('if save_draft and not result["valid"] and not allow_invalid:', tpl_src)

        tasks_src = (ROOT / "backend/routers/tasks.py").read_text(encoding="utf-8")
        self.assertIn('action="report.export"', tasks_src)
        self.assertIn("files_deleted", tasks_src)
        self.assertIn("is_password_protected(data)", tasks_src)

        rep_src = (ROOT / "backend/routers/reports.py").read_text(encoding="utf-8")
        self.assertIn("allow_trashed_for_banker=True", rep_src)
        self.assertIn('@router.post("/reports/{task_id}/export"', rep_src)

        auth_src = (ROOT / "backend/routers/auth.py").read_text(encoding="utf-8")
        self.assertIn("_check_login_rate(uname)", auth_src)
        self.assertIn('User.status == "active"', auth_src)
        self.assertIn("def list_users(user: User = Depends(require_admin)", auth_src)

        ver_src = (ROOT / "backend/services/verify.py").read_text(encoding="utf-8")
        self.assertIn("cloud_enabled", ver_src)
        self.assertIn('"status": "skipped"', ver_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
