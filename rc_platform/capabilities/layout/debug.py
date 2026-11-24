"""版式检测调试：打印每页认出的列带，便于对着真件调参。

    python -m rc_platform.capabilities.layout.debug <pdf>
"""
from __future__ import annotations

import sys
from pathlib import Path

from .detect import detect_layout
from .keywords import MONEY_FIELDS
from .words import read_pages


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("用法：python -m rc_platform.capabilities.layout.debug <pdf>")
        return 2
    path = Path(args[0])
    pages = read_pages(path.read_bytes())
    plan = detect_layout(pages)
    print(f"方法={plan.method} 置信={plan.confidence} 页数={plan.page_count} 区域={len(plan.regions)}")
    for region in plan.regions:
        print(f"  第 {region.page + 1} 页 [{region.source}] area={tuple(round(v, 3) for v in region.area)}")
        for col in region.columns:
            mark = "*" if col.field in MONEY_FIELDS else " "
            print(f"    {mark}{col.field:<14} x={col.x:.3f} w={col.w:.3f} conf={col.confidence:.1f}")
    for reason in plan.reasons:
        print("  ·", reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
