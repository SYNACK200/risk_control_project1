"""结构守卫：能力包必须自带说明书。

为什么要有这条检查：M3 那次子代理写完了代码与 50 条测试就终止了，
README 与交付文档没落盘，仓库里留下一个「能跑但没人知道怎么用」的包。
测试全绿发现不了这种缺失——只能靠清点交付物。

    python -m rc_platform.tools.check_structure
"""
from __future__ import annotations

import importlib
import pathlib

CAPABILITY_ROOT = pathlib.Path(__file__).resolve().parents[1] / "capabilities"


def packages() -> list[pathlib.Path]:
    return sorted(
        path for path in CAPABILITY_ROOT.iterdir()
        if path.is_dir() and not path.name.startswith("__") and path.name != "tests"
    )


def capability_names(package: pathlib.Path) -> list[str]:
    module = importlib.import_module(f"rc_platform.capabilities.{package.name}.plugin")
    return [
        getattr(value, "name")
        for value in vars(module).values()
        if isinstance(getattr(value, "name", None), str)
        and getattr(value, "provides", None)
        and callable(getattr(value, "run", None))
    ]


def check() -> list[str]:
    problems: list[str] = []
    for package in packages():
        if not (package / "plugin.py").exists():
            problems.append(f"{package.name}：缺 plugin.py（注册表发现不了它）")
            continue
        readme = package / "README.md"
        if not readme.exists():
            problems.append(f"{package.name}：缺 README.md（没人知道它吃什么、产什么、什么时候关掉）")
            continue
        text = readme.read_text(encoding="utf-8")
        for name in capability_names(package):
            if name not in text:
                problems.append(f"{package.name}/README.md：没有提到自己的能力名 {name}")
    return problems


def main() -> int:
    problems = check()
    for problem in problems:
        print("·", problem)
    print("结构检查：OK" if not problems else f"结构检查：{len(problems)} 个问题")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
