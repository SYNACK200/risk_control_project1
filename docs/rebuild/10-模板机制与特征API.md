# 模板机制与特征 API

> 2026-11-11 · 分支 `rebuild/v1`

## 一、模板这块现在是怎么做的

### 1. 模板是什么

模板现在**不是一张「框的死坐标表」**，而是一份「这家银行的表长什么样」的声明：

```json
{
  "page_size": {"w": 842, "h": 595},
  "page_count": 1,
  "tables": [{
    "page": 0,
    "slot": "first",
    "area": {"x": 0.02, "y": 0.08, "w": 0.96, "h": 0.90},
    "headerY": 0.0919,
    "columns": [
      {"field": "txn_date",         "fields": ["txn_date"],         "x": 0.050, "w": 0.044},
      {"field": "summary",          "fields": ["summary"],          "x": 0.212, "w": 0.018},
      {"field": "counterparty_name","fields": ["counterparty_name"],"x": 0.375, "w": 0.035}
    ]
  }]
}
```

- `columns[].x / w` 是**归一化到 0–1 的列带**（横向区间），不是单元格坐标；
- 列带只说明「这一列在这一带」，具体哪一行有值由解析器按 y 往下捡；
- `headerY` 是表头所在的高度，`area` 是表格区，`slot` 说明这页是首页/中间页/末页。

所以同一家银行换一份文件、页边距或行高略有不同，模板照样能用——这是与「死坐标模板」的根本区别。

### 2. 一条模板的一生

| 状态 | 怎么来 | 能不能用 |
| --- | --- | --- |
| `draft` | 标注画布保存 / 手工导入 | 不用（未定稿） |
| `enabled` | 管理员点「启用」（publish） | 解析时优先命中 |
| `disabled` | 管理员点「停用」 | 不用 |
| 已删除 | 「移入回收站」（软删除，写 `deleted_at`） | 不用；可「恢复」 |

同一家银行再存一条，`version` 自动 +1（不覆盖旧版本）；老报告的 `report.template_version` 指回当时那一版。

### 3. 解析时怎么用

1. 有 `enabled` 模板且档期匹配 → 直接按列带切（快通道）；
2. 没命中 → 锚点扩散自己找（`layout.anchor_spread`：表头词当种子，形态收敛，几何聚类兜底）；
3. 跑偏了 → 在标注画布上调列带、改字段名，保存出新版本。

模板是**加速层**，不是唯一路径——这条在设计上是硬约束，否则新银行第一次进来就没法解析。

### 4. 相关接口

`GET /templates`（含 `include_deleted=true`）、`GET /templates/{id}`、`POST /templates`（建草稿）、
`PUT /templates/{id}`（写 layout + field_map）、`POST /templates/{id}/publish|disable|duplicate|restore`、
`DELETE /templates/{id}`（软删除）、`GET /templates/{id}/stats`、`GET /templates/{id}/layout`、`POST /templates/probe`（预读）。

### 5. 已知短板

- 一页里有多个表格区（明细表 + 汇总表）时只输出一个 `tables[0]`；
- `field_map` 目前只记「字段 → 列序」，没有「必需列」声明，所以缺列不会在模板层报错，要到指标层才表现为「不可算」；
- 模板没有「适用档期/账户类型」的过滤条件，只能靠 bank_code 命中。

## 二、特征 API（所有特征都有接口）

### 1. 接口清单

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/features` | 全部特征目录（24 内置 + 自定义），含 code/name/unit/form/body/version/description |
| GET | `/api/v1/features/{code}` | 单个特征定义与表达式 |
| POST | `/api/v1/features/compute` | 给交易行或样本，算全部或指定特征 |
| POST | `/api/v1/features/compute-file` | 直接上传 PDF，解析 + 计算一次完成 |
| POST | `/api/v1/lab/evaluate` | 试算一条表达式（返回单值或序列） |
| GET/POST/DELETE | `/api/v1/lab/custom` | 自定义特征 CRUD（版本化） |

### 2. 请求与响应

**算指定特征（直接给交易行）**

```bash
curl -X POST http://127.0.0.1:8020/api/v1/features/compute \
  -H "Content-Type: application/json" \
  -d '{"codes":["f_txn_count","f_in_total"],
       "rows":[{"txn_date":"2026-01-05","amount":"1000","direction":"in"}]}'
```

```json
{"rows": 2, "count": 2, "version": "1.0",
 "features": [
   {"code":"f_txn_count","name":"交易笔数","value":2,"unit":"笔","reason":"","version":"1.0"},
   {"code":"f_in_total","name":"入账总额","value":"1000","unit":"元","reason":"","version":"1.0"}
 ]}
```

**传文件算特征**

```bash
curl -X POST http://127.0.0.1:8020/api/v1/features/compute-file \
  -F "file=@statement.pdf" -F "codes=f_txn_count,f_out_total"
```

**实测**（`clean/ccb.pdf`，6 笔）：`f_txn_count=6`、`f_out_total="3450.50"`。

### 3. 三条对外约定

1. **金额一律是字符串化的十进制**（`"3450.50"`），不是浮点。调用方要算就用自己的十进制库，别转 double。
2. **算不出来不算 0**：`value` 为 `null`，`reason` 写明缺什么（如「缺列：trade_time」「样本不足 2 笔」）。
3. **每个值带 `version`**：内置特征是定义版本，自定义特征是那条特征的版本号；口径变了版本必须变，否则报告无法回溯。

### 4. 鉴权现状（临时）

Lab 与特征 API 目前**只监听 127.0.0.1、没有鉴权**，只对合成样本开放。
接进正式服务前必须补：登录校验、按数据权限过滤、调用审计留痕。这一条不许当成已经做完。
