# DA-02/03/04/07模型复核与待批准执行范围

## 契约覆盖与物理结构

contract.md冻结的11表、82字段保持原名及顺序。check_core.py独立对比契约、DDL、schema.json和物理字典，逐表缺失/额外/重复均为0。

| 表 | 字段数 | 主键 | 主要约束/索引 |
| --- | --- | --- | --- |
| staff_user | 4 | id | 四类角色枚举、姓名脱敏CHECK |
| file_obj | 9 | id | sha256唯一、carrier枚举 |
| task | 13 | id | biz_no唯一、task_type/carrier枚举、ix_task_status |
| bank_account | 8 | id | 账号掩码CHECK |
| txn | 10 | id + txn_date | amount>0、对手姓名脱敏、ix_txn_task_date、月分区 |
| metric_value | 8 | id | ix_metric_task_code |
| report | 8 | id | carrier枚举、ix_report_task_version |
| template | 5 | id | 版本追加约束由运行权限/调用方实现 |
| rule | 6 | id | 同上 |
| appeal | 5 | id | 不实现物理删除业务流程 |
| audit_log | 6 | id | 后续0002仅赋审计写入身份INSERT |

所有表为InnoDB/utf8mb4_0900_ai_ci。金额amount/balance/期初期末余额为DECIMAL(18,2)；value_num为通用指标技术精度DECIMAL(30,8)，不自行定义指标业务口径。时间为DATETIME(6)，通过+08:00会话和入库校验维护UTC+8语义，DATETIME本身不保存时区偏移。未明确业务非空要求的字段保持现有Demo NULL设计，不伪称契约已规定。

没有物理外键：跨库按data/design.md约定逻辑关联；MySQL InnoDB分区表与外键不兼容，txn及指向txn的关联也不添加外键。关系依赖task_id/account_id/file_id/template_id等既有字段及调用方一致性校验，不能声称数据库已杜绝孤儿行。txn复合主键包含分区列，满足MySQL唯一键分区限制；id单列全局唯一性不能由此复合主键保证，txn_id引用必须由ID分配/调用方保证，未新增辅助表或擅定ID业务规则。

版本只增不改、审计只追加不靠新增触发器实现；0002运行身份权限与调用方流程单独验收，本批不给任何运行角色新权限。DA-06 PR#3及业务待裁决问题保持独立。

## 本批准确SQL影响范围（等待人工批准）

固定目标仅127.0.0.1:3307、MySQL8.4、D:/RiskControlDemo/mysql84/data，现有rc_demo_biz/report/audit三个已验收空库。

1. 只读核对DA-01真实回执、服务身份、版本/端口/datadir/当前账号、三库字符集以及BASE TABLE/VIEW/trigger/routine/event清单。
2. 仅三库完全没有对象时，在data/evidence中新建并fsync空对象基线及DDL/JSON/env/0001源码SHA-256；这不是实例级数据备份。账号和角色不变，无业务行需要导出。
3. Alembic首次创建rc_demo_biz.alembic_version工具表，并在成功后写入0001_core修订号；工具表不计正式11表。
4. 执行schema.sql：1条SET SESSION time_zone，加11条CREATE TABLE，顺序staff_user→file_obj→task→bank_account→txn→metric_value→report→template→rule→appeal→audit_log。业务库8表、报告库2表、审计库1表。
5. 11个主键、2个业务唯一索引（sha256、biz_no）、4个路径二级索引及9个CHECK随CREATE TABLE一次创建。txn为RANGE COLUMNS(txn_date)，p_before<2026-10-01、p202610<2026-11-01、p202611<2026-12-01、p202612<2027-01-01、p_future MAXVALUE。
6. 成功后仅SELECT/SHOW/EXPLAIN：逐字段类型/NULL/默认/字符集、主键与全部索引、CHECK启用、无外键、分区元数据、修订号及4条查询实际key。保存core-live脱敏回执。

不执行0002_views、不创建视图/账号/角色、不GRANT/REVOKE、不修改现有表、不写业务行、不DROP/TRUNCATE、不自动降级；MySQL80不在连接目标或脚本范围。空表EXPLAIN不能代替DA-12满量P99，未执行分区边界插入或迁移down演练，不能勾选这些尚未验证部分。

审核DDL的SHA-256（原始字节，含现有换行）为：

```text
9861A8C428C1A77878CF2C2199951660E43A170C841D8CA8DDE77B6FE9FEACE5
```

Apply必须显式-Apply、匹配上述DDL哈希，并在本机输入APPLY CORE 0001 ON DEMO 3307。只读Plan不需要写入开关，也不会创建Alembic版本表。代码/物理字典字段变化必须重新审阅，不绕过哈希门禁。

## 幂等性、并发与失败恢复

- 第一次对象为空才允许升级；若11核心表+工具表完整、版本0001且全部物理元数据匹配，仅验证并返回already_applied，不重复DDL或数据写入。
- 工具表单独存在、部分核心表、未知表/视图/触发器/例程/事件、错误版本均停止；不自动猜测“上次已创建到哪张表”。迁移期间须维护窗口，禁止其他会话同时改DDL或写入。
- MySQL DDL可能部分提交。任何失败保留全部对象、基线和脱敏错误码；先比较实际清单与基线，禁止盲目重跑或自动DROP。
- 当前08入口不提供down，env也拒绝head/0002/直接CLI。0001降级函数已有空表计数及显式授权保护，离线测试通过，但真实down/up须单独审阅并批准受控入口。不能通过直接旧alembic命令绕过。
- 若后续允许撤销，仅能逐项处理本次新建、无外部依赖且COUNT=0的对象；有行立即停止。部分缺表时现有全量down不能直接使用，须生成针对实际完成清单的审阅逆操作。不得删除数据目录或重初始化实例。

## 仍需批准的前提

现有venv尚缺Alembic/SQLAlchemy。联网安装曾被自动审批拒绝且没有执行：需要明确批准仅在D:/RiskControlDemo/python312-venv安装alembic>=1.13,<2和SQLAlchemy>=2.0,<2.1及其依赖，不改Python解释器、Anaconda、PATH或MySQL服务。现有PyMySQL/cryptography保持不变。

批准后由自动工具先完成依赖/API真实离线验证，再让维护人员用08入口一次安全输入密码执行本批。依赖安装、真实建表和空库降级不是同一授权：本次请求仅为依赖+上行到0001，不含降级或0002。
