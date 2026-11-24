"""模板智能字段分析（短字段就近匹配 + 标题字段版式分析）回归测试。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # 移到 backend/tests 后要上跳两级才是仓库根
sys.path.insert(0, str(ROOT / "backend"))

from services.template_analyzer import analyze_template_fields  # noqa: E402

DEFAULT_SHORT = [
    {"field": "account_no", "label": "卡号/账号", "keywords": "卡号,账号,银行卡号,客户账号,账户"},
    {"field": "account_name", "label": "户名", "keywords": "户名,姓名,账户名,客户姓名,持卡人"},
    {"field": "period", "label": "起止日期", "keywords": "起止日期,查询日期,交易区间,交易时段,明细周期"},
    {"field": "bank_branch", "label": "开户行", "keywords": "开户行,开户网点,开户机构,网点"},
    {"field": "currency", "label": "币种", "keywords": "币种,货币,钞汇"},
]

DEFAULT_HEADER = [
    {"field": "txn_date", "label": "交易日期", "keywords": "交易日期,记账日期,交易时间,日期"},
    {"field": "summary", "label": "摘要", "keywords": "摘要,交易摘要,附言,用途,交易类型"},
    {"field": "amount", "label": "交易金额", "keywords": "交易金额,发生额,记账金额,金额,收入/支出"},
    {"field": "balance", "label": "账户余额", "keywords": "账户余额,余额,联机余额,当前余额"},
    {"field": "counterparty_name", "label": "对方户名", "keywords": "对方户名,对方账号与户名,对方姓名,对手信息,交易对手"},
]


class TemplateFieldAnalyzerTest(unittest.TestCase):
    def test_ccb_sample_pdf(self) -> None:
        pdf_path = ROOT / "流水文件" / "【建设银行】样例.pdf"
        self.assertTrue(pdf_path.exists(), f"missing sample: {pdf_path}")
        res = analyze_template_fields(
            pdf_path.read_bytes(),
            DEFAULT_SHORT,
            DEFAULT_HEADER,
            filename=pdf_path.name,
        )
        self.assertEqual(res["bank_code"], "CCB")
        self.assertTrue(res["header_found"])
        self.assertGreaterEqual(len(res["preview_rows"]), 5)

        short_by_key = {x["field"]: x for x in res["short_results"]}
        self.assertTrue(short_by_key["account_no"]["matched"])
        self.assertIn("6217007200066562177", short_by_key["account_no"]["value"])
        self.assertTrue(short_by_key["account_name"]["matched"])
        self.assertIn("刘先生", short_by_key["account_name"]["value"])
        self.assertIsNotNone(short_by_key["account_no"]["rect"])

        hdr_by_key = {x["field"]: x for x in res["header_results"]}
        for k in ("txn_date", "summary", "amount", "balance", "counterparty_name"):
            self.assertTrue(hdr_by_key[k]["matched"], f"CCB header missing: {k}")
            self.assertIsNotNone(hdr_by_key[k]["x"])
            self.assertIsNotNone(hdr_by_key[k]["w"])
        self.assertEqual(res["layout"]["page_base"], 0)
        self.assertTrue(res["layout"]["tables"])
        self.assertTrue(res["layout"]["meta_boxes"])

    def test_cgb_sample_pdf_and_no_alipay_false_positive(self) -> None:
        pdf_path = ROOT / "流水文件" / "【广发银行】样例.pdf"
        self.assertTrue(pdf_path.exists(), f"missing sample: {pdf_path}")
        res = analyze_template_fields(
            pdf_path.read_bytes(),
            DEFAULT_SHORT,
            DEFAULT_HEADER,
            filename=pdf_path.name,
        )
        # 即使交易摘要里出现“支付宝”，也不应误判为 ALIPAY，而应通过文件名识别为 CGB
        self.assertEqual(res["bank_code"], "CGB")
        self.assertTrue(res["header_found"])
        self.assertGreaterEqual(len(res["preview_rows"]), 5)

        short_by_key = {x["field"]: x for x in res["short_results"]}
        self.assertTrue(short_by_key["account_no"]["matched"])
        self.assertIn("6214620621009423843", short_by_key["account_no"]["value"])
        self.assertEqual(short_by_key["account_no"]["method"], "right_neighbor")
        self.assertTrue(short_by_key["account_name"]["matched"])
        self.assertIn("王小二", short_by_key["account_name"]["value"])

        for k in ("txn_date", "summary", "amount", "balance", "counterparty_name"):
            self.assertIn(k, res["field_map"])

    def test_icbc_synthetic_pdf_and_custom_fields(self) -> None:
        pdf_path = ROOT / "algorithm" / "inputs" / "samples" / "synthetic" / "clean" / "icbc.pdf"
        self.assertTrue(pdf_path.exists(), f"missing sample: {pdf_path}")
        res = analyze_template_fields(
            pdf_path.read_bytes(),
            DEFAULT_SHORT,
            DEFAULT_HEADER,
            filename=pdf_path.name,
        )
        self.assertTrue(res["header_found"])
        self.assertGreaterEqual(len(res["field_map"]), 4)
        self.assertGreaterEqual(len(res["preview_rows"]), 2)

    def test_explicit_bank_code_override(self) -> None:
        pdf_path = ROOT / "流水文件" / "【建设银行】样例.pdf"
        res = analyze_template_fields(
            pdf_path.read_bytes(),
            DEFAULT_SHORT[:2],
            DEFAULT_HEADER[:3],
            bank_code="custom_bank",
            filename="sample.pdf",
        )
        self.assertEqual(res["bank_code"], "CUSTOM_BANK")
        self.assertEqual(len(res["short_results"]), 2)
        self.assertEqual(len(res["header_results"]), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
