# PR 审阅与合并流程（内化版）

仓库：`SYNACK200/risk_control_project1`。适用于任何外部提交的 PR。

## 步骤

| # | 动作 | 命令/判断 |
| --- | --- | --- |
| 1 | 列 PR | `curl -s https://api.github.com/repos/SYNACK200/risk_control_project1/pulls?state=open` |
| 2 | 取下来 | `git fetch origin refs/pull/<N>/head:pr-<N>` |
| 3 | 看范围 | `git diff --stat origin/dev...pr-<N>`；只加 `data/**`、文档 → 低风险；触及 `backend/frontend/algorithm` → 逐文件读 diff |
| 4 | 预判冲突 | `git merge-tree <base> origin/dev pr-<N>` |
| 5 | 试合并 | `git checkout -B feat/pr<N>-review origin/dev && git merge pr-<N>` |
| 6 | 解冲突 | 文档类取 PR 侧；业务代码逐段手解；解完 `git add` |
| 7 | 跑测试 | `cd algorithm && python -m pytest tests -q`；`cd backend && MYSQL_PASSWORD=… MYSQL_DB=risk_control python -m pytest tests -q`；`npm --prefix frontend run build`；`cd frontend-admin && node build-bank.mjs` |
| 8 | 合 dev | `git checkout dev && git pull && git merge --no-ff feat/pr<N>-review && git push` |
| 9 | 合 main | `git checkout main && git pull && git merge --no-ff dev && git push` |
| 10 | 发布 | `git tag -a vX.Y.0 -m … && git push origin vX.Y.0` |
| 11 | 清理 | 删本地 `feat/pr<N>-review` 与 `pr-<N>`；删远端 PR 源分支 |
| 12 | 汇报 | PR 号、范围、冲突处理、测试结果、tag、遗留分支 |

## 纪律

1. 永远 dev 先行，不直接合 main。
2. 测试必须在**解完冲突之后**跑，不能只跑合并前。
3. 业务代码 PR 若没有测试覆盖，先补最小测试再合。
4. 合完在 `contract.md` 记一行变更，任务书勾掉对应编号。

