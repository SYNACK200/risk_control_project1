# 当前团队版本的数据交付

本目录对应当前仓库的 `backend/db/models.py`，共 16 表、153 字段。业务契约与实际模型应分别核对；新增的配置、用户等实现表不意味着擅自修改公共契约。历史 `data/v2/` 保留为旧 Demo，不能用于当前版本建库。

## 独立建表

使用 Python 3.12，依赖 `data/requirements.txt` 中的 SQLAlchemy 2。生成工具只导入模型，不导入数据库会话、不连接数据库。

```powershell
python data/tools/current_schema.py --check
python data/tools/test_current_schema.py
```

`schema.sql` 是空库初始化脚本：先由运维指定一个空数据库，再使用 MySQL 客户端执行 `source`，例如客户端内执行 `source D:/项目目录/data/current/schema.sql`，路径替换为实际绝对路径。执行前核对数据库目标及空库状态；脚本不含建库、切库和删除命令，重复执行会报已存在，不能用于升级已有库。

`schema.json` 与 `data_dictionary.md` 是字段类型、可空性的机器快照和人工字典。后端模型变更后运行 `python data/tools/current_schema.py --write`，审查生成差异并重新验证。

## 新需求对应

- 补件按任务内 seq 唯一；同一文件允许用不同 seq 追加，不增加 task_id/file_id 唯一约束。
- 日期缺失和指标缺失允许 NULL；不把缺失收入指标变成零，不强制交易日期非空。
- 保留 txn.extra、task.field_map_override、report.verification，以及报告历史版本相关字段。
- 保留 task/template.deleted_at、task.user_id、QUEUED 字符串状态及当前模型已有索引。
- 建表直接遵循后端外键及主键，不套用旧 Demo 分区；分区与 InnoDB 外键的冲突仍需专项设计。
- 用户密码哈希与 OCR 服务配置是新增实现表的专用字段，不能直接接入旧 v2 的通用隐私 flush 钩子。当前工具只生成结构，不写入或导出凭据值。

## 验证边界

离线验证覆盖模型与交付物一致、补件重复文件、缺失值、自定义 JSON、软删除、QUEUED 以及报告多版本的存储能力。SQLite 内存测试不证明 MySQL 运行性能或接口行为通过。现有库的 ALTER/up/down 迁移须先采集真实结构并核对历史数据；本次不执行数据库变更，也不把旧库验收记录算作新版本验收。DA-22 性能、DA-23 印章扩展、生产清理周期与备份恢复演练继续保留待验收状态。

## 当前运行状态

已在本机MySQL8.4/3307完成16表建表与首轮样本恢复，原始失败回执保留于evidence/current-local-20261126_1e9d64f2.json。交易查询未使用索引，故不标全通过。local_acceptance.py现已增加100任务、19100笔交易及全表非空合成行，使用current_backup.py认证加密文件恢复；新版本待交互密码重跑。详细任务边界见task_status.md。

## 第二轮真实验收

回执：`data/evidence/current-local-20261126_5f0cf915.json`，complete=true。MySQL8.4/3307独立合成库16表均有数据（100任务、19100笔交易）；认证加密文件恢复后全表内容相同；三条查询各100轮均选索引，P99为1.829/0.805/0.7482ms。仅验证本机合成工作量及单字段回滚，不代表生产迁移、150万笔旧任务、业务接口或完整灾备验收。首轮失败回执保留。
