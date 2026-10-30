> 这是什么：接口与数据契约，跨部分唯一依据 · 谁写：PM/PD · 何时更新：接口变更前先改这里
> 权限：仅 PM/PD 可写。前端/后端/算法/数据 只读；需要改接口请写 chat.md 提案。

# 通用约定

| 项 | 约定 |
| --- | --- |
| 基址 | /api/v1 |
| 鉴权 | Bearer Token；前台 bs_token，后台 bs_admin_token，互不读取 |
| 响应 | {code, message, data}；code=0 为成功 |
| 分页 | page 从 1 起，size 默认 20，上限 100 |
| 幂等 | 创建任务以文件哈希判重，重复提交返回原 task_id；补件不判重，追加到原任务的 `task_file` 并重新进入解析 |
| 时间 | 存储与返回均为 UTC+8，带偏移 |
| 金额 | decimal(18,2)；接口用字符串传输，禁止 JSON 浮点 |
| 限流 | 单账号创建任务 10 次/分钟 |
| 支持载体 | application/pdf、image/jpeg、image/png |
| 大小上限 | PDF 20MB；图片 10MB、短边 ≥ 1000px |
| 载体判定 | 服务端判定 electronic / image / screenshot，不接受客户端自称 |

# 必填清单

**唯一必填：流水文件本身。其余一律选填。**

| 字段 | 必填 | 缺失时怎么办 |
| --- | --- | --- |
| file | **是** | 没有文件无法受理，返回 `E_FORMAT` |
| task_type | 否 | 默认 `credit` |
| period_start / period_end | 否 | 取文件内标注的期间；取不到则在报告写「期间未取得」，指标分母改用明细覆盖期 |
| password | 否 | 需要时再向客户索要，最多 3 次 |
| source_ref（来源凭证）/ source_channel | 否 | 记「来源未核验」，**不因此降低结论档位**（见真实性校验分层设计） |
| 授权勾选 | 否（业务口径） | 合规上建议保留，属产品决策项，见待确认 |

选填缺失只影响**报告里的受限说明**，不影响能否受理。

# 特殊情况：压缩包与口令

| 情况 | 处置 |
| --- | --- |
| 压缩包（zip） | **不在受理格式内**。默认要求客户解压后上传 PDF / 图片；系统可代解，但必须在界面与报告中标明「系统代解」，并留审计 |
| 压缩包口令 | 由客户提供；最多尝试 **3 次**，错误 3 次停止并转补件/人工；口令不得入库、不得写入日志 |
| PDF 自带口令 | 同上；由 `POST /tasks` 的 `password` 字段承载，仅当次有效 |
| 解压后多份材料 | 只取首个可受理件并提示客户确认；多份材料进入 `task_file` |
| 解压后体积 | 超过 200MB 拒绝（防压缩炸弹），返回 `E_FORMAT` |
| 文件名乱码 | 按 GBK / UTF-8 依次尝试解码；仍失败记为「压缩包内材料」，不得因文件名报错拒收 |
| 审计 | 每次收件、每次口令尝试（成功/失败/取消）都要留痕：时间、材料名、结果，不含口令本体 |

# 接口清单

## 任务

| 方法 | 路径 | 输入 | 成功 | 失败 |
| --- | --- | --- | --- | --- |
| POST | /tasks | multipart：**file（必填）**；task_type?、period_start?、period_end?、password?、source_ref?、source_channel? 全部选填 | 202 {task_id,status,carrier} | E_FORMAT E_ENCRYPT E_LIMIT E_IMAGE_LOWQ E_IMAGE_BLUR |
| GET | /tasks | page、size、status、task_type | 200 分页 | — |
| GET | /tasks/{id} | — | 200 详情 | 404 |
| POST | /tasks/{id}/retry | — | 202 | E_STATE |
| POST | /tasks/{id}/supplement | multipart：file | 202；追加一条 task_file（role=supplement），不新建任务 | E_STATE |
| DELETE | /tasks/{id} | — | 204 逻辑删除 | E_STATE |

## 报告（仅银行侧）

| 方法 | 路径 | 输入 | 成功 | 失败 |
| --- | --- | --- | --- | --- |
| GET | /tasks/{id}/report | — | 200 报告 | 409 未生成 E_FORBID |
| POST | /reports/{id}/export | format（pdf/docx） | 202 {job_id} | E_LIMIT |
| GET | /reports/{id}/export/{job_id} | — | 200 {url} | 404 |

## 批量

| 方法 | 路径 | 输入 | 成功 |
| --- | --- | --- | --- |
| POST | /tasks | task_type=batch，period_start/end | 202 |
| GET | /tasks/{id}/hits | page、size、rule_code | 200 命中清单 |
| PUT | /tasks/{id}/hits/{hitId} | decision、note | 200 |

## 模板与规则

| 方法 | 路径 | 输入 | 成功 |
| --- | --- | --- | --- |
| GET | /templates | bank_code、status | 200 |
| POST | /templates | field_map、version | 201 |
| POST | /templates/{id}/publish | — | 200 启用 |
| GET | /rules | category | 200 |
| PUT | /rules/{id} | expr、threshold | 200 新版本 |

## 账号与审计

| 方法 | 路径 | 输入 | 成功 |
| --- | --- | --- | --- |
| POST | /auth/login | username、password | 200 token |
| GET | /users | role、status | 200 |
| GET | /audit | object_type、object_id、page | 200 |
| GET | /settings/thresholds | — | 200 默认阈值与当前版本 |
| PUT | /settings/thresholds | 阈值项与值 | 200 新版本号 |

# 错误码

| 码 | HTTP | 含义 | 借款人可见文案 | 审批人可见文案 |
| --- | --- | --- | --- | --- |
| E_FORMAT | 400 | 非 PDF | 文件格式不支持，请上传 PDF | 格式判定失败 |
| E_BROKEN | 400 | 文件被截断 | 文件不完整，请重新下载 | 文件结构异常 |
| E_ENCRYPT | 400 | 有口令 | 文件已加密，请去掉口令 | 加密件 |
| E_NOLAYER | 400 | 无文字层 | 该文件像截图或扫描件 | 非官方导出件 |
| E_MULTI | 400 | 混装多家银行 | 一次只能传一家银行 | 来源不单一 |
| E_CHECK | 409 | 校验未通过 | 明细与合计对不上，请核对原件 | 数字核对失败，见定位行 |
| E_STATE | 409 | 状态不允许 | 当前状态不能这样操作 | 状态机拒绝 |
| E_LIMIT | 429 | 超限 | 操作太频繁或文件过大 | 触发限流 |
| E_IMAGE_LOWQ | 400 | 图片分辨率过低 | 图片太模糊，请重新拍摄或导出 | 短边不足 1000px |
| E_IMAGE_BLUR | 400 | 模糊、倾斜或反光遮挡关键字段 | 关键信息看不清，请重新拍摄 | 图片质量不达标 |
| E_AUTH | 401 | 未登录 | 登录已过期 | 令牌无效 |
| E_FORBID | 403 | 无权限 | 没有权限查看 | 越权访问 |

# 报告结构

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| carrier | string | electronic / image / screenshot |
| verdict | string | 未发现异常 / 存在不一致 / 余额可疑 / 来源可疑 / 无法判定 |
| limitations | array | 核验受限说明，例：影像件未做结构取证、无利率表未做结息反算 |
| verdict_reason | string | 触发结论的检查项 |
| layers | array | 四层各自结论：file、content、ledger、external |
| metrics | array | {code,name,value,unit,note,caliber_version}；指标集版本见 metric_set_version |
| metric_set_version | int | 指标集版本，数量可增减，历史报告按当时版本解释 |
| threshold_version | int | 阈值版本，默认值随系统发布 |
| conclusions | array | {code,level,threshold,value}，按阈值判定出的结论，银行可调阈值 |
| trend | array | {month,income,expense} |
| evidence | array | {txn_id,rule_code,page_no,x,y} |
| materials | array | 本次报告依据的材料清单 {file_id,role,pages,sha256}；role 为 original / supplement，按提交顺序 |
| version | int | 只增不改 |

# 载体与结论上限

| carrier | 结论上限 | 附加要求 |
| --- | --- | --- |
| electronic | 未发现异常 | 结构取证 11 项全部执行 |
| image | 未发现异常 + limitations 注明核验受限 | 图像取证 8 项，强制人工复核 |
| screenshot | 来源可疑（封顶） | 报告写明不得作为授信依据 |

服务端判定的 carrier 与报告中的 carrier 必须一致，不允许前端传入。

# 数据契约（十一张表）

| 表 | 关键字段 | 约束 |
| --- | --- | --- |
| staff_user | id、name、role、status | role ∈ 审批人/模板管理员/运营管理员/系统管理员 |
| file_obj | id、sha256、mime、carrier、width、height、pages、has_text_layer、storage_path | sha256 唯一；carrier ∈ electronic/image/screenshot |
| task | id、biz_no、task_type、channel、file_id、carrier、template_id、template_version、status、check_result、period_start、period_end、hits | biz_no 唯一；task_type ∈ credit/batch；carrier 冗余便于统计；file_id 仅存首份主文件，多份看 task_file |
| task_file | id、task_id、file_id、role、seq、created_at | (task_id,seq) 唯一；role ∈ original/supplement；同一任务内 file_id 不重复；补件只追加不覆盖 |
| bank_account | id、task_id、account_no、bank_name、period_start、period_end、opening_balance、closing_balance | 账号脱敏后落库 |
| txn | id、task_id、account_id、txn_date、direction、amount、balance、summary、counterparty_name、page_no、coord_x、coord_y、confidence、drop_reason | amount 恒正；按月分区；坐标与置信度用于证据回溯与失败归因，drop_reason 记录六类剔除原因 |
| metric_value | id、task_id、metric_code、metric_name、value_num、unit、note、caliber_version | 名与值同行 |
| report | id、task_id、version、carrier、verdict、layers、limitations、evidence、metric_set_version、threshold_version | 只增不改；两个版本号用于历史报告按当时口径解释 |
| template | id、bank_code、version、status、field_map | 只增不改 |
| rule | id、rule_code、version、category、expr、threshold | 只增不改 |
| audit_log | id、actor_id、action、object_type、object_id、created_at | 只追加 |

# 状态机

| 当前 | 事件 | 下一 |
| --- | --- | --- |
| PENDING | 合规通过 | CHECKING |
| CHECKING | 解析投递 | PARSING |
| PARSING | 自检通过 | VERIFYING |
| PARSING | 缺页缺月 | NEED_SUPPLEMENT |
| NEED_SUPPLEMENT | 补传成功 | PARSING |
| VERIFYING | 三态合成 | REPORTING |
| REPORTING | 报告生成 | DONE |
| 任一 | 异常 | FAILED |
| FAILED | 重跑 | PENDING |

# 变更流程

1. 任何接口或字段变更：先改本文件，由 PM/PD 落笔。
2. 变更记录追加到「变更日志」，写明日期、内容、影响部分。
3. 契约变更后，对应部分的 tasks.md 由 Agent 自动追加「同步契约」条目。

# 标注外推（v2 新增）

银行侧不必标完所有字段：**只标 1-3 处**（表头词或样例单元格）即可，系统外推整张表。

| 规则 | 说明 |
| --- | --- |
| 最小标注 | 只要 amount + balance + txn_date 三处即可跑通（实测工行 8 页 191 笔） |
| 外推方式 | 以标注为种子做列聚类 → 按表头文字映射（不用列序号，避免表头混入数字） |
| 未标字段 | 按统计特征推断：日期格式→交易日期、含符号数值→金额、最右数值→余额、短文本→摘要 |
| 结果透明 | 每个字段返回来源（labeled / inferred）与置信度，低置信需人工确认 |
| 不成功时 | 返回 warnings（如未推断出必需字段），不静默生成坏模板 |
| 接口 | POST /api/v1/templates/infer（multipart：file、marks，可选 bank_code/password/save_draft） |

# 实现进度（v2 · 2026-10-30）

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| POST /tasks 受理 | **已实现** | multipart，file 必填；加密件返回 E_ENCRYPT |
| GET /tasks、/tasks/{id} | **已实现** | 列表与状态 |
| GET /tasks/{id}/transactions、/metrics | **已实现** | 明细与 40 项指标 |
| GET /reports/{task_id} | **已实现** | 13 字段报告 |
| /templates 增查与启用 | **已实现** | 同银行只保留一个启用版本 |
| 其余 7 个接口 | 未实现 | 模板 dry-run、阈值配置、补件、导出、登录与权限 |
| 11 张表 | **已实现** | 启动自动建表 |
| 登录与权限 | 未实现 | v3 必补，当前接口无鉴权 |

# 变更日志

| 日期 | 内容 | 影响 |
| --- | --- | --- |
| 2026-10-26 | 初版：十二接口、十错误码、十一张表、报告结构 | 全部 |
| 2026-10-26 | 报告改为单份仅银行侧；移除 audience | 后端、前端、算法 |
| 2026-10-26 | 增加三类载体：electronic / image / screenshot；新增两条图片错误码；报告加 carrier 与 limitations | 全部 |
| 2026-10-26 | 结论改为按阈值判定：报告加 conclusions、threshold_version；指标集加 metric_set_version；新增阈值配置接口 | 后端、算法、前端 |
| 2026-10-29 | txn 增 coord_x、coord_y、confidence、drop_reason；report 增 metric_set_version、threshold_version | 数据、后端、算法 |
| 2026-10-29 | 删除 appeal 表（异议申诉功能已从需求移除），表数十一改十 | 数据、后端、产品设计 |
| 2026-10-29 | 新增 task_file 关联表承载补件多文件（表数十改十一）；报告结构加 materials；补件不新建任务 | 数据、后端、算法、前端 |
| 2026-10-30 | 新增「特殊情况：压缩包与口令」：zip 不在受理格式内、口令最多 3 次、口令不落库不落日志、代解需标注与审计 | 后端、前端、数据 |
| 2026-10-30 | 新增标注外推：只标 1-3 处即可生成模板，字段带来源与置信度 | 算法、后端、前端 |
| 2026-10-30 | v2 实现进度：受理/任务/报告/模板接口与 11 张表落地；必填清单确立为「只有流水文件必填」 | 全部 |
| 2026-10-30 | 指标口径 v2：月均/月供分母改为实际覆盖自然月（不足 1 月按 1 月并注明）；收入方向缺失时 A01/A02 给 null 而非 0；口径说明并入报告受限 | 算法、后端、前端 |
| 接口 | GET /api/v1/metric-definitions（返回 40 项指标的 code/name/unit/group/formula/inputs/viz 与 metric_set_version） |
| 2026-10-30 | 新增指标定义接口：银行侧逐条查看计算公式、输入与可视化类型；定义源在 algorithm/algo/metric_defs.py | 算法、后端、银行侧 |
| 2026-10-30 | 报告 layers 每层新增 checks[]（code/name/status/detail），新增 self_check[] 七项自检结果；附 GET /api/v1/verification-definitions 返回 36 个检查点的检验方法 | 算法、后端、银行侧 |
| 2026-10-30 | 新增预读取：受理阶段先全文预读，非流水返回 422 E_NOT_STATEMENT（附 preread 明细）；预读结果写入 task.check_result.preread；自检新增 S8 预读一致性 | 算法、后端、两端 |
| 2026-10-30 | 新增 POST /api/v1/tasks/{id}/reanalyze：用原文件重跑，生成新版本报告（补齐逐项 checks）；加密件需再给口令；旧版本保留 | 后端、银行侧 |
| 2026-10-30 | GET /tasks 改为解析结果汇总：每条含 bank/period/verdict/authenticity/parse/risk/materials/report_version，支持 authenticity、risk、parse、bank、date_from、date_to、q 筛选；返回 items/total/facets | 后端、银行侧 |
| 2026-10-30 | 银行侧拆为两个页面：/ 解析结果列表（多维筛选）与 /report/:id 报告详情；前端改用 HashRouter 兼容静态托管 | 银行侧 |
| 2026-10-30 | 新增 GET /entities（账户/户名/冲突）、GET /entities/methods（7 种合并方式与 3 种重叠算法）、GET /entities/merge?subject=&method=&overlap=（合并结果含口径说明与不支持项） | 后端、银行侧 |
