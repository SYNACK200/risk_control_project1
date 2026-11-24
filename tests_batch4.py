# -*- coding: utf-8 -*-
"""第四批修复（B1 / B2+F7 / T14 / B14 / F14）全量内部回归验证测试套件。"""
from __future__ import annotations

import py_compile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent  # 原脚本写死作者沙箱绝对路径，换机器必 FileNotFoundError


class TestBatch4(unittest.TestCase):
    def test_00_py_compile_all_batch4_python_files(self):
        py_files = [
            "backend/routers/queue.py",
            "backend/main.py",
            "backend/services/analysis.py",
            "backend/routers/templates.py",
            "backend/routers/tasks.py",
            "backend/routers/dashboard.py",
            "backend/services/task_runner.py",
        ]
        for rel in py_files:
            py_compile.compile(str(ROOT / rel), doraise=True)

    def test_01_b1_rc_platform_fallback_wired_in_analysis(self):
        src = (ROOT / "backend/services/analysis.py").read_text(encoding="utf-8")
        self.assertIn("import os\n", src)
        self.assertIn('PIPELINE_BACKEND', src)
        self.assertIn("rc_platform.capabilities.layout.detect", src)
        self.assertIn("rc_platform.capabilities.parse_v2.table_reader", src)
        self.assertIn('"pipeline_backend": pipeline_backend', src)

    def test_02_b2_f7_queue_router_and_page(self):
        q_src = (ROOT / "backend/routers/queue.py").read_text(encoding="utf-8")
        for ep in ('@router.get("/stats")', '@router.get("/jobs")', '@router.post("/jobs/{task_id}/retry")', '@router.post("/jobs/{task_id}/cancel")'):
            self.assertIn(ep, q_src)
        main_src = (ROOT / "backend/main.py").read_text(encoding="utf-8")
        self.assertIn("app.include_router(queue.router, prefix=settings.api_prefix)", main_src)
        page_src = (ROOT / "web/src/pages/banker/QueuePage.tsx").read_text(encoding="utf-8")
        self.assertIn("getQueueStats", page_src)
        self.assertIn("retryQueueJob", page_src)
        self.assertIn("cancelQueueJob", page_src)
        app_src = (ROOT / "web/src/pages/banker/BankerApp.tsx").read_text(encoding="utf-8")
        self.assertIn('path="queue"', app_src)

    def test_03_b14_upload_limit_dashboard_dedup_report_version(self):
        tasks_src = (ROOT / "backend/routers/tasks.py").read_text(encoding="utf-8")
        self.assertIn("if len(data) > MAX_UPLOAD_BYTES:", tasks_src)
        dash_src = (ROOT / "backend/routers/dashboard.py").read_text(encoding="utf-8")
        self.assertIn("seen_codes: dict[str, str] = {}", dash_src)
        tr_src = (ROOT / "backend/services/task_runner.py").read_text(encoding="utf-8")
        self.assertIn("version=int(prev_ver) + 1", tr_src)
        self.assertNotIn("session.query(Report).filter(Report.task_id == task.id).delete()", tr_src)

    def test_04_t14_f14_frontend_and_template_stats(self):
        tpl_src = (ROOT / "backend/routers/templates.py").read_text(encoding="utf-8")
        self.assertIn('"tasks_total": tot', tpl_src)
        self.assertIn('"success_rate":', tpl_src)

        upload_src = (ROOT / "web/src/pages/borrower/UploadPage.tsx").read_text(encoding="utf-8")
        self.assertNotIn("components/annotate/types", upload_src)
        self.assertIn("from '../../lib/banks'", upload_src)

        landing_src = (ROOT / "web/src/pages/public/LandingPage.tsx").read_text(encoding="utf-8")
        self.assertIn("user?.role === 'banker' ? '/bank' : '/login?role=banker'", landing_src)

        login_src = (ROOT / "web/src/pages/public/LoginPage.tsx").read_text(encoding="utf-8")
        self.assertIn("忘记密码？请联系银行系统管理员协助重置", login_src)

        banker_src = (ROOT / "web/src/pages/banker/BankerApp.tsx").read_text(encoding="utf-8")
        self.assertIn('isAdmin ? <AuditPage /> : <Navigate to="/bank" replace />', banker_src)
        self.assertIn('isAdmin ? <UsersPage /> : <Navigate to="/bank" replace />', banker_src)

        audit_src = (ROOT / "web/src/pages/banker/AuditPage.tsx").read_text(encoding="utf-8")
        # 审计页后来改成了服务端分页 + 动作筛选，断言跟着实际实现走
        self.assertIn("listAudit({ page, size: PAGE, action:", audit_src)

        lab_src = (ROOT / "web/src/api/lab.ts").read_text(encoding="utf-8")
        self.assertIn("requestBlob('/lab/sample-file?sample='", lab_src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
