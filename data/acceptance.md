# DA-01—DA-19 验收矩阵

## 2026-10-31 最新状态（优先于以下历史准备记录）

- V2真实验收已通过：11表/89契约关键字段、合成PDF接口上传/解析/3笔入库/40指标/报告读取、存储脱敏、限定授权和交易备份样本恢复比对。证据：evidence/v2-live-77892ffba9c14d1599fe936ba8302aa6.json。
- V2前端TypeScript与Vite生产构建通过；真实Edge上传首页、授权勾选门禁、错误格式拒绝通过。证据：evidence/20261031-web-smoke.json、20261031-upload-smoke.png。
- 真实Edge网页上传合成PDF至处理完成已通过（task_id=2），读取3笔交易、40项指标及报告API通过。证据：evidence/20261031-web-pipeline.json、20261031-progress.png。银行侧报告页面不在当前V2前端路由内，报告API通过不能代表银行报告UI已交付。
- 四条Demo查询真实EXPLAIN均选中索引：PRIMARY、ix_txn_task_id、ix_metric_task_code、ix_report_task_id；分区存在及存储脱敏通过。证据：evidence/v2-readonly-ecf90ce243af4036a850346f14b597c7.json。小样本索引结果不等于性能验收，也不替代旧四查询定义。
- DA-03边界/裁剪、DA-07完整升降级、DA-08/09/10完整备份恢复、DA-12压测、DA-14只读视图和DA-16连接池仍未完成真实验收。此次不追加授权或为了完成度修改数据库。
- 新入口bootstrap/09_web_demo.ps1只验证已有库或启动既有后端，不重新执行Deploy，不创建库/表/账号；权限验证不会用试写代替只读核对。

V2最新准备：已复用团队e9baadf后端模型生成v2/schema.sql及v2/data_dictionary.md，覆盖11表89关键字段。真实ORM保存前脱敏接入点和新库迁移门禁已实现、仅离线验证；没有V2真实建表/业务读写/网站端到端证据。原82字段迁移停用。DA-01保留真实完成，新库rc_demo_v2与合成闭环及运行权限须按v2/DEPLOYMENT.md追加批准后再执行，不冒充DA-20/22/25完成。

2026-10-30最新：DA-01真实回执五项全PASS、三账号真实登录已通过。用户已批准仅0001_core上行及独立venv迁移依赖；Alembic1.20.1/SQLAlchemy2.0.55已实际安装，pip check及真实MySQL方言DDL编译通过，未连接数据库。08执行和验收入口已就绪，当前停在本机真实密码输入，不能声明本轮已建表。实际数据库完成状态以本文件最新live verification及core-live回执为准。DA-11/17仍仅保留原离线验收；此前证据为历史快照。

| 任务 | 实现文件及用途 | 已验证 | 尚需执行及依赖 | 状态 |
| --- | --- | --- | --- | --- |
| DA-01 三库三角色 | bootstrap/*；07真实验收回执 | 已读真实回执：结构隔离/元数据/三账号登录全PASS | 无，后续建表不重跑空角色验收 | 已完成真实验收 |
| DA-02 十一表 | core/schema.sql、schema.json、tools/build_core.py；08统一入口 | 11表82字段名称/类型离线零差异，已有/部分对象安全门禁 | 获批准后运行至0001，真实表/字段/引擎/约束验收 | 代码已实现，真实DDL未执行 |
| DA-03 月分区 | txn复合PK和202610—202612分区；partition_plan.py | 3测试验证跨年/闰月、连续未来月维护及保留数据逆操作计划 | SHOW CREATE、边界插入、裁剪/维护真实运行；历史兜底拆分未实现 | 部分实现 |
| DA-04 四索引 | schema.sql、queries.sql、benchmark.py | 四命名索引及查询路径结构检查 | 四EXPLAIN实际选索引，选择性评估 | 代码已实现，运行未验证 |
| DA-05 利率/规则 | extensions/adapters.py模拟版本利率目录；proposal.json | Demo显式启用、版本/有效期/重复区间测试；不计算利息 | PM批准扩展/算法接口，尚无正式利率/计息规则表 | 独立原型已测；正式任务Blocked |
| DA-06 数据字典 | physical_dictionary.md技术补充；PR#3来源137e199 | 物理字典与DDL82字段对比 | PR#3业务字典合并裁决/语义问题，不覆盖原PR历史 | 部分；业务字典仍在独立PR |
| DA-07 up/down | alembic.ini、migrations/*；安全连接注入、仅0001目标 | env/迁移门禁及匿名管道离线测；无getpass，禁止head/已有对象覆盖 | 批准独立venv依赖安装及上行；真实down/up另批，当前入口不提供down | 部分完成，运行未验证 |
| DA-08 全量/增量 | logical_backup.py、snapshot_format.py、logical_incremental.py | 11快照/逻辑增量测试，包含两级重建与坏备份拒绝 | 真实快照导出和链恢复；binlog/PITR未实现，不能等同 | 逻辑增量离线已测；真库未验证 |
| DA-09 审计独立备份 | audit模式与不可变行增量检查 | 审计追加增量成功，修改/删除拒绝的模拟测试 | 独立账号/真实审计导出和checksum比对 | 代码及模拟已测，真库未验证 |
| DA-10 恢复演练 | restore新临时库与完整预校验 | 4个模拟SQL接收端测试：11表恢复、已有库拒绝、坏源零写入、结果损坏失败 | 真实新库恢复/行数+SHA256；模拟连接不是MySQL | 模拟控制流已测，真库未验证 |
| DA-11 500×3000造数 | synthetic.py、audit_synthetic.py、load_demo.py | 实际全量流式核验1500000笔、500任务各3000笔；编号/引用/余额/金额/时区/掩码通过 | 落库COUNT属DA-02/12集成验收，尚未执行 | 已完成原任务离线验收 |
| DA-12 P99 | benchmark.py、test_benchmark.py | 3测试：区分possible_keys与实际key；空数据拒绝、P99越界失败 | 满量数据、四路径100次以上、P99<=300ms、实际索引 | 判定逻辑已测，真实压测未运行 |
| DA-13 字段脱敏 | validation.py、synthetic.py、视图/CHECK | 6校验测试：精度/UTC+8/掩码/JSON标识符/手机/身份键控哈希；原掩码2测试 | SQL CHECK/视图与角色真实验收；文本启发式不是完整清洗 | 部分实现 |
| DA-14 只读视图 | 0002_views、views_grants.sql、verify_permissions.py零行DML验收 | reader无写、只授视图；四类只增不改及审计INSERT静态检查 | reader底表SELECT/INSERT拒绝、审计隔离、角色继承 | 代码已实现，运行未验证 |
| DA-15 运维手册 | operations.md、bootstrap/README.md | 流程/边界人工源码核对，命令未执行 | 陌生维护者按手册真实建库和恢复 | 文档已实现，实操未验证 |
| DA-16 后端连接池/批量 | integration.py、validation.py | 4测试：流式批次、类型/原始SQL拒绝、坏记录/不一致字段拒绝、模拟异常归还 | 真实SQLAlchemy池并发/失败回滚/无泄漏，需要后端 | 部分实现；跨模块依赖 |
| DA-17 字典脚本一致 | check_core.py、test_schema_checker.py、verify_live.py | 11表82字段及物理类型零差异；2测试涵盖3漂移反例；3元数据比较测试 | 真库字段/类型/默认值对照待DA-02；PR#3语义不由此证明 | 已完成原任务离线验收 |
| DA-18 影像字段/OCR | 既有核心字段；extensions/adapters.py追加对象原型 | 文件ID/版本/坐标/置信度/掩码/内容校验、双追加和损坏检测测试 | OCR正式表/MinIO策略/行内服务契约待批，非替代批准 | 独立原型已测；正式任务Blocked |
| DA-19 三类影像样本 | 9PNG；evaluate_carrier.py结果评估器 | PNG解码/尺寸；2评估器测试拒绝错类、缺项、重复、哈希不符 | 真实后端/算法输出及版本证据未取得，不实现他组分类器 | 部分实现，外部分类依赖 |

## 可复核命令

```powershell
python -B data/tools/check_core.py
python -B data/tools/run_checks.py
python -B data/tools/check_static.py
python -B data/tools/test_synthetic.py
python -B data/tools/test_backup_format.py
python -B data/tools/test_integration.py
python -B data/tools/test_migration_guards.py
python -B data/tools/synthetic.py --count-only
python -B data/tools/audit_synthetic.py
pwsh -NoProfile -File data/bootstrap/tests/Test-Preflight.ps1
python -B data/bootstrap/tests/test_auth_dependencies.py
git diff --check
git status --short --untracked-files=all
```

离线验证可用现有Python执行；数据库工具用独立3.11/3.12，不能用Anaconda3.7。SQL结构检查不是MySQL解析器，不宣称语法/迁移执行通过。凭据扫描为模式启发式，不是绝对无敏感信息证明。不得用SQLite替代MySQL验收。运行验收顺序、命令及失败停止条件见operations.md及next_batch.md。

## DA-01 live acceptance 20261030-205612

PASS: three empty schemas, six local identities, exact empty roles/default bindings, authentication plugins and three runtime logins. Evidence: evidence/da01-live-20261030-205612-2a743751dc004d60b7a8b6bbaf7cff1f.json. Read-only; DA-02 table/view privileges are not covered.

## V2 live acceptance 2026-10-31T00:15:11.6280231+08:00

11 V2 tables/89 key fields verified; actual synthetic HTTP upload, parsing, persistence, metrics and report retrieval PASS; storage privacy and minimal grants PASS; synthetic transaction backup sample roundtrip PASS (not full disaster recovery). Evidence: evidence/v2-live-77892ffba9c14d1599fe936ba8302aa6.json.
