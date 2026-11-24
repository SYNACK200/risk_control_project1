"""新骨架的命令行入口：跑一份流水并打印阶段与结论。

用法：
    python -m rc_platform.cli <文件> [--template 模板.json] [--json]

它证明的是「骨架能驱动能力跑完一条链路」，不含业务闭环（没有上传、没有库）。
业务闭环在 M4 由 api 层接上。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rc_platform.core.context import JobContext
from rc_platform.core.contracts import SourceDocument
from rc_platform.core.pipeline import Pipeline
from rc_platform.core.registry import default_registry


def run_file(path: Path, *, config: dict | None = None, verbose: bool = False) -> dict:
    registry = default_registry()
    plan = registry.plan("report")
    ctx = JobContext(job_id=path.stem, config=config or {})

    if verbose:
        def sink(event):
            print(f"  [{event.index}/{event.total}] {event.stage} {event.status} {event.elapsed_ms}ms")
        ctx.sink = sink

    result = Pipeline(registry, plan, on_error="degrade").run(
        ctx, {"document": SourceDocument(data=path.read_bytes(), filename=path.name)}
    )
    verification = result.get("verification")
    statement = result.get("statement")
    metrics = result.get("metrics")
    return {
        "status": result.status,
        "verdict": getattr(verification, "verdict", None),
        "verdict_reason": getattr(verification, "verdict_reason", None),
        "txn_count": len(statement.rows) if statement else 0,
        "metric_count": len(metrics.items) if metrics else 0,
        "degradation": result.degradation,
        "stages": [s.to_dict() for s in result.stages],
        "elapsed_ms": result.elapsed_ms,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="用新骨架分析一份流水")
    parser.add_argument("path", type=Path)
    parser.add_argument("--template", type=Path, default=None, help="模板 JSON（field_map/layout）")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"文件不存在：{args.path}", file=sys.stderr)
        return 2

    config: dict = {}
    if args.template:
        config["parse.template"] = json.loads(args.template.read_text(encoding="utf-8"))

    summary = run_file(args.path, config=config, verbose=args.verbose and not args.json)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"结论：{summary['verdict']}（{summary['verdict_reason']}）")
        print(f"明细：{summary['txn_count']} 笔 · 指标 {summary['metric_count']} 项 · 用时 {summary['elapsed_ms']}ms")
        if summary["degradation"]:
            print("降级：" + "；".join(summary["degradation"]))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
