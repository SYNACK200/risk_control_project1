> 这是什么：后端任务书（v2 交接版，FastAPI + MySQL）· 谁写：AI 维护，人审 · 何时更新：每轮
> 规则：**没有验收命令的条目不许进表**。版本：v2.0.0（2026-10-30）。

# 一、接手第一步（约 40 分钟）

| # | 动作 | 命令 | 通过标准 |
| --- | --- | --- | --- |
| 1 | 拉代码 | `git pull origin dev` | 最新提交 |
| 2 | 装依赖 | `cd backend && pip install -r requirements.txt` | 无报错 |
| 3 | 建库 | MySQL 建库 risk_control（启动会自动建库建表） | 11 张表出现 |
| 4 | 起服务 | `MYSQL_PASSWORD=你的密码 python -m uvicorn main:app --port 8000` | /health 返回 ok |
| 5 | 冒烟上传 | `curl -X POST 127.0.0.1:8000/api/v1/tasks -F file=@样例.pdf` | 返回 task_id 与 txn_count |
| 6 | 看库 | `SELECT COUNT(*) FROM task;` | 与返回一致 |

# 二、v2 基线（已完成，别重写）

| 能力 | 位置 | 验收 |
| --- | --- | --- |
| 11 张表 + 启动自动建表 | `db/models.py`、`db/session.py` | SHOW TABLES 见 11 张 |
| 受理 `POST /tasks`（含 E_ENCRYPT、模板选择、审计） | `routers/tasks.py` | 返回 202 与 carrier/txn_count |
| 任务/明细/指标/报告查询 | `routers/tasks.py`、`routers/reports.py` | GET reports/{id} 返回 13 字段 |
| 模板增查/启用/外推 | `routers/templates.py` | 外推返回 field_map + provenance |
| 识别自检写入 check_result | `services/analysis.py` | 任务详情含 self_check 七项 |

# 三、待办

## P0（阻塞下一版）

| 状态 | 编号 | 目标 | 为什么 | 涉及文件 | 验收命令 |
| --- | --- | --- | --- | --- | --- |
| [x] | BE-54 | 数据隔离：task.user_id 归属；列表/详情/报告/导出按角色过滤；回收站/模板/阈值/实体/审计仅银行侧 | 借款侧不能看到别人的流水 | routers/tasks.py、reports.py、各管理路由 | 借款侧 3 条 / 银行侧 15 条；借款侧 /entities 403 |
| [x] | BE-53 | 账号体系：app_user 表、PBKDF2 密码、HMAC 令牌（12h）、/auth/register|login|me|change-password|users；首次启动种 admin | 之前只有共享口令，无法区分用户与角色 | db/models.py、helpers/security.py、routers/auth.py | 注册/登录 200；错令牌 401 |
| [x] | BE-52 | 模板生命周期接口：编辑出新版本、复制、停用、删除（被用过 409）、统计、试跑、导出、导入 | 模板只启用不管理，出错无法修也无法验证 | routers/templates.py | 统计/复制/试跑/导出均 200；试跑 570 笔 |
| [x] | BE-51 | 导出接口：/tasks/{id}/transactions.csv（UTF-8 BOM+CRLF）与 /tasks/{id}/export.json（报告+明细）；已删除流水 404 | 审批与归档需要离开系统也能看 | routers/tasks.py | CSV 192 行、JSON 191 笔，均 200 |
| [x] | BE-50 | 流水回收站：deleted_at 软删除 + 幂等迁移补列；recycle/restore/purge 三个批量接口；列表支持 trash=1；实体与合并只看在用 | 流水只增不减会淹没问题记录 | db/models.py、db/migrate.py、routers/tasks.py | 回收 14→12、恢复 12→13、purge 需 confirm 且级联删明细 |
| [x] | BE-49 | 阈值版本落库 threshold_profile + GET/PUT /thresholds、reset；受理与重解析改用当前生效版本，报告记录 threshold_version | 改参数必须可追溯，旧报告不能变 | db/models.py、services/thresholds.py、routers/thresholds.py、services/analysis.py | v2→v3（DTI 0.65）→v4（默认）；重解析报告 threshold_version=4 |
| [x] | BE-20a | 本地口令保护：/bank 与写接口要求口令（先做单口令，不做完整 RBAC） | 现在任何能访问 8000 的人都能看报告 | `helpers/security.py`、路由依赖 | `cd backend && py -m pytest tests -q`（Bearer 缺失 401、正确口令 200） |
| [x] | BE-48 | 人工白名单：POST /tasks/{id}/whitelist，写 check_result.whitelist 与审计；汇总返回 whitelisted | 自己造的数据需要显式放行而不是改结论 | routers/tasks.py、services/summary.py | 任务 7 whitelisted=true，理由入库 |
| [x] | BE-47 | 重解析支持指定模板并重建明细：POST /tasks/{id}/reanalyze 收 template_id，删除旧 txn/metric_value 后按新结果写入 | 之前只换报告不换明细，等于白重算 | routers/tasks.py | 任务 7 重解析后 txn 570、metric_value 40 |
| [x] | BE-45 | 实体接口：GET /entities、/entities/methods、/entities/merge（含口径说明、警告、不支持项） | 前端不重复定义合并口径 | routers/entities.py | 三个接口 200；merge 返回 6 指标 + 口径说明 |
| [x] | BE-44 | 解析结果汇总接口：GET /tasks 返回合格性/风险/解析质量等汇总与 facets，支持多维筛选 | 前端不应各算一套 | services/summary.py、routers/tasks.py | 返回 items/total/facets；筛选生效 |
| [x] | BE-43 | POST /tasks/{id}/reanalyze：按原文件重跑并写入新版本（payload.version 递增） | v2.4.0 前的旧报告没有逐项结果，只能解释不能补 | routers/tasks.py | 旧任务重算后 checks 齐全，version 递增 |
| [x] | BE-42 | 受理阶段预读拦截：非流水返回 422 E_NOT_STATEMENT（附 preread 明细），预读写入 check_result.preread | 无关文件不能进流水解析与报告 | routers/tasks.py | 上传合同 PDF 返回 422；上传流水 200 且 check_result.preread 有值 |
| [ ] | BE-39 | 报告输出 authenticity_summary（level/label/未通过层/受限数） | 前端自算会与导出/审计不一致 | `algo/report.py` 调用链 + `schemas` | 报告 JSON 含该字段，页面与它一致 |
| [ ] | BE-31 | `POST /templates/dry-run`：传样例与 field_map，返回抽取值、条数、自检三项 | 标注页需要即时反馈 | `routers/templates.py` | 返回明细条数与自检结果 |
| [x] | BE-33 | 口令次数上限与审计（PDF/zip 均 3 次，口令不落库） | 现在前端有提示，后端不限次 | `routers/tasks.py` + `audit_log` | `cd backend && py -m pytest tests -q`；实现按 file_id 统计 3 次失败，第 4 次 `E_LIMIT`，审计不含口令 |
| [~] | BE-32 | 补件：`POST /tasks/{id}/supplement` 追加 task_file，不新建任务 | 缺件场景走不通 | `routers/tasks.py`、`services/workflow.py` | 已验证仅 `NEED_SUPPLEMENT` 可转 `PARSING` 且追加材料不新建任务；待 BE-09 队列完成多材料重跑并让报告 materials 变为 2 份 |

## P1

| 状态 | 编号 | 目标 | 为什么 | 验收命令 |
| --- | --- | --- | --- | --- |
| [ ] | BE-09 | 解析投递改队列（现在是同步阻塞） | 大文件会占满 worker | 上传后立即返回 202，状态可轮询到 DONE |
| [ ] | BE-15 | 报告导出（异步作业 + 水印 + 留痕） | 审批要归档 | 导出任务完成后可下载且留审计 |
| [x] | BE-21 | 审计查询接口（按任务/操作人/时间） | 现在只能查库 | `cd backend && py -m pytest tests -q`；`GET /api/v1/audit` 支持对象、操作人、动作、时间与分页过滤 |
| [x] | BE-02 | 启动检查补：数据库连不上给出可读提示 | 现在报错栈难懂 | `cd backend && py -m compileall -q .`；启动阶段捕获 MySQL/SQLAlchemy 连接错误并输出配置指引 |

## P2

| 状态 | 编号 | 目标 | 涉及文件 |
| --- | --- | --- | --- |
| [ ] | BE-17 | 批量导入与命中清单 | 新模块 |
| [ ] | BE-23/24 | 载体判定与图片三关细化（当前只分电子/影像） | `services/analysis.py` |

# 四、边界

| 不许做 | 原因 |
| --- | --- |
| 改 `contract.md` 的表结构与字段语义 | 改契约先提 PM/PD |
| 把口令、密钥写进代码或仓库 | 只走环境变量 |
| 用 SQLite 替代 MySQL | 规范禁止 |
| 在接口里返回完整账号/姓名 | 字段级脱敏是硬要求 |

# 五、已完成清单（历史）

| 编号 | 内容 |
| --- | --- |
| BE-34~BE-38 | 11 表、受理、查询、模板增查启、外推 |
| BE-41 | 受理时执行识别自检并落 check_result |
| BE-01~BE-08 部分 | 骨架、config、连接池、日志、建表 |
