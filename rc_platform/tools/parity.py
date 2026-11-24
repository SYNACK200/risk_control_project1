"""新旧行为对照：同一批文件，分别走封存版链路与新骨架，逐项比对。

为什么要有这个命令：重构最容易犯的错不是「跑不起来」，而是「跑起来但结论变了」。
每个里程碑交付前都跑一次，红了就先修再谈下一步。

    python -m rc_platform.tools.parity [样本目录] [--parse parse.layout_v2]

对照口径（只比可比的，不比格式）：
- 五态结论：必须完全相同
- 明细笔数：必须完全相同
- 40 项指标：code -> value 必须逐项相同
报告结构、字段顺序、新增字段不参与比对——那是允许变化的。
"""
from __future__ import annotations

import json
import pathlib
import sys
from dataclasses import dataclass, field

ROOT = pathlib.Path(__file__).resolve().parents[2]


@dataclass
class Comparison:
    path: pathlib.Path
    ok: bool
    old_detail: dict = field(default_factory=dict)
    new_detail: dict = field(default_factory=dict)
    diffs: list[str] = field(default_factory=list)


def _old_run(data: bytes) -> dict:
    backend = str(ROOT / "backend")
    if backend not in sys.path:
        sys.path.insert(0, backend)
    from services.analysis import run_analysis

    result = run_analysis(data)
    return {
        "verdict": result["report"]["verdict"],
        "txn_count": result["txn_count"],
        "metrics": {item["code"]: item["value"] for item in result["metrics"]},
    }


def _new_run(data: bytes, parser: str | None = None) -> dict:
    from rc_platform.core.context import JobContext
    from rc_platform.core.contracts import SourceDocument
    from rc_platform.core.pipeline import Pipeline
    from rc_platform.core.registry import default_registry

    registry = default_registry()
    plan = registry.plan("report", overrides={"statement": parser} if parser else None)
    result = Pipeline(registry, plan, on_error="degrade").run(
        JobContext(job_id="parity"), {"document": SourceDocument(data=data)}
    )
    if result.status != "ok":
        return {"verdict": None, "txn_count": 0, "metrics": {}, "degradation": result.degradation}
    verification = result.get("verification")
    statement = result.get("statement")
    metrics = result.get("metrics")
    return {
        "verdict": verification.verdict,
        "txn_count": len(statement.rows),
        "metrics": {item.code: (None if item.value is None else str(item.value)) for item in metrics.items},
    }


def compare(path: pathlib.Path, parser: str | None = None) -> Comparison:
    data = path.read_bytes()
    old = _old_run(data)
    new = _new_run(data, parser)
    diffs: list[str] = []
    if old["verdict"] != new["verdict"]:
        diffs.append(f"结论：旧 {old['verdict']} / 新 {new['verdict']}")
    if old["txn_count"] != new["txn_count"]:
        diffs.append(f"笔数：旧 {old['txn_count']} / 新 {new['txn_count']}")
    old_metrics, new_metrics = old["metrics"], new["metrics"]
    if set(old_metrics) != set(new_metrics):
        missing = sorted(set(old_metrics) - set(new_metrics))
        extra = sorted(set(new_metrics) - set(old_metrics))
        diffs.append(f"指标集合不一致：缺 {missing[:5]} 多 {extra[:5]}")
    else:
        changed = [code for code in old_metrics if str(old_metrics[code]) != str(new_metrics[code])]
        if changed:
            diffs.append(f"指标值不一致：{changed[:5]}")
    return Comparison(path=path, ok=not diffs, old_detail=old, new_detail=new, diffs=diffs)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    parser = None
    if "--parse" in args:
        index = args.index("--parse")
        parser = args[index + 1]
        args = args[:index] + args[index + 2:]
    sample_dir = pathlib.Path(args[0]) if args else ROOT / "algorithm" / "inputs" / "samples" / "synthetic"
    if not sample_dir.exists():
        print(f"样本目录不存在：{sample_dir}", file=sys.stderr)
        return 2

    files = sorted(sample_dir.rglob("*.pdf"))
    if not files:
        print(f"没有 PDF：{sample_dir}", file=sys.stderr)
        return 2

    results = [compare(path, parser) for path in files]
    width = max(len(path.relative_to(sample_dir).as_posix()) for path in files)
    print(f"{'样本':<{width}}  旧      新      结论")
    for item in results:
        name = item.path.relative_to(sample_dir).as_posix()
        old, new = item.old_detail, item.new_detail
        mark = "一致" if item.ok else "不一致"
        print(f"{name:<{width}}  {old['txn_count']:>3} 笔  {new['txn_count']:>3} 笔  {mark}  {old['verdict']}")
        for diff in item.diffs:
            print(f"    ! {diff}")

    failed = [item for item in results if not item.ok]
    print()
    print(f"共 {len(results)} 份，一致 {len(results) - len(failed)}，不一致 {len(failed)}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
