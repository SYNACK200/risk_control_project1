"""词库表：把「工资」「小贷」「第三方支付」这类语义从代码里搬出来。

为什么必须可配置：这类词每个银行、每个地区都不一样（「工资」也可能是「代发」「薪资」「劳务费」），
写死在代码里意味着业务每加一个词就找算法发版一次。老系统的做法就是写死，
结果 14 项语义指标一直改不动。

存储：内置一份默认词库（够跑通），本地可覆盖（var/lab/lexicons.json），
每个词库带版本号；报告里引用指标时要能回溯用的是哪一版。
"""
from __future__ import annotations

import json
from pathlib import Path

STORE_PATH = Path(__file__).resolve().parents[3] / "var" / "lab" / "lexicons.json"

# 默认词库：只收高置信度的词，宁可漏也不要误伤。
# 每条都写清它服务于哪个口径，避免以后没人敢改。
DEFAULTS: dict[str, dict] = {
    "salary": {
        "version": 1,
        "label": "工资 / 代发",
        "words": ["工资", "薪资", "薪金", "代发", "劳务费", "奖金", "绩效", "工资代发"],
    },
    "loan_disbursement": {
        "version": 1,
        "label": "贷款发放（入账）",
        "words": ["贷款发放", "放款", "贷款放款", "借款发放", "授信发放"],
    },
    "loan_repayment": {
        "version": 1,
        "label": "贷款还款（出账）",
        "words": ["贷款还款", "还款", "分期还款", "月供", "房贷", "车贷", "按揭"],
    },
    "credit_card": {
        "version": 1,
        "label": "信用卡还款",
        "words": ["信用卡还款", "信用卡", "还款-信用卡", "贷记卡"],
    },
    "online_loan": {
        "version": 1,
        "label": "网贷平台",
        "words": ["微粒贷", "借呗", "花呗", "京东金条", "360借条", "度小满", "美团借钱", "分期乐"],
    },
    "cash": {
        "version": 1,
        "label": "现金存取",
        "words": ["现金存入", "现金支取", "ATM取款", "ATM存款", "存取款", "柜面取现", "取现"],
    },
    "third_party": {
        "version": 1,
        "label": "第三方支付",
        "words": ["支付宝", "微信", "财付通", "云闪付", "银联在线", "京东支付"],
    },
    "gambling": {
        "version": 1,
        "label": "涉赌代理",
        "words": ["博彩", "彩票", "赌", "棋牌", "体彩", "福彩"],
    },
    "crypto": {
        "version": 1,
        "label": "虚拟币",
        "words": ["USDT", "比特币", "BTC", "以太坊", "ETH", "虚拟币", "数字货币", "交易所"],
    },
    "related_party": {
        "version": 1,
        "label": "关联方（同名互转）",
        "words": ["本人", "同名", "自有账户", "内部转账"],
    },
}


def _overrides() -> dict:
    if not STORE_PATH.exists():
        return {}
    try:
        payload = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload.get("lexicons", {}) if isinstance(payload, dict) else {}


def resolve(name: str) -> tuple[str, ...]:
    """取一个词库的词表；本地覆盖优先，缺了就回落到默认。"""
    key = (name or "").strip()
    override = _overrides().get(key)
    if isinstance(override, dict) and override.get("words"):
        return tuple(str(word) for word in override["words"])
    entry = DEFAULTS.get(key)
    if entry is None:
        raise KeyError(key)
    return tuple(entry["words"])


def catalog() -> list[dict]:
    overrides = _overrides()
    out = []
    for name, entry in DEFAULTS.items():
        words = overrides.get(name, {}).get("words") or entry["words"]
        out.append({
            "name": name,
            "label": entry["label"],
            "version": int(overrides.get(name, {}).get("version") or entry["version"]),
            "words": list(words),
            "overridden": name in overrides,
        })
    return out


def save_override(name: str, words: list[str], *, label: str | None = None) -> dict:
    """本地覆盖一个词库；版本号自增，便于回溯。"""
    if not words:
        raise ValueError("词表不能为空")
    payload = {"lexicons": _overrides()}
    current = payload["lexicons"].get(name, {})
    payload["lexicons"][name] = {
        "label": label or current.get("label") or DEFAULTS.get(name, {}).get("label", name),
        "version": int(current.get("version") or 0) + 1,
        "words": [str(word).strip() for word in words if str(word).strip()],
    }
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload["lexicons"][name]
