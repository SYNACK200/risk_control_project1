# 数据模块运维与后端交接（Demo，未运行验收）

## 边界与身份

报告仅供银行侧。数据模块不实现状态机、阈值或授信判断，不向借款人提供指标或结论。冻结核心为十一表、82字段；Alembic版本表是工具元数据，不计业务表。敏感字段存储时已脱敏；视图展示脱敏不能替代入库清洗。JSON/自由文本禁止直接保存原始OCR、真实姓名/卡号，后端入库清洗尚待联调。

MySQL80不得停止、重配或升级。只使用新8.4、3307、独立data；新服务账号为专用虚拟账号。实例管理员负责部署、账号和备份授权，不交后端；迁移身份负责指定三库DDL/视图和角色的对象级授权，不给全局SUPER/FILE；运行身份只有app、reader、audit_writer角色。app不能修改报告/指标/模板/规则，不接触审计；reader只读脱敏视图；审计writer只INSERT。视图DEFINER为执行0002的迁移身份，该身份须稳定保留且有底表SELECT，禁止迁移后直接删除。当前不会自动创建迁移账号或撤销管理员权限，须部署后单独核验。

## 执行顺序及失败条件

1. DA-01真实回执五项全部通过，三账号登录成功。不要重复部署、Initialize或注册服务；MySQL80不动。
2. 独立Python3.12.4和认证依赖已可用，全局Anaconda3.7不能作为运行环境；Alembic/SQLAlchemy尚未安装，安装等待明确批准。以下`$py`指独立venv完整路径；迁移env已改为安全连接注入，不再接受直接getpass或CLI。
3. 下一入口为bootstrap/08_core_schema.ps1，默认Plan只读，Apply必须另行批准、-Apply和审核DDL哈希，并本机输入确认短语。真实写入范围与失败恢复详见core/model_review.md。
4. 管理员单独配置最小迁移身份并人工确认授权范围，审核两版迁移与角色授权。维护窗口内禁止并行改DDL和账号。部署新环境的升级本身就是写库操作，须授权。

```powershell
# 只读盘点；真实Apply命令仅在core/model_review.md范围获批后使用。
pwsh -NoProfile -File data/bootstrap/08_core_schema.ps1 -PythonExe $py -Mode Plan
# 建表后的只读验证复用同一入口，不再直接getpass。
pwsh -NoProfile -File data/bootstrap/08_core_schema.ps1 -PythonExe $py -Mode Verify
```

0001建核心表，0002建视图及角色权限；本批只允许0001。MySQL DDL不保证事务回滚，失败先核对revision与实际对象，禁止直接重跑或手工删对象。当前env拒绝head/0002/直接CLI，08不提供down；真实下行须另批受控入口，加载150万笔后不得执行drop表降级。

```powershell
# 暂无正式批准的降级入口；禁止照旧直接运行alembic downgrade。
# 空表计数、真实对象基线及恢复范围全部审阅后，再单独批准并实现。
```

5. 逐库SHOW TABLES并筛选BASE TABLE核心对象（8业务+2报告+1审计）；版本表另列。SHOW CREATE TABLE rc_demo_biz.txn核对分区和CHECK。p_before/p_future是Demo兜底分区；历史/未来月份须按真实范围演练分区拆分及维护，尚未达到长期月分区运维验收。
6. 以reader登录：SELECT脱敏视图；SELECT底表须报1142；对底表执行INSERT ... SELECT ... WHERE 0须被拒绝；审计writer的SELECT/UPDATE/DELETE须拒绝；app对四类结论表UPDATE/DELETE须拒绝。使用零行语句防止测试误写，仍需独立许可并保留授权结果。不能把“不可更新视图”报错当作底表权限已收敛。

   可执行命令：`& $py -B data/tools/verify_permissions.py --user '<对应运行账号>' --role reader --confirm-zero-row-dml`；分别换成app、audit_writer及各自账号。只接受1142/1143权限拒绝，其他SQL错误不能冒充通过；不读取客户行。仍须管理员另查SHOW GRANTS及角色继承、全局/DDL权限，操作断言不是完整权限审计。
7. 空核心库及独立加载授权下执行 `& $py -B data/tools/load_demo.py --user '<模拟数据加载账号>' --apply`。它再次核对8.4/3307/datadir和十一表空状态，要求输入精确短语，流式批量生成500任务/150万交易，整批失败回滚DML，不覆盖或清空任何表。DONE/in/out等为技术模拟标签，不是新增业务规则；不生成真实报告结论。迁移/加载/压测期间禁止并发写入。
8. `& $py -B data/tools/benchmark.py --user '<只读性能验收账号>' --iterations 100`：须至少150万行，四条查询均非空；记录EXPLAIN选中索引、每条P99，目标<=300ms。reader角色无底表权限；性能账号由管理员临时精确授予四条路径所需SELECT，验收后回收，不能给reader放宽权限。当前未压测，不预报性能达标。

## 备份、独立审计备份与恢复

`tools/logical_backup.py` 使用交互凭据，固定目标核验后以一致性只读事务导出。DDL变更窗口不得与备份并行。输出必须在仓库外受保护C:\ProgramData\RiskControlDemoAclBackup树中新子目录；不得混入现有ACL备份，已存在目录直接拒绝。输出ACL继承保护须由维护用户确认。部分输出没有complete标志时不可恢复。

```powershell
& $py -B data/tools/logical_backup.py full --user '<备份账号>' --folder 'C:\ProgramData\RiskControlDemoAclBackup\db-full-独立编号'
& $py -B data/tools/logical_backup.py audit --user '<独立审计备份账号>' --folder 'C:\ProgramData\RiskControlDemoAclBackup\db-audit-独立编号'
# 创建全新恢复库是写入，须单独授权；现有rc_restore_*任一库存在即拒绝。
& $py -B data/tools/logical_backup.py restore --user '<恢复管理员>' --folder 'C:\ProgramData\RiskControlDemoAclBackup\db-full-独立编号'
```

全量/审计包含流式JSONL、表字段映射、行数和SHA256，Decimal和日期/二进制显式编码。恢复先校验文件和字段，再精确确认CREATE FRESH RESTORE SCHEMAS，仅创建rc_restore_biz/report/audit；只执行仓库内审阅过的DDL，不执行备份携带的SQL。恢复后逐表有序行流SHA256及行数比对，原库不改；不自动删除临时库。权限/视图/用户、原件对象、Alembic元数据不在逻辑表备份内，恢复后须按独立部署流程复建，不能声称是实例级灾备。

备份格式现为2：记录完整full/audit范围与审阅DDL的SHA256；恢复前扫描全部行，检查字段/类型/敏感字段掩码/有序唯一键/行数/哈希，缺表或坏源在CREATE DATABASE前拒绝。格式1草案不兼容，保留旧文件，不自动转换。可无数据库验证：`& $py -B data/tools/logical_backup.py verify --folder '<备份目录>'`。

现有逻辑行增量已完成离线模拟：从两个独立一致性快照流式生成新增/更新/删除差异，绑定基线manifest SHA256、目标manifest及逐文件哈希。只追加表出现更新/删除即拒绝；不能把表文件简单差分称为日志级增量。生成后重建到新目录并逐表比对目标行数与SHA256，两级链已测试；原快照、原数据库不修改，已有输出目录拒绝覆盖。

```powershell
# 只读输入文件；写全新、事先保护的输出目录，不连接数据库。
& $py -B data/tools/logical_incremental.py create --base '<完整基线快照>' --input '<后续完整快照>' --output '<新逻辑增量目录>'
& $py -B data/tools/logical_incremental.py materialize --base '<完整基线快照>' --input '<逻辑增量目录>' --output '<新重建快照目录>'
& $py -B data/tools/logical_backup.py verify --folder '<新重建快照目录>'
# 真实恢复须重新获得授权，再对重建快照执行restore。
```

此实现每次仍需全量扫描快照，不是binlog/PITR，不保证任意时间点恢复，也未通过真实MySQL链路验收。日志级增量还需新实例ROW binlog、归档、坐标/GTID衔接及真实回放演练；不修改MySQL80日志配置。

## 后端接入

`data/integration.py` 的make_engine接收调用方安全提供的用户名/密码，不从仓库读取密码，导入不连接。使用SQLAlchemy2/PyMySQL、127.0.0.1:3307、pool_size5/max_overflow0、timeout10秒、recycle1800秒、pre_ping、参数日志隐藏；批量上限1000。这些是Demo技术初值，非生产容量结论。

调用方通过transaction(engine)取得上下文连接，先验证服务版本/端口/datadir和时区；退出自动提交/回滚并归还连接。insert_batches接受审阅过的SQLAlchemy insert和已脱敏记录，不接受外部SQL字符串；结束时调用engine.dispose()。三个运行身份使用不同engine，不共享管理员连接。后端需自行保证银行授权、幂等范围、引用一致性和版本绑定；不能把文件sha唯一等同跨用户任务复用。

批次拆分单元测试已验证；真实连接池异常归还、超时、并发峰值、批量失败回滚及无泄漏需要后端负责人配合。未修改backend/。OCR服务只能调行内，不能本地另搭或发公网。

新增validation.py可经validated_records(table, records)接入批量流；模拟加载器已使用它校验交易。检查已知字段、金额精度/边界、显式UTC+8、敏感字段掩码、JSON与整数类型，不实现状态机或指标。自由文本/JSON标识符扫描仅启发式，不能保证发现所有姓名或PII；正式清洗仍需联调。identity_digest要求调用方通过批准的密钥提供者传入至少32字节键，代码不存密钥，测试材料不用于部署；没有新增身份证/手机号列。

## 分区及影像验收补充

`& $py -B data/tools/partition_plan.py --through 2027-02`离线输出未来月份正向/逆向REORGANIZE计划；加`--live-user '<只读账号>'`才读取真实分区。工具永不执行DDL，拒绝不连续/改名/未知布局、重复月份及超过120个月的单次计划。实际执行须另行批准、再核对布局及计数；逆操作合并回p_future而非DROP PARTITION，仍有锁和I/O成本。历史p_before拆分尚未实现。

影像负责人提供`producer_version`及`predictions`数组，每项包含file、sha256、carrier后，运行`& $py -B data/tools/evaluate_carrier.py --predictions '<结果JSON>'`。要求九张全覆盖、无重复且内容hash一致。拍照/扫描样式的公共carrier均为image，截图为screenshot，不增加photo/scan公共枚举；不以预设样本标签代替真实分类结果。评估器单测不代表分类器已经通过。

利率/OCR独立模拟原型详见extensions/README.md，仅测试准备，不是批准的扩展存储接口或正式表。

## 未裁决业务及冻结冲突

见extensions/proposal.json及chat.md：利率/计息规则与OCR独立扩展须PM批准；逻辑删除/剔除原因、坐标与报告阈值/指标集历史版本缺少核心持久字段；姓名可见口径冲突；不能通过自行新增核心列解决。PR#3业务字典保留原分支历史，本分支physical_dictionary仅为技术补充。
