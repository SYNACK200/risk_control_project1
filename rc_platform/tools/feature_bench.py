"""AL-106：46 个内置特征的耗时/内存基线。

用法：python -m rc_platform.tools.feature_bench [--rows 20000]
只跑纯计算，不含解析；金额一律 Decimal，不引入 float。
"""
from __future__ import annotations

import argparse
import time
import tracemalloc
from decimal import Decimal

from ..capabilities.features.defs import BUILTIN_FEATURES, compute, evaluate
from ..core.contracts import Statement, TxnRow


def make_rows(n: int) -> list[TxnRow]:
    rows: list[TxnRow] = []
    for index in range(n):
        month = index % 12 + 1
        day = index % 28 + 1
        direction = "in" if index % 3 == 0 else "out"
        amount = Decimal("100.00") + Decimal(index % 500) * Decimal("17.35")
        rows.append(
            TxnRow(
                txn_date=f"2025-{month:02d}-{day:02d}",
                trade_time=f"{index % 24:02d}:{index % 60:02d}:00",
                direction=direction,
                amount=amount,
                balance=Decimal("50000.00") - Decimal(index) * Decimal("0.73"),
                summary="工资" if index % 17 == 0 else "消费",
                counterparty_name=f"对手方{index % 50}",
                page_no=index // 40,
                row_no=index + 1,
            )
        )
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="跑 46 个特征的耗时/内存基线")
    parser.add_argument("--rows", type=int, default=20000)
    args = parser.parse_args(argv)

    rows = make_rows(args.rows)
    statement = Statement(rows=rows)

    tracemalloc.start()
    started = time.perf_counter()
    compute(BUILTIN_FEATURES, statement)
    total_ms = (time.perf_counter() - started) * 1000
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    timings: list[tuple[str, float]] = []
    for definition in BUILTIN_FEATURES:
        started = time.perf_counter()
        evaluate(definition, rows)
        timings.append((definition.code, (time.perf_counter() - started) * 1000))
    timings.sort(key=lambda item: item[1], reverse=True)

    print(f"行数：{args.rows}")
    print(f"46 特征总耗时：{total_ms:.1f} ms")
    print(f"峰值内存：{peak / 1024 / 1024:.1f} MiB")
    print("单特征最慢前 5：")
    for code, elapsed in timings[:5]:
        print(f"  {code}: {elapsed:.1f} ms")
    slow = [item for item in timings if item[1] > 200]
    print("超过 200ms：" + ("、".join(f"{code} {elapsed:.1f}ms" for code, elapsed in slow) or "无"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())