# 特征衍生能力（features）

> 能力名：`features.derivation`（产出 `features`，依赖 `statement`）。
> 一句话：把「算子」写成代码插件，把「特征」写成可配置的表达式或步骤，产物是一张带版本、带缺失原因的特征表。

## 为什么这样切

老版本的元算子只有加减乘除，业务想说「夜间出账占全部出账的比例」必须找算法改代码。
这里把两件事分开：

- **算子**（算法侧）：纯函数，注册进算子库，写一次到处能用
- **特征**（业务侧）：用算子拼出来，可以是表达式，也可以是步骤 JSON

两者共用同一个执行核，不会出现「表达式一套口径、步骤另一套口径」。

## 表达式语法（可用的子集）

```
expr    := ternary
ternary := or_expr [ "if" or_expr "else" ternary ]
or_expr := and_expr { "or" and_expr }
and_expr:= not_expr { "and" not_expr }
not_expr:= "not" not_expr | compare
compare := additive [ ("=="|"!="|">="|"<="|">"|"<") additive ]
additive:= multiplicative { ("+"|"-") multiplicative }
multiplicative := unary { ("*"|"/") unary }
unary   := ("-"|"+") unary | primary
primary := NUMBER | STRING | true | false | none | null
         | NAME "(" [args] ")"      # 函数调用即算子调用
         | NAME                     # 列引用（一列值，与行对齐）
         | "(" expr ")"
args    := arg { "," arg }
arg     := [ NAME "=" ] expr
```

要点：

- 有 `where=` 具名参数，`sum(amount, where=direction=='out')` 就是「出账求和」
- 三值逻辑：`none` 参与算术得 `none`，`none and false` 得 `false`，`none or true` 得 `true`
- 除零不抛异常，得 `none` 并写一条 note
- 写错了报 `ExprError`，消息里带原文与指针位置

## 算子清单（49 个，六族）

| 族 | 算子 |
| --- | --- |
| 数值 | `sum count mean median std max min cv pct_change diff1 cumsum window_sum last first add sub mul div neg abs` |
| 逻辑与比较 | `gt ge lt le eq ne and or not if_else` |
| 分组 | `group_by group_by_counterparty group_by_month monthly sum_by mean_by count_by distinct_count rank_by monthly_agg` |
| 时间窗 | `within_days between_dates by_hour hour_band by_dow span_days` |
| 过滤 | `filter_direction filter_amount_abs_ge filter_counterparty_contains` |

## 步骤形态

与老版本 `CustomMetric.steps` 兼容，老数据可直接跑：

```json
[{"atom": "filter_direction", "args": {"value": "out"}},
 {"atom": "sum", "args": {}}]
```

## 缺失口径（最重要的一条）

缺输入一律 `value = None` 且 `reason` 写清缺什么，**绝不填 0**。
只有「笔数 / 个数」这类空集本身就是真值的特征可以为 0。

```
f_night_count   None  笔  缺列：trade_time（该列在全部交易上都没有值）
```

原因：指标系统最坏的失败不是算错，而是缺列时悄悄给 0——下游拿 0 去评分，报告看起来很漂亮。

## 怎么加东西

加一个算子：

```python
@operator("my_op", family=NUMERIC, kind="agg", unit="元", detail="一句话说明口径")
def my_op(frame, value, **kwargs): ...
```

加一个内置特征：在 `defs.py` 的 `BUILTIN` 里加一条 `FeatureDef(code=..., expr=...)`，版本号跟着特征走。
