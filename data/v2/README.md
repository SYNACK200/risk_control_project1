# v2 数据侧交接

依据团队dev提交e9baadf的contract.md及《数据隐私与外部调用方案》。本地旧分支及历史实现未覆盖；contract_source.md为该提交的原文快照，contract.json为11表89个关键字段清单，原件不是新公共契约。

本轮范围只有DA-25数据隐私与DA-24留存干跑。数据交接接口为integration.validated_v2_records(table, records)：先统一脱敏，再核对新版契约字段、金额精度和补件角色/顺序。只处理关键字段；backend模型额外的created_at/payload等列不能直接混入此接口，须由后端在交接时映射。

- privacy.py：账号前四后四、姓名/对手方留首字；已脱敏字段可重复处理；金额及哈希不作为身份号码误脱敏。
- 口令、Token、整页文本、OCR原文、原件二进制不允许进入交接记录，JSON字符串先解析再检查，不记录被拒绝的值。
- audit_metadata只接收事件、对象编号、结果，不提供自由文本或口令参数；后端须接入真实审计落库，数据侧未修改后端。
- retention_preview只接收对象编号/类型/时间及调用方明确提供的留存天数，输出待归档复核清单；不读取原件、不连接数据库、不删除文件/数据，审计保留。生产留存时长待业务确认。

新版字段：删除appeal，增加task_file；txn增加coord_x/coord_y/confidence/drop_reason，report增加metric_set_version/threshold_version。没有执行ALTER/DROP/CREATE，没有用旧82字段脚本改新版数据库；08旧Apply已暂停。

未解决的实际交接差异：v2后端默认risk_control单库/3306并有外键；本地已验收为rc_demo三库/3307，旧txn有分区且不能搭配InnoDB外键。新版库迁移需后端与数据统一目标后另批执行。本轮不触碰MySQL80，不启动backend/db/session.py（导入即可能自动建库）。

现有validated_records保留旧模型调用方式，并增加入库前自动脱敏；单独validate_record仍要求已脱敏输入。自由文本中的任意姓名识别不在本轮功能内，不能将标识符替换等同完整敏感信息识别。业务金额和指标口径不变，也没有实现新的外部API通道。

验证：python -B data/tools/test_v2_privacy.py；python -B data/tools/test_validation.py；python -B data/tools/test_integration.py。全部使用合成数据，不等同真实库无明文或全链路合规验收。
