# 特征 Lab：把「衍生能力」与「风控特征」分开摆出来

> 日期 2026-11-10 · 分支 `rebuild/v1`

## 为什么要有这一页

特征衍生与个人流水风控里的「特征」是**有耦合但实质不同**的两件事：

| | 特征衍生（通用能力） | 个人流水风控特征（域内口径） |
| --- | --- | --- |
| 是什么 | 算子库 + 表达式引擎 + 数据帧 | 建立在引擎之上的一组具体口径（f_in_total、f_night_out_share…） |
| 谁维护 | 算法侧 | 业务 + 算法共同定义 |
| 变了会怎样 | 影响所有特征 | 只影响引用它的指标与报告 |

以前这两层混在一起：算子藏在 `operators.py`、口径写在 `defs.py`、指标又在另一处再写一遍。
特征 Lab 把它们分开呈现——左边是算子与内置特征库，右边是随手试算。

## 交付

| 项 | 路径 | 内容 |
| --- | --- | --- |
| 数学与微积分算子 | `capabilities/features/math_ops.py` | `pow sqrt exp ln log10 floor ceil round integrate derivative` |
| 目录口径 | `capabilities/features/library.py` | `operator_catalog()` / `feature_catalog()`，算子与特征只有一个答案源 |
| Lab API | `rc_platform/api/app.py` | `/lab/operators`、`/lab/features`、`/lab/samples`、`/lab/evaluate` |
| Lab 页面 | `web/src/pages/banker/LabPage.tsx` | 特征/算子双栏 + 样本选择 + 表达式编辑器 + 示例快捷键 + 结果 |
| 路由 | `/bank/lab` | 侧栏「参数 → 特征 Lab」 |

## 算子能力（对齐 pandas 的思路，落到流水场景）

| 类别 | 已有 | 本轮新增 |
| --- | --- | --- |
| 基础运算 | `+ - * /`、`neg`、`abs` | — |
| 乘方开方 | — | `pow`、`sqrt` |
| 对数指数 | — | `ln`、`log10`、`exp` |
| 取整 | — | `floor`、`ceil`、`round` |
| 积分/微分 | `cumsum`、`diff1` | `integrate`、`derivative(order=n)` |
| 逻辑与比较 | `gt ge lt le eq ne and or not if_else` | — |
| 分组 | `group_by*`、`sum_by`、`mean_by`、`count_by`、`distinct_count`、`rank_by`、`monthly_agg` | — |
| 时间窗 | `within_days`、`between_dates`、`by_hour`、`hour_band`、`by_dow` | — |

离散序列的微积分口径写在模块头注释里，避免各处自己解释：
积分 = 累加（离散点上没有连续积分，累加是唯一不引入假设的做法）；
微分 = 相邻差分，可指定阶数；两者互逆但先微分再积分会丢首项，不补 0 假装没丢。

## 验收（真服务实测）

```
GET  /api/v1/lab/operators  → 70 个算子
GET  /api/v1/lab/features   → 24 个内置特征
POST /api/v1/lab/evaluate {"sample":"clean/icbc.pdf","expr":"sum(amount, where=direction=='out')"}
     → 3450.50（Decimal，6 笔）
POST ... {"expr":"sqrt(sum(amount, where=direction=='out'))"}   → 58.74095675080548
POST ... {"expr":"derivative(monthly_values(agg='count'))"}     → [null,"0"]（Series，带预览）
```

页面渲染（1440×805）：左栏「内置特征 24 / 算子 70」双页签 + 搜索，右栏样本选择、表达式框、
九个示例快捷键、结果卡片。构建 `tsc -b` 0 错误，银行侧分包 34.07 kB。

## 安全边界（当前是临时状态）

Lab API 只监听 127.0.0.1、只对**合成样本**试算、**没有鉴权**。
正式接进主应用时必须补：登录校验、只允许对自己有权的数据试算、审计留痕。
这条写在这里，不许当成已经做完。

## 还没做

- **自定义特征的持久化**：现在只能试算，不能保存。要保存得先定「存哪、按什么版本管、谁能改」——
  老系统的 `custom_metric` 表是前车之鉴（只存了 steps，没版本管理，改了口径无法追溯）。
- 特征 Lab 里的「保存到特征库」与「发布为指标」两条动作。
- 分组结果的可视化（现在返回的是值或序列）。
