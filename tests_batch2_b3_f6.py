# -*- coding: utf-8 -*-
"""第二批修复（B3–B6 + F1–F6）全量内部回归验证测试套件。"""
from __future__ import annotations

import ast
import datetime
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

# 本机装了真 pymupdf：桩只在确实缺它时才装，否则会把真模块盖掉、让影像件用例失效
try:  # pragma: no cover
    import pymupdf  # noqa: F401
except ImportError:  # pragma: no cover
    fake_fitz = types.ModuleType("pymupdf")
    sys.modules["pymupdf"] = fake_fitz
    sys.modules["fitz"] = fake_fitz

from algorithm.algo.self_check import run_self_check  # noqa: E402
from backend.services.workflow import transition  # noqa: E402
from backend.services import worker  # noqa: E402


@dataclass
class _FakeTxn:
    txn_date: datetime.date
    amount: Decimal
    balance: Decimal
    direction: str
    page_no: int = 1


class TestBatch2B3ToF6(unittest.TestCase):
    def test_00_py_compile_all_modified_python_files(self):
        py_files = [
            "backend/services/worker.py",
            "backend/services/verify_scheduler.py",
            "backend/services/workflow.py",
            "backend/routers/tasks.py",
            "backend/services/task_runner.py",
            "backend/services/ocr_api.py",
            "backend/routers/ocr_routing.py",
            "backend/services/analysis.py",
            "backend/main.py",
            "algorithm/algo/self_check.py",
        ]
        for rel in py_files:
            py_compile.compile(str(ROOT / rel), doraise=True)

    # ---- B3: worker.last_finished_at + verify_scheduler >50 条不卡死 ----
    def test_01_b3_worker_and_verify_scheduler(self):
        self.assertTrue(callable(worker.last_finished_at))
        self.assertIsInstance(worker.last_finished_at(), float)
        src = (ROOT / "backend/services/verify_scheduler.py").read_text(encoding="utf-8")
        self.assertIn("func.json_extract", src)
        self.assertIn("Report.id > last_id", src)
        self.assertIn("_fast_last_finished()", src)
        self.assertIn('"image"', src)

    # ---- B4: workflow 允许 NEED_SUPPLEMENT -> QUEUED，补件投递 worker 且 task_runner 读 task_file ----
    def test_02_b4_supplement_workflow_and_dispatch(self):
        class _T:
            status = "NEED_SUPPLEMENT"

        t = _T()
        transition(t, "QUEUED")
        self.assertEqual(t.status, "QUEUED")

        tasks_src = (ROOT / "backend/routers/tasks.py").read_text(encoding="utf-8")
        idx = tasks_src.index("def add_supplement(")
        fn_body = tasks_src[idx:]
        self.assertIn('transition(task, "QUEUED")', fn_body)
        self.assertIn("worker.submit_task(task.id)", fn_body)

        tr_src = (ROOT / "backend/services/task_runner.py").read_text(encoding="utf-8")
        self.assertIn("from db.models import TaskFile", tr_src)
        self.assertIn("TaskFile.seq.asc()", tr_src)

    # ---- B5: ocr_api.available(extra_key=...) + ocr_routing 接线 ----
    def test_03_b5_ocr_api_available_and_routing_wired(self):
        src = (ROOT / "backend/services/ocr_api.py").read_text(encoding="utf-8")
        # 抽离 available() 函数直接验证 extra_key 分支
        ns = {"CONF": Path("/nonexistent/paddle.json"), "os": __import__("os")}
        start = src.index("def available(")
        exec(src[start:], ns)
        available = ns["available"]
        self.assertTrue(available(extra_key="sk-live-test-key"))
        self.assertFalse(available(extra_key="   "))

        router_src = (ROOT / "backend/routers/ocr_routing.py").read_text(encoding="utf-8")
        self.assertIn("ocr_api.available(db=db, extra_key=payload.api_key)", router_src)
        self.assertIn("ocr_api.available(db=db)", router_src)

        tr_src = (ROOT / "backend/services/task_runner.py").read_text(encoding="utf-8")
        self.assertIn("_ocr_routing.should_use_api(session", tr_src)

    # ---- B6: backend/main.py 导入 HTTPException + 影像件 self_check 不崩溃 ----
    def test_04_b6_main_import_and_image_self_check(self):
        main_ast = ast.parse((ROOT / "backend/main.py").read_text(encoding="utf-8"))
        imported_fastapi = set()
        for node in ast.walk(main_ast):
            if isinstance(node, ast.ImportFrom) and node.module == "fastapi":
                imported_fastapi.update(a.name for a in node.names)
        self.assertIn("HTTPException", imported_fastapi)

        # 用真实 JPG 影像件验证 run_self_check 不抛 FileDataError / IndexError
        jpg_path = ROOT / "流水文件/微信图片_20261031192516_151_2.jpg"
        raw_jpg = jpg_path.read_bytes()
        txns = [
            _FakeTxn(datetime.date(2026, 10, 1), Decimal("100.00"), Decimal("1100.00"), "in"),
            _FakeTxn(datetime.date(2026, 10, 2), Decimal("50.00"), Decimal("1050.00"), "out"),
        ]
        res = run_self_check(raw_jpg, txns, footer_count=2)
        by_code = {item.code: item for item in res.items}
        for code in ("S1", "S2", "S3", "S4"):
            self.assertEqual(by_code[code].status, "limited")
        self.assertEqual(by_code["S5"].status, "pass")
        self.assertEqual(by_code["S6"].status, "pass")
        self.assertEqual(by_code["S7"].status, "pass")

    # ---- F1–F6: 前端关键契约断言 ----
    def test_05_f1_to_f6_frontend_contracts(self):
        client_src = (ROOT / "web/src/api/client.ts").read_text(encoding="utf-8")
        self.assertIn("isLoginReq = path.startsWith('/auth/login')", client_src)
        self.assertIn("typeof rawDetail === 'string'", client_src)

        errors_src = (ROOT / "web/src/api/errors.ts").read_text(encoding="utf-8")
        for code in ("E_FORBIDDEN", "E_EXISTS", "E_PARAM", "E_NO_CREDENTIAL", "E_EXPR", "E_OP"):
            self.assertIn(code, errors_src)

        report_src = (ROOT / "web/src/pages/banker/ReportPage.tsx").read_text(encoding="utf-8")
        self.assertIn("case 'passed':", report_src)
        self.assertIn("case 'discrepancy':", report_src)
        self.assertIn("report.trust?.score", report_src)
        self.assertIn("onPasswordRequired=", report_src)
        self.assertIn("isNormalizedCoord", report_src)

        entities_src = (ROOT / "web/src/pages/banker/EntitiesPage.tsx").read_text(encoding="utf-8")
        self.assertIn("normalizeMergeResult", entities_src)
        self.assertIn("formatMetricValue", entities_src)
        self.assertIn("holder_masked", entities_src)
        self.assertIn("}, []);", entities_src)

        banker_src = (ROOT / "web/src/pages/banker/BankerApp.tsx").read_text(encoding="utf-8")
        self.assertNotIn("/bank-old/", banker_src)
        self.assertNotIn("ComingSoon", banker_src)
        self.assertIn('path="ocr-routing"', banker_src)

        app_src = (ROOT / "web/src/App.tsx").read_text(encoding="utf-8")
        self.assertIn("LegacyHashRedirect", app_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
