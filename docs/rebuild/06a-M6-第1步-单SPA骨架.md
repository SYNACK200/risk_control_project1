# M6 第 1 步：单页应用骨架 + 共享层 + 三个公开页

> 日期 2026-11-10 · 分支 `rebuild/v1` · 对应方案第 1 步

## 交付

| 交付物 | 路径 | 说明 |
| --- | --- | --- |
| 新单页应用 | `web/` | Vite + React，base `/`，dev 代理 `/api` → 8010 |
| 共享请求层 | `web/src/api/client.ts` | base、token、错误码、超时唯一出口；401 自动清会话 |
| 错误文案表 | `web/src/api/errors.ts` | 两种身份两套话术，合并前端时最容易丢的就是这个区分 |
| 会话状态 | `web/src/auth/store.ts` | 键名沿用 `bs_token` / `bs_user`，新旧页面并存期间不会互相踢下线 |
| 角色守卫 | `web/src/auth/guards.tsx` | 未登录回登录页；角色不符回自己的首页 |
| 公开页 | `web/src/pages/public/{Landing,Login,Register}.tsx` | 原 portal 三张静态页迁成组件 |
| 角色分包 | `web/src/pages/{borrower,banker}/*` | 懒加载，构建产物已按角色拆包 |

## 验收证据

### 构建

```
cd web && npx tsc -b        # 0 错误
npx vite build
dist/index.html                     0.42 kB
dist/assets/index-*.css             4.60 kB
dist/assets/BorrowerApp-*.js        1.08 kB   ← 按角色分包生效
dist/assets/BankerApp-*.js          1.13 kB
dist/assets/index-*.js            270.56 kB
✓ built in 406ms
```

### 渲染（无头 Chrome + CDP 实测，1424×805）

| 页面 | 结果 |
| --- | --- |
| `/login` | 左深色说明栏 + 右表单，身份切换页签、两个输入框、登录按钮、底部两个链接全部就位 |
| `/` | 卡片式落地页，两个身份入口（银行员工 / 借款人）、注册链接正常 |
| `/login` @ 764×485 | 响应式生效：单列堆叠，说明栏在最上，表单在下方 |

### 路由

`/app/*` 与 `/bank/*` 已挂角色守卫与懒加载分包；旧地址 `/portal` 重定向到 `/`。
两个工作台当前是「迁移进行中」占位页，并给出旧入口链接（`/app-old/` `/bank-old/`），
迁移期间业务不中断。

## 关于 node_modules

`web/node_modules` 是指向 `frontend-admin/node_modules` 的目录联接（junction），
目的是复用同一套 vite/react/typescript 版本、不重复装依赖。
它不进版本库；正式落地时改成 `npm ci`（`web/package-lock.json` 尚未生成，第 7 步统一补）。

## 还没做（第 2 步起）

借款侧两页、银行侧六个只读页、模板三页、标注页拆组件、阈值/实体/OCR 路由、
删旧前端并把后端静态挂载改到 `web/dist`、data 收编、contract/CHANGELOG 回写。
