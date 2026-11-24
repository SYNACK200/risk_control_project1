"""能力注册表：发现、校验、按契约装配。

三条设计约束：
1. 能力自己声明 provides/requires，注册表只按契约组装，不认识任何业务概念。
2. 同一契约可以有多个实现并存（例如模板解析与通用解析），由 overrides 选择，便于 A/B 与回滚。
3. 启停由配置决定：停用的能力不参与装配，下游缺契约时自动跳过并标记降级。
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Any, Iterable

from .contracts import CONTRACTS, EXTERNAL_CONTRACTS
from .errors import CapabilityError, ContractCycle, ContractMissing

_CATALOG: dict[str, type] = {}


@dataclass(frozen=True)
class CapabilityInfo:
    name: str
    version: str
    provides: str
    requires: tuple[str, ...]
    cls: type
    priority: int = 0
    optional_requires: tuple[str, ...] = ()

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "provides": self.provides,
            "requires": list(self.requires),
            "optional_requires": list(self.optional_requires),
            "priority": self.priority,
            "doc": (self.cls.__doc__ or "").strip().splitlines()[0] if self.cls.__doc__ else "",
        }


def capability(cls: type) -> type:
    """把一个类登记为能力。缺声明就当场报错，不等到运行期。"""
    for attr in ("name", "version", "provides"):
        if not isinstance(getattr(cls, attr, None), str) or not getattr(cls, attr):
            raise CapabilityError(f"{cls.__name__} 缺少字符串属性 {attr}")
    if not isinstance(getattr(cls, "requires", ()), tuple):
        raise CapabilityError(f"{cls.__name__} 的 requires 必须是元组")
    if not callable(getattr(cls, "run", None)):
        raise CapabilityError(f"{cls.__name__} 缺少 run(ctx, inputs)")
    if cls.provides not in CONTRACTS:
        raise CapabilityError(f"{cls.__name__} 产出的契约 {cls.provides} 未登记")
    for need in tuple(cls.requires) + tuple(getattr(cls, "optional_requires", ())):
        if need not in CONTRACTS:
            raise CapabilityError(f"{cls.__name__} 依赖的契约 {need} 未登记")
    previous = _CATALOG.get(cls.name)
    if previous is not None and previous is not cls:
        raise CapabilityError(f"能力名重复：{cls.name}（已由 {previous.__name__} 注册）")
    _CATALOG[cls.name] = cls
    return cls


def discover(package: str = "rc_platform.capabilities") -> list[str]:
    """扫描能力包里每个子目录的 plugin.py。加一个目录就等于加一个能力。"""
    pkg = importlib.import_module(package)
    found: list[str] = []
    for info in pkgutil.walk_packages(pkg.__path__, prefix=package + "."):
        if not info.ispkg:
            continue
        module_name = info.name + ".plugin"
        try:
            importlib.import_module(module_name)
        except ModuleNotFoundError as exc:
            if exc.name == module_name:
                continue
            raise
        found.append(module_name)
    return found


class Registry:
    def __init__(self, catalog: dict[str, type] | None = None):
        self._catalog = dict(catalog if catalog is not None else _CATALOG)

    # ---- 查询 ----
    def names(self) -> list[str]:
        return sorted(self._catalog)

    def info(self, name: str) -> CapabilityInfo:
        cls = self._catalog.get(name)
        if cls is None:
            raise ContractMissing(f"没有注册能力：{name}")
        return CapabilityInfo(
            name=cls.name,
            version=cls.version,
            provides=cls.provides,
            requires=tuple(cls.requires),
            cls=cls,
            priority=int(getattr(cls, "priority", 0)),
            optional_requires=tuple(getattr(cls, "optional_requires", ())),
        )

    def describe(self) -> list[dict[str, Any]]:
        return [self.info(name).describe() for name in self.names()]

    def providers(self, contract: str) -> list[str]:
        return [n for n in self.names() if self._catalog[n].provides == contract]

    # ---- 装配 ----
    def plan(
        self,
        target: str,
        *,
        overrides: dict[str, str] | None = None,
        disabled: Iterable[str] = (),
        enabled: Iterable[str] | None = None,
    ) -> list[str]:
        """给出产出 target 所需的能力顺序（依赖在前）。"""
        if target not in CONTRACTS:
            raise ContractMissing(f"目标契约未登记：{target}")
        overrides = overrides or {}
        off = set(disabled)
        on = None if enabled is None else set(enabled)

        order: list[str] = []
        done: set[str] = set()
        visiting: list[str] = []

        def pick(contract: str) -> str:
            candidates = [n for n in self.providers(contract) if n not in off]
            if on is not None:
                candidates = [n for n in candidates if n in on]
            if not candidates:
                raise ContractMissing(f"没有可用能力产出契约 {contract}（可能被配置停用）")
            wanted = overrides.get(contract)
            if wanted:
                if wanted not in candidates:
                    raise ContractMissing(f"overrides 指定的能力不可用：{wanted}")
                return wanted
            candidates.sort(key=lambda n: (-self.info(n).priority, n))
            return candidates[0]

        def visit(contract: str) -> None:
            if contract in done:
                return
            if contract in EXTERNAL_CONTRACTS:
                done.add(contract)
                return
            if contract in visiting:
                cycle = " -> ".join(visiting[visiting.index(contract):] + [contract])
                raise ContractCycle(f"能力依赖成环：{cycle}")
            visiting.append(contract)
            try:
                name = pick(contract)
                info = self.info(name)
                for need in info.requires:
                    visit(need)
                # 可选依赖：没有可用实现就跳过，装配不因此失败（外部层未接入是常态）
                for need in info.optional_requires:
                    try:
                        visit(need)
                    except ContractMissing:
                        continue
                if name not in order:
                    order.append(name)
                done.add(contract)
            finally:
                visiting.pop()

        visit(target)
        return order

    def instantiate(self, plan: Iterable[str]) -> list[tuple[str, Any]]:
        out = []
        for name in plan:
            out.append((name, self.info(name).cls()))
        return out


def default_registry(discover_first: bool = True) -> Registry:
    if discover_first and not _CATALOG:
        discover()
    return Registry()


def catalog() -> dict[str, type]:
    return dict(_CATALOG)
