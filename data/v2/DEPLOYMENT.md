# V2真实部署待批准范围

最新状态：上述新库、合成业务读写和app仅INSERT审计例外已获用户明确批准。当前执行入口为bootstrap/08_core_schema.ps1 -Mode Deploy -Apply；仅在本机隐藏输入root和rc_demo_app密码，确认DEPLOY V2 DEMO 3307后连续执行，密码不上报。尚未取得v2-live真实回执，不能声明已部署。

执行入口在确认新库不存在后才写入；成功后用实际ASGI接口上传一份纯合成PDF，调用团队解析/计算/报告代码，读取持久化结果并核验脱敏。仅对本次三笔合成交易导出小样本，恢复到会话临时表后比对，不创建第12张永久业务表；这不是完整灾备演练。合成PDF保留在data/inputs/demo_v2_uploads，便于材料关联和重算；不提交PDF。

现有可核实成果：DA-01三库/六身份真实通过；本轮复用V2后端模型编译出schema.sql并核对11表89契约关键字段。模型额外实现列保留，不新造业务字段。没有新版数据库读写或端到端真实通过结果。

## 已实现的接入点

- models.load_backend_models只导入后端模型，不导入会自动连接3306的db/session.py。
- models.build_ddl生成同模型DDL，task_file补足契约要求的(task_id,file_id)唯一约束和材料角色约束。保留必要task_id/日期、指标代码索引。
- txn遵循契约按月分区，主键包含txn_date；因此不创建MySQL禁止的txn物理外键，task/account引用由业务存储校验。其他同库外键保留。txn_date须有有效日期，缺日期不能直接入库；不补造日期。
- session.install_privacy绑定SQLAlchemy会话before_flush，处理后端实际新增/修改的ORM对象；完整payload也经过隐私检查，审计detail只保留事件类型，不保存异常原文。此功能已经用真实SQLAlchemy事件验证，但尚未在运行中的网站启用。
- migration.upgrade仅作用于新rc_demo_v2，版本/3307/datadir检查后，目标库已存在就停止。降级目前只生成逆向审核清单，不执行删除。

## 为什么需要追加授权

此前批准仅在现有三个rc_demo库执行旧版0001。新版已删appeal、增task_file，且后端使用单库模型；继续将旧DDL套入会产生错误。建议在同一独立MySQL8.4实例新建rc_demo_v2，保留原三库及账号，复用V2后端单库查询而不改写整个后端。

需要批准：新建rc_demo_v2及11张V2表/必要索引分区约束；只写入可辨识的合成流水，运行一次上传到报告的端到端测试；为已有运行角色增加仅此库所需对象权限（单独列清单核对，禁止全局权限）。不改MySQL80、不改现有三库数据、不重新Initialize、不删对象。新库已有任何对象时停止，不强行迁移。

后端的现有上传流程同时写业务与审计，不能不经审阅直接给它root或全局权限。实际角色权限和一次安全密码输入入口在追加范围批准后统一接入现有安全管道，不要求聊天提供密码。

若保持现有后端单会话流程，拟申请rc_role_app仅在新库对file_obj/task/task_file/bank_account/txn/metric_value/report授予SELECT、INSERT，task额外UPDATE，template/rule仅SELECT，audit_log仅INSERT，staff_user无权限。没有DELETE、DDL或GRANT OPTION；不允许修改报告/指标旧版本。app写审计是对原三角色职责的明确例外，必须一并批准，不自行执行；若不批准，交由后端负责人接独立审计写入账号，不为此重写业务流程。

当前没有启动V2后端、创建新数据库、执行合成DML或宣称报告全流程已跑通。旧08 Apply继续停用。原件清理、外部API、印章和生产级优化均不在当前工作范围。
