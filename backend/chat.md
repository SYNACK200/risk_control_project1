> 这是什么：与 AI 的自然语言需求入口 · 谁写：人（需求）+ AI（回收与精炼）

## 当前目标
本轮已完成 BE-20a、BE-33、BE-21、BE-02，并实现 BE-32 的安全入库与状态转换；下一步在 PM/PD 裁决 P0 契约冲突后继续 BE-09 队列完成补件重跑与报告导出。

## 当前阻塞
BE-31 的 `/templates/dry-run` 未写入 `contract.md`；BE-39 要新增已冻结的报告字段且任务书要求修改算法目录，均需 PM/PD 裁决后再实施。

## 最近裁决
本轮先按既有契约实施 BE-20a、BE-33、BE-32；认证沿用 `Authorization: Bearer`，口令仅来自环境变量。

## 待处理需求

- [ ] BE-31：`/templates/dry-run` 未写入 `contract.md`；需 PM/PD 确认路径、请求/响应结构后实施。
- [ ] BE-39：新增 `authenticity_summary` 会修改冻结的报告结构且任务书指定算法目录；需 PM/PD 解冻并指派归属。
- [ ] BE-32 收尾：随 BE-09 实现多材料队列编排；重跑必须同时使用 original + supplement 并更新报告 materials，不能覆盖原材料。

## 已处理

（已回收至 history/20261030-02.md）
