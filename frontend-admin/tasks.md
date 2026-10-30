> 这是什么：银行侧应用任务书（v2 交接版，独立应用，端口 5174）· 谁写：AI 维护，人审 · 何时更新：每轮
> 规则：**没有验收命令的条目不许进表**。版本：v2.0.0（2026-10-30）。

# 一、接手第一步（约 30 分钟）

| # | 动作 | 命令 | 通过标准 |
| --- | --- | --- | --- |
| 1 | 拉代码 | `git pull origin dev` | 最新提交 |
| 2 | 装依赖 | `cd frontend-admin && npm install` | 无报错 |
| 3 | 起后端 | `cd backend && MYSQL_PASSWORD=你的密码 python -m uvicorn main:app --port 8000` | health ok |
| 4 | 起本端 | `cd frontend-admin && npm run dev` | 5174 打开见「任务与报告」 |
| 5 | 造一条任务 | 用样例 PDF 在 5173 提交，或 POST /api/v1/tasks | 列表出现任务 |
| 6 | 看报告 | 点「查看报告」 | 结论/四层/图表/指标全部渲染 |
| 7 | 构建 | `npm run build` | 产物在 dist/ |

# 二、v2 基线（已完成，别重写）

| 能力 | 位置 | 验收 |
| --- | --- | --- |
| 任务列表 + 报告详情 | `src/components/TaskList.tsx` | 列表→报告可打开 |
| 真实性总览常显、明细折叠 | 同上 | 顶部「真实性校验：部分通过」，点开才见四层/受限/证据 |
| 资金全景图表（纯 SVG） | `src/components/Charts.tsx` | 指标卡/月度收支/余额走势/摘要结构/三件事 |
| 模板管理 + 外推面板 | `src/components/TemplateAdmin.tsx` | 填 marks → 返回 field_map 与 provenance → 存草稿 |
| 模板标注页（框画） | `src/pages/Annotate.tsx` | 载入 PDF 框选字段、导出 field_map |
| 三个页签 | `src/App.tsx` | 任务 / 标注 / 模板 |

# 三、待办

## P0（阻塞下一版）

| 状态 | 编号 | 目标 | 为什么 | 涉及文件 | 验收命令 | 依赖 |
| --- | --- | --- | --- | --- | --- | --- |
| [x] | FE-38 | 试解析接真实接口，替换 mock | 标注完看不到系统怎么读 | `Annotate.tsx`、`lib/api.ts` | 标注后调 templates/infer 返回真实列与置信度（见 `history/20261030-fe38.md`） | BE-31 |
| [ ] | FE-46 | 真实性总结改读后端 authenticity_summary | 前端自算会与导出/审计不一致 | `TaskList.tsx` | 报告 JSON 有该字段后页面只渲染 | BE-39 |
| [ ] | FE-35 | 本地口令保护 /bank/ | 银行侧不能裸奔，哪怕本地演示 | 全应用 + 后端 | 未输入口令进不去 | BE-20a |

## P1

| 状态 | 编号 | 目标 | 为什么 | 涉及文件 | 验收命令 |
| --- | --- | --- | --- | --- | --- |
| [x] | FE-58 | 本地口令门：请求统一带 Bearer；401/503 弹口令框并保存到 localStorage；银行侧与借款侧共用同一套 | 后端 BE-20a 严格保护后，前端不带口令会白屏 | frontend-admin/src/lib/auth.ts、components/AuthGate.tsx、lib/api.ts；frontend/src/lib/auth.ts、api/client.ts、components/AuthGate.tsx | 无口令→口令门；错口令→「口令不正确」；对口令→列表 15 行、报告页正常 |
| [x] | FE-57 | 报告页：解析模板下拉 + 重新解析 + 开绿灯；白名单横幅；列表页白名单标签 | 银行要能自己救回解析失败的单子 | components/ReportView.tsx、pages/TaskListPage.tsx | 任务 7 页面显示横幅与 570 笔 |
| [x] | FE-55 | 客户与账户页：冲突告警、客户选择、7 种合并方式（简约标签）、可展开说明、合并结果与账户明细 | 银行要一眼看客户整体风险，并知道怎么合的 | pages/EntitiesPage.tsx | 页面显示冲突 1 条；切换方式数值随之变化 |
| [x] | FE-54 | 列表按银行关心维度呈现并支持多维筛选：合格性、信用风险、解析质量、银行、时间、业务号 | 银行不看 status/carrier | TaskListPage.tsx | 11 条筛“中”为 3 条；叠加“不合格”为 0 并提示 |
| [x] | FE-53 | 列表与报告拆两页：/ 列表、/report/:id 详情，改用 HashRouter | 原来同页，流水一多不可用 | TaskListPage.tsx、ReportView.tsx、App.tsx | 列表点查看报告进 #/report/11，页内有返回 |
| [x] | FE-52 | 真实性校验可直达：层标签变成按钮，点一下就展开明细并滚到该层高亮；旧报告显示「重算逐项」 | 用户反馈「点不开」——层标签原本是纯文本 | TaskList.tsx | 点载体层 → 展开并定位；旧报告出现重算按钮 |
| [x] | FE-51 | 报告页预读卡：判定、置信度、银行、脱敏账户、期间、页数/文字层、疑似行数、命中特征与理由 | 审批人要知道系统在看到模板前先读到了什么 | TaskList.tsx | 报告页出现预读卡；与模板解析对照指到自检 S8 |
| [x] | FE-50 | 真实性校验逐项可展开：每个检查点显示「怎么验 + 当前结果 + 状态含义」，含四层 36 项与识别自检 S0–S7 | 只看四层状态无法判断到底验了什么 | CheckTable.tsx、TaskList.tsx | 每层每项可点开；内容层与自检也带逐项结果 |
| [x] | FE-49 | 指标逐条可展开：计算规则 + 输入 + 单项/指标集版本 + 按原始数据的图 | 审批人不能只看一个数字 | MetricExplain.tsx、TaskList.tsx、lib/api.ts | 点任一行出现「计算规则」与对应图；28/40 有图，12 项无图并说明原因 |
| [ ] | FE-47 | 证据联调：点证据跳到 PDF 对应页并高亮 | 现在证据表是死的 | `TaskList.tsx` + 新组件 | 点一条证据，PDF 翻页并框出位置 |
| [ ] | FE-48 | 报告导出 PDF（带水印、留操作人） | 审批要归档 | 新组件 | 导出 PDF 含全部区块与水印 |
| [ ] | FE-34 | 模板版本细化（对比、停用、回滚） | 现在只能启用 | `TemplateAdmin.tsx` | 可停用/回滚旧版本 |

## P2

| 状态 | 编号 | 目标 | 涉及文件 |
| --- | --- | --- | --- |
| [ ] | FE-14 | 批量筛查页（批次、清单、复核） | 新页面 |
| [ ] | FE-16 | 看板（解析量、失败率、命中分布） | 新页面 |

# 四、边界

| 不许做 | 原因 |
| --- | --- |
| 改 `contract.md` / `forbidden.md` | 契约归 PM/PD |
| 在借款人端复用本应用页面 | 一端只给一个受众 |
| 引入重型图表库 | 现有纯 SVG 已够 |
| 把真实客户流水放进样例或截图 | 公开仓库 |

# 五、材料登记

| 文件名 | 来源 | 与哪个任务相关 | 状态 |
| --- | --- | --- | --- |
| algorithm/integration/samples/icbc_template.json | 团队生成（仅坐标） | FE-38 / FE-44 | 可用 |
| src/mocks/verify_result.json、metrics_report.json、interest_rates.json | 早期示例 | FE-36/37、报告与结息展示 | 仍在使用 |
| src/mocks/ocr_lines.json | 早期示例 | 原 FE-38 假试解析 | 已删除（FE-38 接真实接口） |
