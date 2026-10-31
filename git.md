> 这是什么：Git 操作规范（Agent 必读 + 零基础照着做） · 谁写：PM/PD · 何时更新：协作方式变化时
> 仓库：https://github.com/SYNACK200/risk_control_project1.git

# 一、仓库怎么组织

| 分支 | 用途 | 谁能改 |
| --- | --- | --- |
| main | 永远是能用的版本，只接受从 dev 合并 | 只有 PM/PD |
| dev | 集成分支，四个部分合到这里 | 只有 PM/PD 合并 |
| feat/角色-内容 | 各人干活的分支 | 本人 |
| integration | 联调专用，四方都合进来跑契约测试 | PM/PD 建，全员可提 PR |

分支命名：

```text
feat/front-upload        前端：上传页
feat/be-task-api         后端：任务接口
feat/algo-file-layer     算法：文件层核验
feat/data-schema         数据：建表脚本
fix/be-retry-500         修 bug
```

名字只写「哪个部分 + 做什么」，不写人名、不写日期。

# 二、给 Agent 的 Git 规矩（硬约束）

## 必须做

| # | 规矩 |
| --- | --- |
| G1 | 开工第一件事：git pull origin dev |
| G2 | 只在自己的 feat 分支改；不在 main、dev 上直接提交 |
| G3 | 提交时机由 PM/PD 定，也可由执行 Agent 自行判断：大改动、关键文档落地、可运行/可部署版本 → 直接提交推送；零碎中间态 → 留在工作区 |
| G4 | 提交前 git status 确认没有多余文件（密钥、真实数据、node_modules） |
| G5 | 推自己的分支：git push origin feat/xxx，再开 PR 到 dev |
| G6 | 每次动手前读 forbidden.md，命中冻结区不动 |

## 禁止做

| # | 禁止 | 为什么 |
| --- | --- | --- |
| N1 | git push --force | 覆盖别人已推送的提交，可能直接丢代码 |
| N2 | 在 main / dev 上直接 commit | 未评审代码绕过联调闸门 |
| N3 | git rebase 别人的分支 | 别人本地会炸 |
| N4 | 一次提交混多个任务 | 出问题无法单独回滚 |
| N5 | 提交 .env、密钥、真实客户数据 | 公开仓库，一提交就泄露 |
| N6 | 改 .git 目录下任何文件 | 会破坏仓库历史 |
| N7 | 用 git reset --hard 解决冲突 | 会丢别人和自己的改动 |

## 遇到冲突怎么办

| 步 | 动作 |
| --- | --- |
| 1 | 停下，不要硬合 |
| 2 | 在 chat.md 写：哪个文件冲突、两边各改了什么 |
| 3 | 等 PM/PD 裁决，或按 contract.md 为准合并 |
| 4 | 合完跑一遍本部分验收命令，再提交 |

## 回滚怎么做

```bash
git revert <commit>        # 推荐：新增反向提交，历史保留
git reset --hard <commit>  # 禁止：会丢掉之后的提交
```

# 三、零基础操作（一条命令一句大白话）

## 第一次：把仓库拿到本地

```bash
git clone https://github.com/SYNACK200/risk_control_project1.git
```

把网上那个仓库整个下载到电脑上，变成一个文件夹。只做一次。

## 每天开工：同步别人的改动

```bash
git pull origin dev
```

把网上最新版本拉下来。**不拉就改，推上去会撞车**（冲突）。

## 开自己的分支（第一次干活前）

```bash
git checkout -b feat/front-upload
```

复制一份当前版本、起个名字，之后改动都在自己这份里，不影响别人。

## 看自己改了什么

```bash
git status     # 哪些文件被改了
git diff       # 具体改了哪几行
```

提交前先看一眼，别把垃圾文件带上。

## 保存一次（提交）

```bash
git add .
git commit -m "task: FE-06 上传页支持拖拽与前置校验"
```

add 是把改动放进篮子，commit 是拍一张快照并附一句说明。

## 传上去（推送）

```bash
git push origin feat/front-upload
```

把快照传到网上，别人才能看到。第一次推若提示设置上游分支，按提示复制那行命令。

## 让别人合你的东西（PR）

打开仓库网页 → Compare & pull request → 目标分支选 dev → 写清改了什么 → 提交，等 PM/PD 合并。

PR 就是「我改好了，请你看一眼要不要」。不合并，别人不会自动拿到你的改动。

## 被拒绝了（push 说 non-fast-forward）

```bash
git pull --rebase origin dev
git push origin feat/front-upload
```

网上有你没有的改动，先拉下来叠好，再推一次。

# 四、四部分的 Git 流程规划

## 总体顺序

```text
PM/PD 建仓库、推骨架（proposal / contract / startup / forbidden / git）
   ↓
四人各自 clone → checkout -b feat/角色-内容
   ↓
每天开工：pull origin dev
   ↓
完成一个任务 → commit（带任务编号）→ push → PR 到 dev
   ↓
PM/PD 评审合并到 dev
   ↓
联调：从 dev 拉 integration，四方各自 PR 进来，跑 contract_test
   ↓
全绿 → PM/PD 合并 dev → main，打 tag v0.x
```

## 合并顺序（按依赖方向，别倒过来）

| 顺序 | 部分 | 理由 |
| --- | --- | --- |
| 1 | 数据 | 表结构是别人干活的前提 |
| 2 | 算法 | 后端要调它的接口 |
| 3 | 后端 | 前端要调它的接口 |
| 4 | 前端 | 最后接，接完就能演示 |

## 各部分的日常节奏

| 部分 | 开工 | 收工 | 特别注意 |
| --- | --- | --- | --- |
| 前端 | pull → 起 5173/5174 看还能不能跑 | commit + push | 别提交 dist/、node_modules/ |
| 后端 | pull → 起服务看能否建表成功 | commit + push | 别提交本地配置与日志 |
| 算法 | pull → 跑样本回归 | commit + push | 样例别放真实客户数据 |
| 数据 | pull → 跑迁移确认可升降 | commit + push | DDL 变更必须带 down |

## 冲突高发区与预防

| 文件 | 为什么容易冲突 | 预防 |
| --- | --- | --- |
| contract.md | 大家都想改接口 | 只有 PM/PD 能改；其他人写 chat 申请 |
| tasks.md | 都在勾自己的 | 只勾自己部分 |
| startup.md | 都要填身份 | 只填自己那份，不并行改 |
| proposal.md | 谁都想加一句 | 只读，改动走 PM/PD |

## 联调阶段的分支用法

| 步 | 谁 | 做什么 |
| --- | --- | --- |
| 1 | PM/PD | 从 dev 建 integration |
| 2 | 四方 | 各自 PR 到 integration |
| 3 | 任一人 | bash algorithm/integration/run_all.sh 起全栈 |
| 4 | 前端 | 跑 contract_test.py，报错按部分回流到 tasks |
| 5 | PM/PD | 全绿后合 dev，打 tag |

# 五、常见错误与解法

| 现象 | 原因 | 解法 |
| --- | --- | --- |
| push 被拒 non-fast-forward | 本地落后于远端 | git pull --rebase origin dev 再推 |
| 冲突提示 <<<<<<< 标记 | 两人改了同一处 | 手工保留正确版本、删掉标记行，git add 后 git rebase --continue |
| 提交里带了大文件 | 误 git add . | git rm --cached 文件，加进 .gitignore 再提交 |
| 提交了密钥 | 没看 git status | 立刻作废该密钥并换新，再 git rm --cached；历史旧值视为已泄露 |
| 改错了想还原 | 未提交 | git checkout -- 文件 |
| 想回到某个旧提交 | 已推送 | git revert 提交号，不要 reset |
| 不知道自己分支从哪来 | — | git log --oneline --graph --all |

# 六、提交信息格式

```text
task: <任务编号> <做了什么>
fix:  <问题> <怎么修的>
docs: <哪份文档> <改了什么>
chore: <杂事> <做了什么>
```

示例：

```text
task: BE-08 上传接口按文件哈希判重
task: AL-07 文件层增加增量更新检测
fix:  上传加密件未返回 E_ENCRYPT
docs: design.md 补充借款人侧禁止展示项
```

一条提交只对应一件事；信息写「做了什么」，不写「改了代码」。

## G4 分支生命周期（2026-10-30 清理后立规）

| 规则 | 说明 |
| --- | --- |
| 一任务一分支 | 命名 `feat/<模块>-<任务号>`；同一任务不要按提交再开分支 |
| 日常小改直接进 dev | 文档、单文件修正、口径微调不必开分支 |
| 合并即删 | 合入 dev 后立即删远端与本地分支（`git push origin --delete`、`git branch -d`） |
| 本地只留两条 | `main` 与 `dev`；其他分支存在超过 3 天要说明原因 |
| 里程碑才打标签 | 功能闭环/上线节点才打 `tag`，不按提交打 |

清理前状态：远端 17 条（15 条特性分支 + main/dev），全部已合并；清理后仅 main/dev。
