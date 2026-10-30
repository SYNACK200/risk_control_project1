> 这是什么：四层核验、40 项指标、规则命中 · 谁写：算法组 · 何时更新：实现变化时

# 模块

| 文件 | 内容 | 状态 |
| --- | --- | --- |
| file_layer.py | 文件层 11 项：生成器、创建修改时间、增量更新、结构指纹、字体、隐藏文字、覆盖图元、签名、版面、体量、图像混排 | 已实现（AL-07；F4/F10 需真件基线） |
| content_layer.py | 内容层 10 项：已实现 C1 余额链、C2 每页合计、C3 笔数、C4 期初期末；跨页、参考号、时间分布、金额形态、语义、重复待做 | 部分实现（AL-04） |
| ledger_layer.py | 账务层 7 项：A1 结息反算、A2 结息日、A3 利息税、A4 费用、A5 到账时延、A6 期末余额、A7 透支冻结 | 已实现（AL-06） |
| external_layer.py | 外部层 7 项：回单验真、调证、征信、社保个税、行内代发、多份互证、签章；适配器接口 + 占位实现 | 已实现（AL-08/14；需授权与接口） |
| verdict.py | 五态合成与证据组装；file/content/ledger/external 缺失时按未执行降级 | 已实现（AL-09） |
| models.py | CheckResult、Attribution、Evidence、LayerConclusion 等输出模型 | 已实现 |
| evidence.py | 行级/页级证据坐标组装 | 已实现 |
| exclusions.py | 六类剔除：同名互转、退款冲正、贷款放款、理财赎回申购、信用卡还款取现、他人代付 | 已实现（AL-10） |
| metrics.py | 40 项指标、指标集版本与单项口径版本 | 已实现（AL-11；部分指标缺输入返回 null） |
| hits.py | 摘要/对手方词库：精确词、正则、标签、行级位置与证据 | 已实现（AL-12；词库待业务评审） |
| thresholds.py | 默认阈值、阈值版本、提示结论、整版导出 | 已实现（AL-13；v2 共 13 项，未校准项待业务确认） |
| report.py | contract 报告聚合：五态、四层、指标、趋势、阈值结论、证据 | 已实现（AL-13） |
| samples.py | AL-15 合成样本：四类版式 + 两类伪造、manifest 清单、加载与校验 | 已实现（AL-15） |
| eval.py | AL-16 样本回归：五态/笔数/失败码比对、抽错归因、JSON 报告 | 已实现（AL-16） |
| perf.py | AL-17 性能压测：三千笔造数、全链路计时、P50/P95/P99 与 SLA 判定 | 已实现（AL-17） |

# 内容层当前口径

| 检查 | 对什么 | 容差 | 判 fail 后归因 |
| --- | --- | --- | --- |
| C1 余额链 | 上一行余额 + 本行收支 = 本行余额，逐对相邻行 | 0.01 元 | 相关行全低置信 → 识别问题（转人工）；否则数据断（停止） |
| C2 每页合计 | 本页印的收入/支出合计 vs 本页明细求和 | 0.01 元 | 同上，证据挂页脚坐标 |
| C3 笔数 | 本页印笔数 vs 本页解析笔数；页脚总数 vs 全量 | 0 笔 | 同上 |
| C4 期初期末 | 期初 + 收入 - 支出 = 期末 | 0.01 元 | 同上；文件未印期初/期末则跳过 |

低置信阈值取 `ocr.parse.LOW_CONF = 0.8`。因低置信跳过或字段缺失导致未核对时，记为 `skipped/partial`，不判数据断。

# 文件层当前口径

| 组 | 检查 | 命中后 |
| --- | --- | --- |
| 生成方式 | F1 生成器、F2 创建修改时间、F3 增量更新、F4 结构指纹 | 任一 fail → 来源可疑 |
| 排版改动 | F5 字体、F6 隐藏文字、F7 覆盖图元、F9 版面 | 2 项及以上 fail → 来源可疑；单项只记录 |
| 整体异常 | F8 签名、F10 体量页密度、F11 图像混排 | 只记录，不单独定性 |

- F4、F10 需要同版式真件基线（`FileBaseline`）；没有基线时跳过并写入 limitations，不猜。
- 无 PAdES 签名按银行流水常见情况处理：记录「无法做密码学校验」，不判可疑。
- F3 遇到多个 `%%EOF`/`startxref` 时先看 `/ByteRange`：签名范围覆盖到文件尾 → `partial`（增量来自签名，未验签）；签名范围未覆盖尾部 → fail（签名后追加）；无签名或 `ByteRange` 异常 → 按原规则处理。依据是微信支付真件：2 个修订全部落在签名覆盖范围内。
- F7 区分贴补与印章：`fill-image` 面积 ≥ 3000 pt² 且覆盖 ≥ 3 个文字块 → 按印章/水印 `partial`，只记录；小尺寸图像和矢量贴补仍 fail。合成覆盖样本是 194 pt²、只覆盖 1 个文字块，仍命中 F7。
- F9 比页尺寸、旋转、左边距；顶边距只在「各页起始行相同」时比对（续页不重复抬头时起点天然不同，招行真件第 2 页从表头起排，比全页最小 y 会误判拼页）。右边距与下边距随内容长度变化，不作判据。
- 影像件与截图件不做结构取证。
- 真件脱敏副本 `inputs/samples/wechat_desensitized.pdf` 是重存后的单修订文件，原签名已失效，只用于版式与解析回归，不用于 F3/F8 判定。

# 账务层当前口径

| 检查 | 判据 | 缺什么就跳过 |
| --- | --- | --- |
| A1 结息反算 | 按日终余额积数 × 年利率 ÷ 360（或 365）复算，与文件利息记录比对，容差 max(0.05 元, 0.1%) | 无利率表、缺上一结息日、低置信行 |
| A2 结息日规律 | 结息日落在 3/6/9/12 月 20 或 21 日，间隔符合季度或年度 | 无结息记录 |
| A3 利息税 | 利息 × 税率与同日利息税记录比对 | 无税率 |
| A4 费用规律 | 同名费用金额一致，间隔符合月/季/年 | 同类费用少于 2 笔 |
| A5 到账时延 | 需交易时分与清算时间表 | 交易时分已随 `Transaction.trade_time` 抽取，仍缺清算时间表，恒跳过 |
| A6 期末余额 | 最后一笔余额 = 账户期末余额 | 调用方未传期末余额 |
| A7 透支与冻结 | 负余额与冻结标记是否合理 | 未提供账户产品形态时只提示 |

账务层任一 fail → 余额可疑；全部可算且通过才算 pass。

# 外部层当前口径

`analyze_external(context, adapters=None, enabled=None)` 输出 E1–E7；默认全是占位适配器，只返回「未启用」，不编造外部数据。

| 编号 | 检查 | 前提 | 不一致时比对什么 |
| --- | --- | --- | --- |
| E1 | 电子回单验真 | 客户授权 + 网银/官方渠道 | 回单编号与官方记录 |
| E2 | 跨行调证 | 机构间函证协议 | 出证行回函 |
| E3 | 征信交叉 | 征信查询授权 | 月供、负债、账户数与流水还款记录 |
| E4 | 社保与个税 | 客户授权 | 缴费基数、申报收入与入账 |
| E5 | 行内代发 | 本行数据 | 代发工资记录与工资入账 |
| E6 | 多份互证 | 多份材料 | 同一账户其他时段、同一人在他行流水 |
| E7 | 电子签章 CA | 签章体系 | 证书链与有效期 |

- 适配器只需实现 `code`、`name`、`check(context) -> ExternalCheckResult`；`ExternalContext` 带明细与 `materials`，由适配器解释。
- 结果状态：`consistent / inconsistent / not_configured / unavailable / skipped`。任一 `inconsistent` → 层 fail、outcome「存在不一致」；全部一致才 pass；部分一致为 limited；一项都拿不到为 unavailable。
- 适配器抛异常按接口不可用处理（`unavailable`），不打断主链，异常信息写进该检查的 detail。
- 无授权或接口未开通时，limitations 逐项写「需什么 + 未启用」；五态仍为「未发现异常」，即 contract 的「未发现异常但标注」。

# 判定顺序（不许跳层）

```text
file_layer → content_layer → ledger_layer → external_layer

```

前层能定性就不走后面；外部层无数据时降级为「未发现异常但标注」。当前四层与 verdict 均已实现；external 传 `None` 或全部适配器未启用时按核验受限处理，结论为「未发现异常」并在 limitations 逐项标注。

# 五态合成

| 前置 | 结论 |
| --- | --- |
| 载体为截图 | 来源可疑 |
| 文件层 outcome = 来源可疑 | 来源可疑 |
| 内容层有数据断 | 存在不一致 |
| 内容层失败全部归因为识别 | 无法判定 |
| 未解析到明细 | 无法判定 |
| 账务层 fail | 余额可疑 |
| 外部层不一致 | 存在不一致 |
| 其余 | 未发现异常（有跳过/部分检查时在 limitations 注明核验受限） |

证据按 `(rule_code, page_no, row_no)` 去重，坐标取行框或页脚框中心。

# 剔除层当前口径

`analyze_exclusions(transactions, holder_name=None)` 按固定顺序匹配，一笔只归一类：

| 顺序 | 类别 | 判据 | 需人工 |
| --- | --- | --- | --- |
| 1 | 同名互转 | 对手方与本人姓名一致（去空格与掩码符），或摘要含本人/同名/内部划转/归集 | 否 |
| 2 | 退款与冲正 | 摘要含退款/冲正/撤销 | 否 |
| 3 | 贷款放款 | 入账且摘要含放款/贷款发放/借款，或对手方为消费金融/小贷/借呗/花呗等 | 否 |
| 4 | 理财赎回与申购 | 摘要含理财/基金/赎回/申购/赎买 | 否 |
| 5 | 信用卡还款与取现 | 摘要含信用卡/还款/取现/ATM | 否 |
| 6 | 他人代付 | 入账且摘要含代付（不含代发）、对手方为机构 | 是，`needs_review` |

剔除只改变收入口径与 `A05/A08/E07` 的分母，不改变 `B01/B03/B05/B06/C02` 等原始收支指标。未提供本人姓名时，同名互转只能靠摘要识别，写入 `notes`。

# 指标层当前口径

- `METRIC_SET_VERSION = 2（v2 起月均类按实际覆盖自然月折算）`、单项 `caliber_version = 1`；两者只增不改。
- 40 项固定输出，缺输入返回 `value = null` 并在 `note` 写明原因，不填 0、不估算。
- 百分比类指标统一取 0–1 比例（与 mock 的 DTI 0.42 / 阈值 0.5 一致）；单位仍写「百分比」。
- 统计口径：标准差用总体标准差；月均收入 = 剔除后入账 ÷ 覆盖自然月数；空月计 0；趋势用月度值对月份序号回归。
- 日终余额：按交易余额还原，无交易日结转；期初余额未知时，首个有余额日期之前不计入均值。
- A 组收入类以剔除后入账为准；`B01/B03/B04/B05/B06` 用原始明细，不因剔除而少算负债。
- 0 笔明细时 40 项全部返回 `null` 并注明「无交易明细」，不输出 0；「没解析到」与「测量为 0」必须区分。
- E01/E02 只统计有名称的对手方；脱敏件里的 `***` 会作为单一对手方计入，集中度会失真，脱敏副本的 E01/E02 不作真实读数。
- B06 只认摘要或对手方含「信用卡」；对手方为支付宝或为空的渠道还款计入 B01，不计入 B06。
- C05/D08 的最后一个月按期末日截断（如期末为 10-23），末点不是完整月末，读斜率与冲量时需注意。
- `trade_time`（`HH:MM:SS`，UTC+8）取每笔日期下方的时分秒：工行件印在日期列正下方（x≈94），每页还重复印 5 次打印时间 `15:00:50`（x≥313），同一行有多个时间候选时取最左，打印时间不会误取。原件只印到分时秒位补 `00`；未印时分秒则为 null，不用 `00:00:00` 顶替。契约表仍无该列，由 PM/PD 决定落库。
- 方向判定顺序：收付/借贷标志列 → 收入/支出两列 → 金额符号。只有整表既无方向列也无收支两列、且金额列确实出现过负数时，才把未带负号的行补为入账（列内无负数可能只是没有出账，不推断，保持 null）；补判笔数写进 `parse()` warnings。招行件 30 笔据此得到 11 笔入账，A01=17957.03。

| 指标 | 缺什么就返回 null |
| --- | --- |
| D02 | 交易时分（`Transaction.trade_time`；原件未印时分秒时为 null） |
| E03 | 关联方关系数据 |
| E04/E05/E06 | 未传入 `detect_hits()` 结果时；传入后按标签计算 |
| D04 | 本行同客群分位阈值 |
| A02–A08、D01、D06、D08 | 交易日期 |
| C03–C06、B07 | 交易余额 |

真实样本（102 笔）结果：剔除 7 笔（退款 2、理财 1、还款 4），入账由 3897.99 降至 3781.39；月均收入 630.23 元；D02 夜间占比 0.1961（20/102 笔落在 22:00–06:00），E03 返回 null 并注明缺关系数据。2026-10-29 用独立脚本按原始明细重算 40 项，数值全部一致；0 笔明细的微信脱敏件 40 项全部为 null。微信零钱提现等内部划转未命中六类，暂按普通入账处理，待约定是否加第七类。招行脱敏件（30 笔）A01=17957.03（与按明细手算一致），S6 余额链 29 处全闭合，结论「未发现异常」；对手方整列打码，E01/E02 返回 null。

# 规则命中当前口径

`detect_hits(transactions, library=None, categories=None)` 输出逐笔命中、标签、标签计数与行级证据。

| 类别 | 标签 | 规则编码 | 主要判据 |
| --- | --- | --- | --- |
| 借贷 | LOAN | R_LOAN_PLATFORM / R_LOAN_REPAY / R_LOAN_WORD | 放贷机构名、借呗/花呗等、带语境的还款、贷款/借款/放款 |
| 博彩 | GAMBLING | R_GAMBLING | 彩票、棋牌、博彩、投注、返水等 |
| 资金归集 | COLLECTION | R_COLLECTION | 代付、代收、收款码、码商、归集 |
| 套现 | CASHOUT | R_CASHOUT | POS、套现、刷卡/扫码套现、商户收款 |
| 司法 | JUDICIAL | R_JUDICIAL | 法院、冻结、扣划、裁定、执行款等 |
| 投资 | INVEST | R_INVEST | 证券、基金、期货、理财、股票等 |
| 虚拟币 | CRYPTO | R_CRYPTO | 虚拟币、比特币、USDT、BTC、交易所名等 |

- 匹配顺序：同一规则先查精确词，再查正则；字段先摘要、再对手方；一笔交易对同一规则只出一条命中。
- 精确优先是为了控误报：「信用卡还款」不命中 LOAN，「消费」不命中 CASHOUT，避免把普通消费或信用卡还款算成小贷。
- 每条命中带 `page_no、row_no、span_start、span_end、evidence(x,y)`，可回指原页原行。
- 标签只作提示与排序，不改变五态真伪结论（Agent.md 第 46 行「线索不是证据」）。
- 词库是 `RuleLibrary`，可整份 JSON 配置；规则、词条、权重、来源、更新日期、版本都随库走，`RULE_LIBRARY_VERSION = 1`。
- 真实样本仅命中 1 笔 INVEST（理财），LOAN/GAMBLING/CRYPTO 均为 0；说明词库偏精确，但尚无真实涉赌/小贷样本可验证召回。

# 报告聚合当前口径

`build_report(verdict, metrics, carrier=..., hits=..., transactions=..., txn_ids=..., materials=...)` 输出 contract「报告结构」的 13 个字段：

| 字段 | 来源 |
| --- | --- |
| carrier | 调用方传入，服务端判定值 |
| verdict / verdict_reason / limitations | `conclude()` 的结果，并合并阈值说明 |
| layers | 四层结论数组，每项 `{layer,status,detail}` |
| metrics / metric_set_version | `compute_metrics()` |
| threshold_version / conclusions | `evaluate_thresholds()` |
| trend | `MetricSet.trend`：月收入用剔除后入账，月支出用全部出账 |
| evidence | 五态证据，按 `(rule_code,page_no,row_no)` 去重；`txn_id` 由页行映射，拿不到时 null 并写受限说明 |
| materials | 报告依据的材料清单，调用方（后端 task_file）传入；空清单时在 limitations 声明「材料清单未提供」 |
| version | 报告版本，调用方传入，从 1 起只增不改 |

阈值默认值与结论编码（`threshold_version=2`，共 13 项）：

| 编码 | 条件 | 默认 |
| --- | --- | --- |
| DTI_HIGH | B02 ≥ 阈值 | 0.5 |
| INCOME_UNSTABLE | A04 ≥ 阈值 | 0.5 |
| LOW_BALANCE | C06 < 月供 × 倍数 | 1 倍；未传月供时用 B01 近似并注明 |
| MULTI_LOAN | B04 ≥ 阈值 | 3 个 |
| GAMBLING_HIT | GAMBLING 命中交易数 ≥ 阈值 | 1 笔；未传 hits 不判定 |
| NIGHT_TRADING | D02 > 阈值 | 0.1（明细无 `trade_time` 时不触发） |
| NET_OUTFLOW | 净流出占流入 ≥ 30%，或连续 2 个月净流出 | 30% / 2 个月；单月 ≥ 100 元才计数（未校准） |
| BALANCE_DECLINE | 月均余额降 ≥ 10% 且期末余额低于月供线 | 10% + 1 倍月供；前后各 3 个月对比 |
| FAST_IN_OUT | 当日进出占比 > 0.2 且当日进金额 ≥ 下限且有效笔数 ≥ 3 | 0.2 / 500 元（未校准）/ 3 笔 |
| COUNTERPARTY_CONCENTRATED | 有效对手方笔数 ≥ 20 且 HHI ≥ 校准阈值 | 未校准（默认不判定） |
| NEW_LOAN | 近 6 月放款 ≥ 1 笔且金额 ≥ 月均收入 30% | 1 笔 / 30%（未校准） |
| SMALL_LOAN_REPAY | 月均 ≥ 1 笔 | 1 笔/月 |
| CRYPTO_HIT | ≥ 1 笔且金额 ≥ 下限 | 1 笔 / 1000 元（未校准） |

- 阈值只产生 `level=info` 的提示结论，不参与五态真伪判定，也不构成授信建议；全部结论都是线索性质，不聚合为综合风险等级（F01）。
- `export_thresholds(config=None)` 输出整版快照 JSON（Decimal 落为字符串，精度不丢），供数据组建表种子与后端按版本归档；报告本身只带 `threshold_version`，不带全量阈值。
- `conclusions` 只列触发项；未触发或指标为 null 的不输出。
- 「未校准」= 算法组暂定默认值，须按「修口径与缺失值 → 样本分布校准 → 按误报代价定价」确认；HHI 阈值校准前不判定，只告警缺失率。
- 对手方缺失率 > 20% 时单独告警（E01/E02 只按有对手方笔数计算，可能失真）；对手方为 `***`、`###` 等纯掩码名称时另告警。
- 净流出连续性按自然月检查，缺交易月按 0 计并中断连续；`BALANCE_DECLINE` 的期末余额取最后一个月内日期最新的一笔（同日按行序），文件需按时间正序。
- `CRYPTO_HIT` 传入 `hits` 时按 `CRYPTO` 标签计数，未传时按摘要词库；与 E06 的标签口径保持一致。
- 净流出月序列、月均余额、当日进出、放款/涉币金额条件依赖原始明细：`build_report` 传入 `transactions` 才判定，否则只写「未传交易明细」说明。
- `layers` 按 contract 输出数组；mock 样例是对象，二者不一致，已记入待处理。
- 真实样本结果（icbc_desensitized.pdf，threshold_version=2）：未发现异常（核验受限），3 条阈值提示（INCOME_UNSTABLE 1.1851、LOW_BALANCE 21.65 vs 106.15、BALANCE_DECLINE −15.54% 期末 21.67）；NET_OUTFLOW 不触发（7 月 −209.68 之后 8 月 −2.70 被单月 100 元下限拦住，未达连续 2 月）；对手方缺失率告警 47.06%（48/102）+ 10 笔掩码名称告警 + HHI 未校准不判定；趋势 6 个月，证据为空（五态未判失败）。

# 样本集当前口径

AL-15 的样本全部是造数，不含真实客户信息；生成到 `algorithm/inputs/samples/synthetic/`（被根目录 `.gitignore` 忽略，可随时重建）。

```text
生成：python -m algorithm.algo.samples --out algorithm/inputs/samples/synthetic
校验：python -m algorithm.algo.samples --check --out algorithm/inputs/samples/synthetic
```

| 编号 | 版式 | 结构 | 期望 |
| --- | --- | --- | --- |
| clean_icbc | 工行式 | 借贷标志 + 单列交易金额 + 余额，跨两页 | 未发现异常；C1/C2/C3 通过，C4 跳过 |
| clean_ccb | 建行式 | 收入金额与支出金额分列 + 账户余额 | 同上 |
| clean_cmb | 招行式 | 借贷方向 + 交易金额 + 交易后余额 | 同上 |
| clean_wechat | 微信账单 | 收/支 + 金额，无余额列 | 未发现异常；C1/C2 跳过，C3 通过 |
| forged_amount_icbc | 内容篡改 | 改金额不改余额 | 存在不一致；C1 fail，证据定位到行 |
| forged_overlay_icbc | 文件伪造 | 增量更新 + 白底覆盖后重写金额 | 来源可疑；F3、F7 fail |

- `manifest.json` 每项含 `id、path、layout、carrier、forgery、expectation{verdict,txn_count,fail_codes}、notes`；`path` 相对样本目录。
- `build_sample_set()` 生成并回读；`load_samples()` 校验 id 唯一、路径不越界、文件存在、四类版式与两类伪造齐全；`load_manifest()` 只读清单。
- 样本 PDF 嵌入 Droid Sans Fallback 子集，固定元数据与页脚；F1/F2/F5 可通过，F4/F10 仍因无真件基线跳过。
- 干净样本只覆盖解析与算术链，不冒充真件：文件层结论仍是 limited，内容层因缺期初期末为 limited。

# 样本评测当前口径

`python -m algorithm.algo.eval` 默认读取 `algorithm/inputs/samples/synthetic`，逐份跑解析、文件层、内容层、账务层、外部层与五态合成，再按 manifest 的 `expectation` 比对。

```text
评测：python -m algorithm.algo.eval
重建后评测：python -m algorithm.algo.eval --build
指定目录：python -m algorithm.algo.eval --samples <目录>
写 JSON：python -m algorithm.algo.eval --json report.json
CI 严格模式：python -m algorithm.algo.eval --strict
```

| 指标 | 口径 |
| --- | --- |
| 样本通过率 | 五态、必需失败码、笔数全部符合的样本 ÷ 总数 |
| 五态准确率 | 实际五态 = 期望五态的样本 ÷ 总数 |
| 笔数准确率 | 有期望笔数的样本中，解析笔数一致的占比 |
| 必需失败码召回 | 清单要求的失败码命中数 ÷ 要求总数 |
| 伪造检出 | 伪造样本通过数 ÷ 伪造样本数 |
| 干净件误判 | 干净样本出现错误五态或失败码的占比 |

- 伪造样本只要求必需失败码命中；多出的内容层失败记为 `extra_codes`，不判失败。干净样本出现任何失败码即误报。
- 抽错归因：`recognition` 识别问题、`parsing` 版式/行列问题、`rule_gap` 规则未命中、`parameter_missing` 缺基线/利率/授权、`false_positive` 干净件误报、`verdict_logic` 五态合成偏差。
- 内容层失败若已归因为识别问题，评测继承为 `recognition`，不判成材料问题（对应 V3）。
- 报告不含时间戳，同一输入两次输出一致（对应 V5）；失败样本带页码、行号与坐标（对应 V6）。
- 当前样本 6 份：通过 6，五态/笔数/失败码召回/伪造检出均 100%，干净件误判 0%；仅代表合成样本，不代表真实客群分布（V2 的十份真件尚未具备）。

# 性能压测当前口径

`python -m algorithm.algo.perf` 生成 3000 笔工行式电子流水（75 页，40 笔/页），对「解析 → 内容 → 文件 → 账务 → 外部 → 五态 → 标签 → 剔除 → 指标 → 报告」整链路计时。

```text
默认：python -m algorithm.algo.perf
自定规模：python -m algorithm.algo.perf --rows 3000 --runs 100 --warmup 5
写 JSON：python -m algorithm.algo.perf --json report.json
保留样本：python -m algorithm.algo.perf --keep path/to/stress.pdf
```

| 指标 | 口径 |
| --- | --- |
| 计时范围 | 每轮完整链路；不含 PDF 生成与文件读取 |
| 分位数 | 线性插值（与 numpy 默认一致）；P99 用全部计时轮次 |
| 验收 | P99 ≤ 5000 ms；解析笔数不等于造数直接判失败 |
| 退出码 | 0 达标；1 P99 超时；2 输入或解析异常 |

- 2026-10-29 本机基线（Windows / Python 3.12.4，100 次计时）：P50 1881.8 ms、P95 1953.1 ms、P99 2017.8 ms。
- 分段均值：解析 813 ms、文件层 860 ms、规则 150 ms、指标 27 ms，其余均在 20 ms 内。
- 电子件文字层已改由 PyMuPDF 抽取，pdfplumber 仅在解析不到明细时回退；这是 P99 从 7.1 s 降到 2.0 s 的主要原因。
- 样本为合成电子件且 75 页，超出 proposal「十页以内」的参考边界；影像件含 OCR，不在本次压测范围。

# 输出约束

- 不给评分、等级、建议。
- 每条判断挂 rule_code 与位置。
- 指标带 caliber_version。
