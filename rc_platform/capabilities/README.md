# 能力目录约定

一个能力 = 一个子目录，最少三样：

```
capabilities/<名字>/
  __init__.py
  plugin.py     # 必须存在，注册表按它发现能力
  README.md     # 这个能力吃什么、产什么、什么条件下关掉
  tests/        # 只测本能力，不测别人
```

`plugin.py` 里用 `@capability` 声明四件事：`name` / `version` / `requires` / `provides`，
并实现 `run(ctx, inputs) -> 契约对象`。

**主干永不 import 这里的任何东西。** 注册表扫描到就装配，扫不到就降级。

## 当前能力（M1 兼容层）

| 能力 | 产出 | 依赖 | 说明 |
| --- | --- | --- | --- |
| `preread.algorithm_compat` | profile | document | 复用封存版本预读 |
| `parse.algorithm_compat` | statement | document, profile | 复用封存版本三级保底解析 |
| `verify.algorithm_compat` | verification | document, profile, statement | 复用封存版本四层核验 |
| `metrics.algorithm_compat` | metrics | statement | 复用封存版本 40 项指标 |
| `report.algorithm_compat` | report | profile, statement, verification, metrics | 复用封存版本报告聚合 |

这些是**过渡实现**：M2 起 `parse` 拆成模板快通道与无模板主干两条能力，M3 起指标改由特征库派生。
替换方式是「加一个新能力 + 配置里指定它」，旧的不删，留作对照与回滚。
