# 后端（FastAPI + MySQL）

v2 已可跑通「上传 → 受理 → 解析 → 四层核验 → 指标 → 报告 → 落库 → 页面查看」的闭环。

# 一、依赖与数据库

| 项 | 值 |
| --- | --- |
| Python | 3.11 |
| 数据库 | MySQL 8.x（本机 8.2 实测） |
| 库名 | `risk_control`（首次启动自动创建） |
| 建表 | 启动时 `Base.metadata.create_all` 自动建 11 张表 |

安装：

```bash
pip install -r requirements.txt
```

# 二、启动

数据库密码**不写进仓库**，用环境变量传：

```bash
cd backend
MYSQL_PASSWORD=你的密码 LOCAL_ACCESS_PASSWORD=本机访问口令 python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

可选环境变量：`MYSQL_HOST`（默认 127.0.0.1）、`MYSQL_PORT`（3306）、`MYSQL_USER`（root）、`MYSQL_DB`（risk_control）、`LOG_LEVEL`（INFO）。`LOCAL_ACCESS_PASSWORD` 是本地保护口令；除健康检查与借款人状态查询外，调用接口时需带 `Authorization: Bearer <口令>`。

健康检查：`GET /health` 与 `GET /api/v1/health`。

# 三、接口（已实现）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/tasks` | multipart 上传；**file 必填**，password / period_start / period_end / bank_code / source_ref 选填 |
| GET | `/api/v1/tasks` | 任务列表（最近 50 条） |
| GET | `/api/v1/tasks/{id}` | 任务状态 |
| GET | `/api/v1/tasks/{id}/transactions` | 解析出的明细 |
| GET | `/api/v1/tasks/{id}/metrics` | 40 项指标 |
| GET | `/api/v1/reports/{task_id}` | 报告 JSON（13 字段） |
| GET | `/api/v1/templates` | 模板列表 |
| POST | `/api/v1/templates` | 新建模板（草稿） |
| POST | `/api/v1/templates/{id}/publish` | 启用模板（同银行只保留一个启用版本） |

错误码：加密件返回 `400`，`detail.code = E_ENCRYPT`；解析失败返回 `500`，`E_PARSE`。

# 四、数据表（11 张）

`staff_user`、`file_obj`、`task`、`task_file`、`bank_account`、`txn`、`metric_value`、`report`、`template`、`rule`、`audit_log`。

字段按 contract.md 命名；金额用 `DECIMAL(18,2)`；JSON 列存 layers / limitations / evidence / materials。

# 五、本轮已实测

| 步骤 | 结果 |
| --- | --- |
| 上传工行加密件（口令 719028） | 202，`task_id=1`，`carrier=electronic`，`191 笔` |
| 带模板上传（bank_code=ICBC） | `task_id=3`，`template_id=1` 已记录 |
| 报告 | 13 字段，结论「未发现异常」，受限 21 条，指标 40 项（33 有值） |
| 落库 | task / txn 191 / metric_value 40 / report 1 / file_obj 1 / audit_log 1 |

# 六、已知限制（组员接手先看这里）

| # | 限制 | 影响 |
| --- | --- | --- |
| 1 | 无登录与权限 | 任何人可调接口，投产前必须补 |
| 2 | 同步解析 | 大文件会阻塞请求，后续可改队列 |
| 3 | 证据坐标多为 0 | 报告 evidence 目前无真实页面坐标 |
| 4 | 影像件未做 8 项像素取证 | 图片件结论封顶「无法判定」 |
| 5 | 口令只做内存校验 | 未做 3 次上限与审计（前端有提示，后端未限次） |
| 6 | 上传文件落本地磁盘 | 未做对象存储与清理策略 |

