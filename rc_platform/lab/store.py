"""自定义特征的存储：只增不改 + 版本号。

为什么不是「存一行、改一行」：口径改了要能回答「这份报告用的是哪一版口径」。
老系统的 custom_metric 表就是反例——只存 steps、没有版本，改完无法追溯。

存储形态刻意选文件而不是库：Lab 还在试用期，进库意味着要同步写迁移、权限、审计；
文件版先在本地把「版本语义」定下来，进库时只换实现不换语义。
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

CODE_RE = re.compile(r"^[a-z][a-z0-9_]{2,31}$")
STORE_PATH = Path(__file__).resolve().parents[2] / "var" / "lab" / "custom_features.json"


class LabFeatureError(ValueError):
    """定义不合法（编号格式、重复生效、表达式为空等）。"""


@dataclass
class CustomFeature:
    code: str
    name: str
    expr: str
    unit: str = ""
    version: int = 1
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    superseded_by: int | None = None      # 被哪一版取代；None 表示当前生效
    deleted_at: str | None = None

    @property
    def active(self) -> bool:
        return self.superseded_by is None and self.deleted_at is None


def _empty() -> dict:
    return {"version": 1, "features": []}


def load() -> dict:
    if not STORE_PATH.exists():
        return _empty()
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()


def _save(data: dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_features(*, include_history: bool = False) -> list[dict]:
    data = load()
    rows = [item for item in data["features"] if include_history or CustomFeature(**item).active]
    return rows


def current(code: str) -> dict | None:
    for item in list_features():
        if item["code"] == code:
            return item
    return None


def save_feature(code: str, name: str, expr: str, *, unit: str = "", description: str = "") -> dict:
    """保存（或改版）一条自定义特征。同一 code 再保存 = 新版本，旧的标记被取代。"""
    code = (code or "").strip().lower()
    if not CODE_RE.match(code):
        raise LabFeatureError("编号只能是 3–32 位小写字母/数字/下划线，且以字母开头")
    if not (name or "").strip():
        raise LabFeatureError("名称不能为空")
    if not (expr or "").strip():
        raise LabFeatureError("表达式不能为空")

    # 表达式必须能被解析：存进去却跑不起来，比不存更糟
    from ..capabilities.features import expr as expr_mod

    try:
        expr_mod.parse(expr)
    except Exception as exc:  # noqa: BLE001 - 语法错误要原样告诉作者
        raise LabFeatureError(f"表达式解析失败：{exc}") from exc

    data = load()
    version = 1
    for item in data["features"]:
        if item["code"] == code and item.get("superseded_by") is None and not item.get("deleted_at"):
            version = int(item["version"]) + 1
            item["superseded_by"] = version

    record = asdict(CustomFeature(code=code, name=name.strip(), expr=expr.strip(),
                                  unit=unit or "", version=version, description=description or ""))
    data["features"].append(record)
    _save(data)
    return record


def delete_feature(code: str) -> bool:
    data = load()
    hit = False
    for item in data["features"]:
        if item["code"] == code and item.get("superseded_by") is None and not item.get("deleted_at"):
            item["deleted_at"] = datetime.now().isoformat(timespec="seconds")
            hit = True
    if hit:
        _save(data)
    return hit
