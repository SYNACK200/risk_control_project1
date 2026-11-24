"""把仓库根放进 sys.path，让兼容层能 import 封存版本的 algorithm 包。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ensure_root_on_path() -> Path:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return ROOT
