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
| [x] | BE-45 | 实体接口：GET /entities、/entities/methods、/entities/merge（含口径说明、警告、不支持项） | 前端不重复定义合并口径 | routers/entities.py | 三个接口 200；merge 返回 6 指标 + 口径说明 |
| [x] | BE-44 | 解析结果汇总接口：GET /tasks 返回合格性/风险/解析质量等汇总与 facets，支持多维筛选 | 前端不应各算一套 | services/summary.py、routers/tasks.py | 返回 items/total/facets；筛选生效 |
| [x] | BE-43 | POST /tasks/{id}/reanalyze：按原文件重跑并写入新版本（payload.version 递增） | v2.4.0 前的旧报告没有逐项结果，只能解释不能补 | routers/tasks.py | 旧任务重算后 checks 齐全，version 递增 |
| [x] | BE-42 | 受理阶段预读拦截：非流水返回 422 E_NOT_STATEMENT（附 preread 明细），预读写入 check_result.preread | 无关文件不能进流水解析与报告 | routers/tasks.py | 上传合同 PDF 返回 422；上传流水 200 且 check_result.preread 有值 |
| [ ] | BE-20a | 本地口令保护：/bank 与写接口要求口令（先做单口令，不做完整 RBAC） | 现在任何能访问 8000 的人都能看报告 | `main.py`、新依赖 | 无口令访问返回 401；带口令 200 |
| [ ] | BE-39 | 报告输出 authenticity_summary（level/label/未通过层/受限数） | 前端自算会与导出/审计不一致 | `algo/report.py` 调用链 + `schemas` | 报告 JSON 含该字段，页面与它一致 |
| [ ] | BE-31 | `POST /templates/dry-run`：传样例与 field_map，返回抽取值、条数、自检三项 | 标注页需要即时反馈 | `routers/templates.py` | 返回明细条数与自检结果 |
| [ ] | BE-33 | 口令次数上限与审计（PDF/zip 均 3 次，口令不落库） | 现在前端有提示，后端不限次 | `routers/tasks.py` + `audit_log` | 第 4 次直接拒绝；审计有 3 条记录且无口令本体 |
| [ ] | BE-32 | 补件：`POST /tasks/{id}/supplement` 追加 task_file，不新建任务 | 缺件场景走不通 | `routers/tasks.py`、`task_file` | 补件后同任务重跑，材料清单变 2 份 |

## P1

| 状态 | 编号 | 目标 | 为什么 | 验收命令 |
| --- | --- | --- | --- | --- |
| [ ] | BE-09 | 解析投递改队列（现在是同步阻塞） | 大文件会占满 worker | 上传后立即返回 202，状态可轮询到 DONE |
| [ ] | BE-15 | 报告导出（异步作业 + 水印 + 留痕） | 审批要归档 | 导出任务完成后可下载且留审计 |
| [ ] | BE-21 | 审计查询接口（按任务/操作人/时间） | 现在只能查库 | GET 审计列表返回分页结果 |
| [ ] | BE-02 | 启动检查补：数据库连不上给出可读提示 | 现在报错栈难懂 | 停库后启动，日志一句话说清原因 |

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
