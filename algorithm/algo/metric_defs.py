"""指标定义单一事实源：公式、输入、可视图类型。

名称与单位来自 metrics.METRIC_DEFS；本文件只补充「怎么算」「怎么画」，
避免前端、文档、接口各写一份。
"""
from __future__ import annotations

from .metrics import METRIC_DEFS, METRIC_SET_VERSION

_ROWS: tuple[tuple[str, str, str, str], ...] = (
    ("A01", "入账合计（剔除六类后）", "入账交易金额合计，先剔除同名互转、本人信用卡还款、贷款发放、理财赎回、退款、担保代偿", "monthly_income"),
    ("A02", "A01 ÷ 实际覆盖自然月数", "分母按明细首末日按自然月比例累加；不足 1 个整月按 1 个月并存入口径说明", "monthly_income"),
    ("A03", "月入账中位数", "按自然月分桶求和后取中位数，无交易月份计 0", "monthly_income"),
    ("A04", "1 − 月入账标准差 ÷ 月入账均值", "均值 0 时不可算", "monthly_income"),
    ("A05", "工资/代发入账 ÷ A01", "按摘要关键词识别工资、代发、薪资", "monthly_income"),
    ("A06", "有工资入账的月数 ÷ 覆盖月数", "当月工资入账 ≥ 1 笔才计入", "monthly_income"),
    ("A07", "月入账对月份回归的斜率", "最小二乘；斜率为正表示收入上行", "monthly_income"),
    ("A08", "剔除金额 ÷ 全部入账金额", "反映多少入账被排除在收入之外", "monthly_income"),
    ("B01", "还款/分期/贷款类出账合计 ÷ 覆盖月数", "按摘要关键词识别", "monthly_expense"),
    ("B02", "B01 ÷ A02", "A02 为 0 或不可算时输出 null", "monthly_expense"),
    ("B03", "近 6 个月贷款发放笔数", "按摘要「贷款发放/放款」识别", "none"),
    ("B04", "小贷/网贷平台去重数", "按平台关键词去重", "counterparty_bars"),
    ("B05", "小贷类还款出账笔数", "出账方向且命中平台关键词", "none"),
    ("B06", "信用卡还款出账合计", "按摘要「信用卡还款」识别", "none"),
    ("B07", "余额为负的天数", "按交易日区间累计，非逐日余额", "balance"),
    ("B08", "余额为负的笔数 ÷ 总笔数", "", "balance"),
    ("C01", "A01 − 全部出账金额", "出账未按剔除口径抵扣，与净现金流略有差异", "monthly_net"),
    ("C02", "入账合计 ÷ 出账合计", "出账为 0 时不可算", "monthly_net"),
    ("C03", "日终余额按天加权平均", "缺余额的交易日沿用上一日余额", "balance"),
    ("C04", "余额标准差 ÷ 余额均值", "均值 ≤ 0 时不可算", "balance"),
    ("C05", "月末余额对月份回归斜率", "至少需要 2 个月", "balance"),
    ("C06", "最后 30 天最低余额", "以明细末日为基准回看 30 天", "balance"),
    ("C07", "取现/ATM 出账 ÷ 出账合计", "按摘要「取现/ATM/现金支取」", "monthly_expense"),
    ("C08", "当日双向进出笔数占比", "同一交易日既有入账又有出账", "none"),
    ("D01", "月度笔数标准差 ÷ 月均笔数", "", "monthly_count"),
    ("D02", "夜间（22:00–06:00）笔数 ÷ 总笔数", "需交易时间字段，无则不可算", "none"),
    ("D03", "整数金额（整百/整千）笔数 ÷ 总笔数", "", "amount_hist"),
    ("D04", "单笔金额 ≥ 大额阈值的笔数", "阈值由阈值配置给出", "top_amounts"),
    ("D05", "最大单笔金额 ÷ 总金额", "", "top_amounts"),
    ("D06", "无交易的月份数", "", "monthly_count"),
    ("D07", "工资到账日标准差（天）", "至少 3 个月工资入账", "none"),
    ("D08", "期末最后 3 天入账 ÷ 期间总入账", "识别冲量式走账", "none"),
    ("E01", "Σ(各对手方金额占比²)", "需对手方字段；无对手方列时不可算", "counterparty_bars"),
    ("E02", "前三大对手方金额 ÷ 总额", "", "counterparty_bars"),
    ("E03", "关联方金额 ÷ 总额", "同户名或关联企业", "none"),
    ("E04", "命中赌博类关键词笔数 ÷ 总笔数", "关键词表在算法配置中", "none"),
    ("E05", "命中涉赌关键词笔数 ÷ 总笔数", "保留项，规则与 E04 相同", "none"),
    ("E06", "命中虚拟币关键词笔数 ÷ 总笔数", "关键词：USDT/BTC/币安…", "none"),
    ("E07", "现金存入类入账 ÷ A01", "", "none"),
    ("E08", "第三方支付金额 ÷ 总额", "支付宝/微信/财付通等", "counterparty_bars"),
)

_INDEX = {row[0]: row for row in _ROWS}


def metric_definitions() -> list[dict]:
    """40 项指标的完整定义，供接口与前端展开查看。"""
    items: list[dict] = []
    for code, name, unit in METRIC_DEFS:
        _, formula, inputs, viz = _INDEX[code]
        items.append({
            "code": code,
            "name": name,
            "unit": unit,
            "group": code[0],
            "formula": formula,
            "inputs": inputs,
            "viz": viz,
        })
    return items


def definitions_version() -> int:
    return METRIC_SET_VERSION

