from decimal import Decimal

from algorithm.ocr.models import Transaction
from algorithm.algo.merge import AccountInput, merge_accounts


def txn(day: str, direction: str, amount: str, summary: str = "消费"):
    return Transaction(page_no=1, row_no=1, txn_date=day, direction=direction,
                       amount=Decimal(amount), summary=summary)


def account(aid: str, txns):
    return AccountInput(account_id=aid, bank_code="ICBC", period_start=None,
                        period_end=None, transactions=txns)


def test_sum_keeps_all_transactions():
    accounts = [
        account("A", [txn("2026-01-05", "in", "1000"), txn("2026-01-06", "out", "200")]),
        account("B", [txn("2026-01-07", "in", "500"), txn("2026-01-08", "out", "100")]),
    ]
    result = merge_accounts(accounts, "sum")
    assert result["txn_count"] == 4
    assert result["dropped_duplicates"] == 0
    assert [a["txn_count"] for a in result["accounts"]] == [2, 2]


def test_dedupe_drops_identical_transactions():
    same = txn("2026-01-05", "in", "1000", "工资")
    accounts = [account("A", [same]), account("B", [same])]
    result = merge_accounts(accounts, "dedupe")
    assert result["txn_count"] == 1
    assert result["dropped_duplicates"] == 1


def test_net_internal_cancels_account_transfer_pair():
    accounts = [
        account("A", [txn("2026-01-05", "out", "1000", "转出"), txn("2026-01-09", "in", "3000", "工资")]),
        account("B", [txn("2026-01-06", "in", "1000", "转入")]),
    ]
    result = merge_accounts(accounts, "net_internal")
    assert len(result["internal_transfers"]) == 1
    assert result["txn_count"] == 1
    assert result["internal_transfers"][0]["from"] == "A"
    assert result["internal_transfers"][0]["to"] == "B"


def test_worst_case_takes_max_for_risk_metric():
    accounts = [
        account("A", [txn("2026-01-05", "in", "10000", "工资")]),
        account("B", [txn("2026-01-05", "in", "1000", "工资"),
                      txn("2026-01-06", "out", "900", "借呗还款")]),
    ]
    result = merge_accounts(accounts, "worst_case")
    values = {m["code"]: m["value"] for m in result["metrics"]}
    assert values["B05"] == "1"


def test_convex_is_sqrt_sum_squares():
    accounts = [
        account("A", [txn("2026-01-05", "in", "3000", "工资")]),
        account("B", [txn("2026-01-05", "in", "4000", "工资")]),
    ]
    result = merge_accounts(accounts, "convex")
    values = {m["code"]: m["value"] for m in result["metrics"]}
    assert values["A01"] == "5000.0"  # sqrt(3000^2 + 4000^2)


def test_weights_default_to_equal_for_weighted():
    accounts = [
        account("A", [txn("2026-01-05", "in", "2000", "工资")]),
        account("B", [txn("2026-01-05", "in", "4000", "工资")]),
    ]
    result = merge_accounts(accounts, "weighted")
    values = {m["code"]: m["value"] for m in result["metrics"]}
    assert values["A01"] == "3000.00"

