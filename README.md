# 智能风控 · 银行流水分析与真实性核验（信贷项目一）

> 模拟银行内部自建系统：借款人上传个人流水，银行侧得到**五态结论 + 四层核验 + 40 项指标 + 报告**。
> 当前版本 **v2.2.0**：本地与服务器均已跑通「上传 → 受理 → 解析 → 四层 → 指标 → 报告 → 落库 → 页面查看」。

## 这是什么 / 不是什么

| 是 | 不是 |
| --- | --- |
| 银行内部自建的风控工具，单份报告仅银行侧可见 | 不是对外 SaaS，借款人看不到任何结论 |
| 真实性校验优先：先证明「数据靠不靠谱」，再谈指标 | 不是「给个分」，也不输出「真实/伪造」的鉴定 |
| 金额、口径、版本都可追溯的工程实现 | 不是一次性脚本或 Demo 截图 |

## 当前能力（v2.2.0）

| 模块 | 已具备 |
| --- | --- |
| 受理 | 只要求流水文件；PDF/JPG/PNG；加密件返回 E_ENCRYPT 并可输口令；zip 代解 |
| 解析 | 模板解析 + 通用兜底；**少量标注外推**（标 3 处即可出整表） |
| 真实性 | 载体层 / 内容层 / 账务层 / 外部层；识别自检七项（金额·日期·余额回查、跨引擎、行数守恒、余额链、方向） |
| 结论 | 五态：未发现异常 / 存在不一致 / 余额可疑 / 来源可疑 / 无法判定 |
| 指标 | 40 项，口径版本 `METRIC_SET_VERSION=2`（月均按实际覆盖自然月折算） |
| 报告 | 13 字段；真实性总结常显、明细折叠；资金全景图表 |
| 银行侧 | 任务列表、报告详情、模板标注、模板管理（含外推面板） |
| 借款人侧 | 上传、加密件口令、进度查询；只显示收件状态 |

## 快速开始

### 0. 前置

| 依赖 | 版本 |
| --- | --- |
| Python | 3.11+ |
| Node.js | 20+ |
| MySQL | 8.x（库会自动创建，数据表自动建） |

### 1. 后端

~~~bash
cd backend
pip install -r requirements.txt
MYSQL_PASSWORD=你的密码 python -m uvicorn main:app --host 127.0.0.1 --port 8000
curl -s http://127.0.0.1:8000/health   # {"status":"ok"}
~~~

### 2. 借款人端（5173）

~~~bash
cd frontend && npm install && npm run dev
~~~

### 3. 银行侧（5174）

~~~bash
cd frontend-admin && npm install && npm run dev
~~~

### 4. 跑一份流水

浏览器打开 5173 上传样例 PDF；或直接调接口：

~~~bash
curl -X POST http://127.0.0.1:8000/api/v1/tasks -F file=@样例.pdf
# 返回 {task_id, biz_no, status, carrier, txn_count}
curl -s http://127.0.0.1:8000/api/v1/reports/1 | head -c 300
~~~

## 验收命令

| 项 | 命令 | 期望 |
| --- | --- | --- |
| 算法单测 | `python -m pytest algorithm/tests -q` | 176 passed |
| 借款人端构建 | `cd frontend && npm run build` | 无 TS 报错 |
| 银行侧构建 | `cd frontend-admin && npm run build` | 无 TS 报错 |
| 离线出报告 | `python algorithm/local_run.py 样例.pdf --template algorithm/integration/samples/icbc_template.json` | 输出 summary 与报告 JSON |
| 数据库 | `SHOW TABLES;`（库 risk_control） | 11 张表 |

## 目录结构

| 目录 | 内容 |
| --- | --- |
| `proposal.md` `contract.md` `forbidden.md` | 产品定位、接口契约（12 接口 / 11 表 / 11 错误码 / 8 状态）、禁止事项 |
| `V2任务分派.md` | 组员入口：各板块 P0 第一件、分支流程、三条红线 |
| `frontend/` | 借款人端（React 19 + Vite，5173） |
| `frontend-admin/` | 银行侧（5174）：任务/报告、模板标注、模板管理 |
| `backend/` | FastAPI + SQLAlchemy，11 张表，受理/查询/模板接口 |
| `algorithm/` | 解析、四层核验、40 指标、报告、自检、外推 |
| `data/` `deploy/` | 数据与迁移规划；部署脚本与服务器现状 |
| `需求分析/` `方案设计/` `技术调研/` | 需求、产品设计、技术选型（含隐私与印章方案） |

## 五个必须懂的概念

| 概念 | 要点 |
| --- | --- |
| **三类载体** | 电子件（有文字层）/ 影像件 / 截图件；结论上限不同：截图件封顶「来源可疑」 |
| **四层核验** | 载体层 → 内容层 → 账务层 → 外部层；**不可算 ≠ 通过** |
| **五态结论** | 未发现异常 / 存在不一致 / 余额可疑 / 来源可疑 / 无法判定 |
| **口径版本** | 指标集与阈值各有版本号，旧报告永不重写 |
| **证据** | 每条结论带交易号、页码、坐标、规则编号；给不出就不进报告 |

## 已知限制（下一版要解决）

| # | 限制 | 影响 |
| --- | --- | --- |
| 1 | 后端无登录鉴权 | 公网/局域网暴露即裸奔，演示也建议加口令 |
| 2 | 影像件 8 项像素取证未做 | 图片件结论封顶「无法判定」 |
| 3 | 印章校验未实现（仅设计） | 无法判断「谁出的」 |
| 4 | 证据坐标多为空 | 报告能说结论，不能跳到原文位置 |
| 5 | 招行方向识别不可靠 | 该版式收入类指标只能给 null |
| 6 | 解析同步执行 | 大文件会占满 worker，需队列 |

## 三条红线

| # | 红线 |
| --- | --- |
| 1 | 真实客户流水、口令、密钥**不得**进仓库、日志或公网演示 |
| 2 | 金额一律 DECIMAL/字符串，禁止 float |
| 3 | 契约（`contract.md`）与禁止事项（`forbidden.md`）由 PM/PD 维护，改动先提审 |

## 贡献流程

~~~bash
git pull origin dev
git checkout -b feat/模块-任务号
# 改完自测（见上文验收命令）
git add -A && git commit -m "feat(模块): 任务号 + 一句话"
git push -u origin feat/模块-任务号
# GitHub 提 PR → 目标分支 dev
~~~

各板块任务书：[`frontend/tasks.md`](frontend/tasks.md)、[`frontend-admin/tasks.md`](frontend-admin/tasks.md)、[`backend/tasks.md`](backend/tasks.md)、[`algorithm/tasks.md`](algorithm/tasks.md)、[`data/tasks.md`](data/tasks.md)。

## 版本

| 标签 | 内容 |
| --- | --- |
| `v2.0.0` | 业务流程闭环 + 图表 + 标注外推 + 识别自检 + 部署资产 |
| `v2.1.0` | 指标口径 v2（月均按自然月）+ 五板块任务交接文档 |
| `v2.2.0` | PR#5 合并：进度页、授权提示、上传区、FE-38 试解析接真实接口 |

## 账号与登录

| 端 | 地址 | 账号来源 |
| --- | --- | --- |
| 借款侧 | http://127.0.0.1:5173 | 页面自助注册 / 登录 |
| 银行侧 | http://127.0.0.1:5174 | 首次启动自动创建 admin（ADMIN_PASSWORD 或随机写入 backend/.admin_password），登录后请改密 |

- 令牌 12 小时有效；密码 PBKDF2-SHA256 存储；借款侧只看自己的流水。
- 生产必须设置 \`AUTH_SECRET\`（否则用默认密钥）并启用 HTTPS。
## 部署与运行

见 [部署与运行.md](部署与运行.md)。
一句话：复制 .env.example 为 .env 填好 MySQL 密码，Windows 跑 scripts/start_windows.bat，Linux 跑 ./scripts/start_unix.sh；一个后端进程同时托管 API 与两个前端（/ 借款侧，/bank/ 银行侧）。
