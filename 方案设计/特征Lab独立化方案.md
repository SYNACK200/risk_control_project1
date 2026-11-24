# 特征 Lab 独立化方案（v3 需求定稿）

> 这是什么：把特征 Lab 从业务系统里拆成**独立服务**的需求与设计定稿 · 谁写：PM/PD（本次由 Lead 代拟，已过用户决策）
> 何时更新：Lab 契约变更前 · 下游：`contract.md`（接口契约）、`任务书/`（本周派活）

## 一、为什么要拆

现状（实测，不是推测）：

| 事实 | 位置 |
| --- | --- |
| Lab 的 16 个接口是**挂在业务后端进程里**的 | `backend/main.py` → `include_router(rc_router, dependencies=[Depends(require_banker)])` |
| Lab 与业务系统共用一套 JWT 鉴权 | 同上 |
| Lab 的入口只是业务系统侧栏的一个菜单项 | `web/src/pages/banker/BankerApp.tsx`「参数 → 特征 Lab」 |
| 特征内核与业务代码物理同仓、可互相 import | `rc_platform/capabilities/features/*` 被 `backend` 直接引用 |

新要求：**特征是独立能力**。业务系统把读到的流水发给特征服务，拿到反馈（run 句柄 + 指标清单），再按需通过 API 取具体指标值。它要能被单独部署、单独演示、单独交付给其他团队。

## 二、已定决策（用户 2026-11-21 拍板）

| # | 决策 | 选定 |
| --- | --- | --- |
| 1 | Lab 形态 | 独立进程 + 独立端口，**同仓独立包** `lab_service/` |
| 2 | 反馈语义 | 提交 → 返回 **run_id + 指标清单**，再按 run_id 取数值 |
| 3 | 输入边界 | **结构化流水 JSON 为主**，原始 PDF 作可选入口 |
| 4 | 本周范围 | 前端信息架构**全量重组**也纳入本周 |
| 5 | 前端方式 | 在现有 `web/` 上重组（不推倒重写） |
| 6 | Lab 前端 | Lab **自带轻前端**（与服务同源）；业务系统前端不直连 Lab |
| 7 | 鉴权 | **服务间 API Key**（`X-Api-Key`） |
| 8 | 任务书 | 四份：前端 / 后端（含 Lab）/ 算法 / 数据 |
| 9 | 旧接口 | 业务后端**保留代理**指向新 Lab，4 周后下线 |
| 10 | run 存储 | Lab 自己的 MySQL 表，**保留 30 天** |

## 三、目标形态

```
┌──────────────┐   ①POST /v1/runs（rows JSON）    ┌────────────────────┐
│  业务系统     │ ───────────────────────────────▶ │  特征 Lab 服务      │
│  backend     │ ◀── ②run_id + 指标清单 ────────── │  lab_service:8030  │
│  :8010       │   ③GET /v1/runs/{id}/features    │                    │
└──────────────┘ ───────────────────────────────▶ │  features 内核      │
        ▲                                         │  lab_run 落库       │
        │ 兼容代理（4 周）                          └────────────────────┘
┌──────────────┐           静态页 /ui                       ▲
│ 业务前端 web │                            ┌───────────────┘
└──────────────┘                            │ 服务间 X-Api-Key
                                   ┌────────┴────────┐
                                   │ Lab 自带轻前端   │
                                   └─────────────────┘
```

- 端口：**8030**（8010 业务后端、8020 旧 Lab 调试口、5175 SPA 已占用）
- 目录：`lab_service/`（新包）；**只读依赖** `rc_platform.capabilities.features` 作为算法库，不改其代码
- 旧 `rc_platform/api/app.py` 里的 lab 路由在兼容期结束后移除

## 四、接口契约（v3）

### 4.1 通用

| 项 | 约定 |
| --- | --- |
| 基址 | `http://127.0.0.1:8030` |
| 鉴权 | `X-Api-Key: <LAB_API_KEY>`；`/healthz` 与 `/ui/**` 豁免 |
| 错误信封 | **沿用现有风格**：`{"detail":{"code":"E_XXX","message":"中文说明"}}`。**不引入第二套 `{code,message,data}` 信封**——那是 v2 文档里的历史约定，实现从未采用 |
| 金额 | 一律**字符串**传输（`"9671.74"`），禁止 JSON 浮点 |
| 时间 | ISO 8601 带 +08:00 |
| 幂等 | 同一 `request_hash`（profile+rows 的规范化哈希）在有效期内重复提交，返回**同一个 run_id** |

### 4.2 提交一次计算

`POST /v1/runs` → `201`

```jsonc
// 请求
{
  "profile": { "carrier": "electronic", "bank_code": "CCB",
               "period": { "start": "2021-05-12", "end": "2022-05-12" } },
  "rows": [ { "txn_date": "2021-05-13", "trade_time": "10:12:00",
              "direction": "in", "amount": "9671.74", "balance": "9691.67",
              "summary": "工资", "counterparty_name": "某公司", "reference_no": "..." } ],
  "codes": ["f_in_total", "f_in_cv"],   // 省略 = 算全部
  "client_ref": "task-167"              // 业务侧追踪号，可选
}

// 响应
{
  "run_id": "run_9f3c1a2b",
  "status": "succeeded",
  "rows": 570,
  "feature_catalog_version": "1.0",
  "created_at": "2026-11-21T21:00:00+08:00",
  "expires_at": "2026-12-21T21:00:00+08:00",
  "available":   [ { "code": "f_in_total", "name": "入账总额", "unit": "元", "category": "基础统计" } ],
  "unavailable": [ { "code": "f_night_count", "reason": "缺 trade_time 列" } ]
}
```

**这就是「反馈」**：业务系统拿到 `run_id` 与 `available` 清单，就知道这份流水能问出哪些指标，不能问的也带着原因。

### 4.3 按 run_id 取指标（"从反馈中调用特征指标"）

`GET /v1/runs/{run_id}/features?codes=f_in_total,f_in_cv` → `200`

```jsonc
{ "run_id": "run_9f3c1a2b",
  "items": [ { "code": "f_in_total", "name": "入账总额", "value": "596599.17",
               "unit": "元", "category": "基础统计", "reason": null, "version": "1.0" },
             { "code": "f_night_count", "value": null, "reason": "缺 trade_time 列" } ] }
```

规则：**算不出来就 `value: null` + `reason`，绝不返回 0**（沿用项目既有红线）。

`GET /v1/runs/{run_id}/features/{code}` → 单条（结构同上）
`GET /v1/runs/{run_id}` → run 概要（状态、行数、版本、创建/过期时间、可用统计），不含数值

### 4.4 目录与试算

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/v1/catalog/features?category=&q=` | 46 个内置特征的 code/名称/单位/分类/口径说明/表达式 |
| GET | `/v1/catalog/operators` | 83 个算子（供 Lab 前端与自定义特征） |
| POST | `/v1/expr/evaluate` | 表达式试算（带 rows 或 sample），返回数值或序列预览 |
| POST | `/v1/runs/file` | 可选入口：直接传 PDF（multipart），内部解析后再走 `/v1/runs` 同一套落库 |
| GET | `/healthz` | `{"status":"ok","catalog_version":"1.0","db":"ok"}` |

### 4.5 上限与拒绝

| 项 | 值 | 超限行为 |
| --- | --- | --- |
| 单次 rows | 20000 行 | `413 E_LIMIT` |
| 单次 codes | 200 个 | `400 E_PARAM` |
| rows 总字节 | 32 MB | `413 E_LIMIT` |
| 未知 code | — | `404 E_NOT_FOUND`，列出未知项 |
| 缺 Key / Key 错 | — | `401 E_AUTH` |

## 五、兼容与迁移（4 周）

| 阶段 | 业务后端行为 | 前端行为 |
| --- | --- | --- |
| W47（本周） | 新增 `lab_bridge`：`/api/v1/features/*`、`/api/v1/lab/*` **原样反代**到 8030 并注入 Key；旧行为不变 | 不变（继续打业务后端） |
| W48–W50 | 代理保留；业务侧新增一键盘走 `lab_client` 直连 | 特征入口页改为跳 Lab 独立前端 |
| W51 | 删除代理；移除 `rc_platform/api/app.py` 中的 lab 路由 | 只走 Lab 独立前端 |

代理铁律：**只转发、不改字段、不改状态码**，否则旧测试与旧前端会在半夜一起挂。

## 六、Lab 自带轻前端（同源）

- 位置：`lab_service/static/`，由 Lab 服务 `StaticFiles` 挂在 `/ui`
- 技术：**纯 HTML + 原生 ES module + 一份 CSS**，零构建、零 npm（"轻"就是这个意思）
- 页面：
  1. `/ui` 目录页：46 特征按分类分组 + 分类筛选 + 每个特征的表达式与口径说明
  2. `/ui/try` 试算页：粘贴/上传 rows JSON 或 PDF → 提交 → 展示 run_id、可用/不可算清单、结果表
- 它直接同源调 `/v1/*`（`X-Api-Key` 由页面向用户要一次并存在 sessionStorage；仅内网演示用）

## 七、验收标准（本周）

1. `python -m uvicorn lab_service.main:app --port 8030` 能起；`/healthz` 返回 ok
2. 业务系统用 `lab_client` 提交一份真实流水 → 拿到 run_id 与 available 清单 → 按 code 取到数值
3. 同一份 rows 重复提交返回同一 run_id（幂等）
4. 无 Key 请求 401；超 20000 行 413
5. `/ui` 能打开、能试算、能看到 46 个特征
6. 旧前端 Lab 页在不改一行代码的情况下仍可用（走代理）
7. 业务后端移除对 `rc_platform.api.app` 的 lab 依赖后，业务主链路测试仍全绿

## 八、明确不做（本周）

- 不做 Lab 的多租户/计费
- 不做特征在线学习、离线训练
- 不做跨库联邦查询（run 结果只存在 Lab 自己的表）
- 不重写解析器（解析责任仍在业务/算法侧，Lab 只收结构化 rows；PDF 入口仅调试用）
