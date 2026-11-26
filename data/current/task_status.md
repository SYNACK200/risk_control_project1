# 新版数据任务对应与执行说明

2026-11-26：已确认本机 MySQL 8.4.13/3307。真实首轮回执 current-local-20261126_1e9d64f2.json：16表建成、单字段回滚与样本恢复通过，交易查询未选索引；性能总体未通过。新脚本已扩展到100任务/19100笔交易、16表均含合成行、加密文件恢复，待用户本机输入密码重跑。旧 Demo PASS 不沿用。

| 任务 | 本次交付 | 尚缺验收 |
| --- | --- | --- |
| DA-20 独立建表/迁移 | schema.sql；current_migration.py 生成增量 up/down 评审计划；未知表、删字段、类型/可空变化、需回填列直接阻断 | 实际 MySQL 空库建表；既有库结构采集、索引/约束核对、真实升降级 |
| DA-22 索引/性能 | index_review.sql 三组复合索引建议；current_benchmark.py 三条当前查询、实际 EXPLAIN key、至少100轮、P99<50ms | 确认合成测试库，191笔以上工作量的真实 EXPLAIN 与性能证据；不能直接改已联调结构 |
| DA-23 印章设计 | seal_design.md：结果/模板分离、版本追溯、坐标与引用、生命周期和迁移验收条件 | 产品与算法评审，契约字段/接口确认，随后正式迁移；当前不新增猜测表 |
| DA-24 留存 | retention_preview.py 独立命令；按类型明确期限、只输出元数据候选、审计保留 | 生产期限确认、实际对象引用和法律保留核对，不提供直接删除功能 |
| DA-25 脱敏 | 既有 privacy.py 与 v2隐私回归8项通过 | 当前账号/OCR配置等新增表与后端真实落库的专项适配；旧通用钩子不能直接套用，不宣称新库无明文 |
| DA-26 备份恢复 | 既有快照校验回归11项通过 | current_backup.py 已实现全16表 Fernet 认证加密文件、精确 Decimal/日期类型恢复、错误密钥/篡改/非空目标拒绝，5项离线测试通过；新脚本真实加密恢复待重跑。仅数据快照，不含对象存储、binlog/PITR |

## 命令

Python 3.12 环境需安装 data/requirements.txt。当前会话使用项目 tmp/data-schema-deps 的 SQLAlchemy 2，临时依赖不提交。

```powershell
python -B data/tools/current_schema.py --check
python -B data/tools/test_current_schema.py
python -B data/tools/test_current_operations.py
python -B data/tools/test_v2_privacy.py
python -B data/tools/test_snapshots.py
```

迁移规划（输入必须是同格式的已审查旧结构快照；不能将旧 v2/contract.json 作为真实结构）：

```powershell
python data/tools/current_migration.py --from-snapshot 旧结构快照.json --output 迁移计划.json
```

计划输出不执行 SQL。当前快照没有外键/索引的完整版本比对能力，故计划仅供人工评审，执行前还需 SHOW CREATE TABLE/SHOW INDEX。down 会丢新增数据，MySQL DDL 不支持事务式整体回滚，先备份再演练。

留存干跑：输入为 `[{"kind":"file","id":1,"created_at":"2020-01-01T00:00:00+08:00"}]`，策略为 `{"file":30}`；30仅是调用示例，不是生产保留期限。

```powershell
python data/tools/retention_preview.py --input 元数据.json --policy 期限.json --now 2026-11-26T12:00:00+08:00
```

性能命令需显式设置 MYSQL_HOST/PORT/USER/PASSWORD/DB；使用只读账号与合成任务，不把密码写进命令行或提交文件：

```powershell
python data/tools/current_benchmark.py --task-id 你的合成任务编号 --iterations 100
```

下一步：本机终端运行 local_acceptance.py 重验（密码 getpass 输入，不回传聊天）。新建带随机后缀的独立合成库，旧库不修改。脚本生成回执并保留测试库，不自动清理。生产迁移、完整灾备与印章契约评审仍单独验收。

## 第二轮真实验收

回执：`data/evidence/current-local-20261126_5f0cf915.json`，complete=true。MySQL8.4/3307独立合成库16表均有数据（100任务、19100笔交易）；认证加密文件恢复后全表内容相同；三条查询各100轮均选索引，P99为1.829/0.805/0.7482ms。仅验证本机合成工作量及单字段回滚，不代表生产迁移、150万笔旧任务、业务接口或完整灾备验收。首轮失败回执保留。
