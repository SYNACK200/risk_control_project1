"""指标口径对照：按映射表算出来的值 vs 旧实现的值。

用法：
    python -m rc_platform.tools.metric_parity

只要有一个「已映射」的指标对不上，退出码就是 1。
未映射的指标会单独列出并写明卡在哪，不算失败——它们是待办，不是错误。
"""
from __future__ import annotations

import pathlib
import sys
from decimal import Decimal

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _old_metrics(data: bytes) -> dict[str, str | None]:
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from services.analysis import run_analysis

    result = run_analysis(data)
    return {item["code"]: item["value"] for item in result["metrics"]}


def _new_metrics(data: bytes) -> dict[str, Decimal | None]:
    from rc_platform.capabilities.metrics.mapping import evaluate
    from rc_platform.core.context import JobContext
    from rc_platform.core.contracts import SourceDocument
    from rc_platform.core.pipeline import Pipeline
    from rc_platform.core.registry import default_registry

    registry = default_registry()
    result = Pipeline(registry, registry.plan("statement"), on_error="degrade").run(
        JobContext(), {"document": SourceDocument(data=data)}
    )
    statement = result.get("statement")
    return evaluate(statement) if statement else {}


def main(argv: list[str] | None = None) -> int:
    sample_dir = ROOT / "algorithm" / "inputs" / "samples" / "synthetic"
    files = sorted(sample_dir.rglob("*.pdf")) if sample_dir.exists() else []
    if not files:
        print("没有样本可对照", file=sys.stderr)
        return 2

    from rc_platform.capabilities.metrics.mapping import coverage, registry

    maps = {code: item for code, item in registry().items() if item.mapped}
    misses: dict[str, list[str]] = {code: [] for code in maps}
    checks = 0

    for path in files:
        data = path.read_bytes()
        old = _old_metrics(data)
        new = _new_metrics(data)
        for code, item in maps.items():
            checks += 1
            expected = old.get(code)
            actual = new.get(code)
            if expected is None and actual is None:
                continue
            left = None if expected in (None, "") else Decimal(str(expected)).quantize(Decimal(10) ** -item.scale)
            right = None if actual is None else actual.quantize(Decimal(10) ** -item.scale)
            if left != right:
                misses[code].append(f"{path.name}: 旧 {expected} / 新 {actual}")

    stats = coverage()
    print(f"映射覆盖：{stats['mapped']}/{stats['total']} 已映射，{stats['blocked']} 待办")
    print(f"对照次数：{checks}")
    print()
    print("已映射指标：")
    for code, item in sorted(maps.items()):
        state = "一致" if not misses[code] else f"不一致 {len(misses[code])} 次"
        print(f"  {code} {item.name:<12} {state}")
        for line in misses[code][:3]:
            print(f"      {line}")
    print()
    print("待办（未映射，不是失败）：")
    for code, item in sorted(registry().items()):
        if item.mapped:
            continue
        print(f"  {code} {item.name:<12} {item.blocked}")

    bad = [code for code, lines in misses.items() if lines]
    print()
    print("结论：全部一致" if not bad else f"结论：{len(bad)} 个已映射指标不一致 -> {bad}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
