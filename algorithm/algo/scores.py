"""指标分区与综合评分：把 40 项指标按业务域分组，给出分区得分与总体判断。

评分是「可解释的扣分制」而不是黑盒模型：
- 每个分区从 100 分起，按该区命中的风险结论扣分（每个 -15）；
- 该区指标缺值（null）再扣分（每缺 1 项 -5，最多 -20），表示证据不足；
- 总分 = 各分区加权平均（收入 25% / 负债 25% / 资金 25% / 异常 15% / 集中度 10%）；
- 结论分档：>=85 良好，>=70 一般，>=50 关注，<50 高风险。

分区按指标编号前缀：A=收入能力，B=负债与还款，C=资金与余额，D=异常行为，E=对手方与集中度。
"""
from __future__ import annotations

from pydantic import BaseModel, Field

DOMAINS: list[dict] = [
    {"key": "income", "prefix": "A", "name": "收入能力", "weight": 0.25, "desc": "收入规模、稳定性、结构与覆盖"},
    {"key": "debt", "prefix": "B", "name": "负债与还款", "weight": 0.25, "desc": "还款压力、多头借贷、小贷依赖"},
    {"key": "cash", "prefix": "C", "name": "资金与余额", "weight": 0.25, "desc": "净流入、余额水平与波动、现金使用"},
    {"key": "abnormal", "prefix": "D", "name": "异常行为", "weight": 0.15, "desc": "夜间交易、大额支出、博彩/虚拟币"},
    {"key": "counterparty", "prefix": "E", "name": "对手方与集中度", "weight": 0.10, "desc": "集中度、关联方、现金支取"},
]

# 结论编码 -> 分区
CONCLUSION_DOMAIN: dict[str, str] = {
    "INCOME_UNSTABLE": "income",
    "DTI_HIGH": "debt",
    "MULTI_LOAN": "debt",
    "SMALL_LOAN_REPAY": "debt",
    "NEW_LOAN": "debt",
    "LOW_BALANCE": "cash",
    "NET_OUTFLOW": "cash",
    "BALANCE_DECLINE": "cash",
    "FAST_IN_OUT": "cash",
    "GAMBLING_HIT": "abnormal",
    "NIGHT_TRADING": "abnormal",
    "CRYPTO_HIT": "abnormal",
    "COUNTERPARTY_CONCENTRATED": "counterparty",
}


class DomainScore(BaseModel):
    key: str
    name: str
    weight: float
    desc: str
    score: float
    metric_total: int = 0
    metric_valued: int = 0
    missing: int = 0
    hits: list[str] = Field(default_factory=list)
    detail: str = ""


class ScoreResult(BaseModel):
    overall: float
    grade: str
    grade_label: str
    domains: list[DomainScore]
    method: str = "分区扣分制：每命中一条风险结论 -15；缺值每项 -5（上限 -20）；按权重加权"


def _grade(overall: float) -> tuple[str, str]:
    if overall >= 85:
        return "good", "良好"
    if overall >= 70:
        return "fair", "一般"
    if overall >= 50:
        return "watch", "关注"
    return "risk", "高风险"


def compute_scores(metrics: list, conclusions: list) -> ScoreResult:
    """metrics: 含 code/value 的对象或字典；conclusions: 含 code 的对象或字典。"""
    def get(item, name, default=None):
        return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)

    domains: list[DomainScore] = []
    for domain in DOMAINS:
        prefix = domain["prefix"]
        items = [m for m in metrics if str(get(m, "code", "")).startswith(prefix)]
        valued = [m for m in items if get(m, "value") is not None]
        missing = len(items) - len(valued)
        hits = [str(get(c, "code")) for c in conclusions if CONCLUSION_DOMAIN.get(str(get(c, "code"))) == domain["key"]]
        score = 100.0 - 15.0 * len(hits) - min(20.0, 5.0 * missing)
        score = max(0.0, min(100.0, score))
        parts = []
        if hits:
            parts.append("命中 " + "、".join(hits))
        if missing:
            parts.append(f"{missing} 项缺值")
        domains.append(DomainScore(
            key=domain["key"], name=domain["name"], weight=domain["weight"], desc=domain["desc"],
            score=round(score, 1), metric_total=len(items), metric_valued=len(valued),
            missing=missing, hits=hits, detail="；".join(parts) or "未见异常",
        ))

    overall = round(sum(d.score * d.weight for d in domains), 1)
    grade, label = _grade(overall)
    return ScoreResult(overall=overall, grade=grade, grade_label=label, domains=domains)
