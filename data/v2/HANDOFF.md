# V2数据模块集成交付

## 实际通过

MySQL8.4.13，127.0.0.1:3307，rc_demo_v2，11表/89关键字段。真实Edge上传纯合成PDF后处理完成，3笔交易、40项指标和报告API可读。交易存储脱敏，4条Demo查询真实EXPLAIN均走索引。完整验收边界见../acceptance.md最新状态，业务说明见../数据模块业务报告_v2.md。

核心证据：../evidence/v2-live-77892ffba9c14d1599fe936ba8302aa6.json、../evidence/20261031-web-pipeline.json、../evidence/v2-readonly-ecf90ce243af4036a850346f14b597c7.json。

## 后端接入

复用团队dev e9baadf的backend和frontend源码，不在数据分支复制其他模块历史。集成时将V2Root设为包含backend/db/models.py的团队V2仓库绝对路径。本机默认指向独立V2工作副本，仅为本机配置，不是集成机器要求。

在PowerShell7运行（项目根目录；密码只在本机隐藏输入）：

```powershell
& ./data/bootstrap/09_web_demo.ps1 -Mode Verify -V2Root '团队V2仓库绝对路径'
& ./data/bootstrap/09_web_demo.ps1 -Mode Serve -V2Root '团队V2仓库绝对路径'
```

Verify只读，Serve启动127.0.0.1:8000后端；启动时只验证目标，不创建对象。复用团队路由和解析/报告实现，以data/v2/runtime.py注入最小权限会话，并通过session.py保存前脱敏。前端在其frontend目录按原README启动，端口5173代理8000。首次新机器需按bootstrap部署步骤独立授权，不能直接启动旧backend/main.py的默认3306自动建库入口。

已存在rc_demo_v2时禁止重新Deploy -Apply。API服务保持运行需要Python进程内保存运行账号凭据；不落盘或输出，退出清除引用不保证托管字符串物理擦除。仅本机合成演示，不作为互联网部署或正式身份认证方案。

## 未完成边界

银行报告UI尚无现成路由，已验证的是报告API；借款人提交页不显示报告与指标。完整升降级、压力测试、只读视图、完整灾备和影像分类仍未验收，不阻断本次合成PDF主流程演示。core/及migrations/为旧82字段历史实现，V2不执行，当前有效DDL和物理字典为本目录schema.sql、data_dictionary.md。DA-06 PR#3历史不合入或覆盖。
