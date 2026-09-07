# Clarity → Atlas 功能整合

> 本文保留同学在 `main/b7e06dc` 上的原始整合记录。当前 `QuantJudge` 的启动、依赖和部署方式以 [MAIN_MERGE.md](MAIN_MERGE.md) 为准：使用 pnpm、api/web 双容器，保留策略实验室及 ZKP；下文 npm/单容器说明不再适用于合并后的分支。

验收日期：2026-09-07。目标应用位于 `atlas-quant-lab-main`；`clarity-investment-journal-main` 保留原样。

## 已确认的边界

- 统一为 React + FastAPI + SQLite，支持本地开发和独立服务器运行。
- Atlas 增加邮箱注册、登录、退出、修改密码与用户隔离。
- 新用户从空账本开始，不自动迁移旧数据库，也不生成示例投资记录。
- 保留原有 v1 JSON 备份导入/导出功能，用户可自行选择导入。
- Clarity 的 Node、Cloudflare/D1 和 ChatGPT 登录部署路径由 Atlas 的统一服务替代。

## 功能映射

| 原有能力 | Atlas 中的位置与实现 |
| --- | --- |
| USD/CNY 总资产、投入、收益、配置、历史趋势 | 资产账本 → 资产总览、收益分析；保留原币现金流汇率与估值汇率口径 |
| 四类投资方向、账户、账户图片 | 账户与资产；账户编辑、归档、删除与图片校验保留 |
| 资产/持仓、数量、单价、金额录入 | 账户详情；保留旧数量持仓兼容及金额优先录入 |
| 当前金额 + 本金 / 收益额 / 收益率 | 资产录入与编辑；包含亏损、清零、本金更正、历史提取处理 |
| 入金、出金、收益、费用、估值、账户转账 | 记一笔、投资手账；编辑、删除、筛选和历史重算 |
| 多资产定投、金额/比例分配、计划币种 | 定投计划；跨币种投入按发生日汇率记账 |
| 每日/工作日/每周/每月、休市顺延、跳过、补记、暂停 | 定投计划；Python 调度器每分钟检查，打开账本时也同步，使用北京时间 |
| CN、US、Crypto 日历与自定义休市 | 偏好设置；保留原项目已知年份及未知年份保守停止规则 |
| 月度预算、日历、投资手记 | 投资手账和偏好设置；手记新增、编辑、删除保留 |
| 汇率自动获取、历史汇率、手工维护 | 偏好设置；FastAPI 提供汇率接口，失败时显示错误 |
| 截图 OCR、解析预览、确认保存 | 账户详情 → 截图识别；浏览器 Tesseract 识别，用户确认后提交账本 |
| JSON 备份恢复、CSV 导出 | 偏好设置；保留校验、CSV 转义和 4 MB 请求限制 |
| 清空投资记录，选择保留账户 | 偏好设置；需要输入“清空”，使用账本版本检查避免覆盖并发更新 |
| WebMCP 账本摘要和打开记账表单 | 浏览器支持时保留原有两个工具；打开表单不会自动提交 |
| 注册、登录、退出、改密 | 全局 Atlas 登录页及账本设置；两个工作区共用会话 |

Atlas 原有单标的、组合回测、研究任务、策略构建器、历史回放、提醒与通知仍位于“策略工作台”。新增用户归属校验覆盖账本、回测记录、研究任务、模板、提醒和通知；偏好及回放进度按用户划分浏览器存储键。

## 主要修改位置

| 文件或目录 | 修改内容 |
| --- | --- |
| `frontend/src/AtlasShell.tsx` | 全局登录、会话恢复/过期处理、退出、两工作区导航和延迟加载 |
| `frontend/src/main.tsx`、`shell.css`、`styles.css` | 挂载统一外壳，沿用 Atlas 深色与金色操作按钮；隔离量化与账本 CSS，适配移动端 |
| `frontend/src/journal/components/` | 整合账本页面、独立登录页、图表、OCR 和实际使用的 UI 组件 |
| `frontend/src/journal/domain/`、`lib/`、`request.ts` | 保留原 TypeScript 账本算法、图片校验、OCR 解析；统一同源认证请求 |
| `frontend/src/journal/styles/` | 将原澄明样式限制在账本容器内，并映射到 Atlas 色彩 |
| `frontend/src/api.ts`、`storage.ts`、`components/TradingChart.tsx` | API 会话失效处理；偏好与回放进度用户隔离 |
| `frontend/package.json`、`package-lock.json`、`postcss.config.mjs`、`vite.config.ts`、`tsconfig.app.json` | 增加必需组件/图表/OCR依赖，统一 npm，支持样式构建与迁入的测试；移除旧 pnpm 锁文件 |
| `backend/app/auth.py`、`config.py` | scrypt 密码散列、签名会话、HttpOnly/SameSite Cookie、持久密钥及部署配置 |
| `backend/app/journal/domain.py` | 纯 Python v1 校验、空账本、清空、交易日历、汇率与自动定投，生产环境不依赖 Node |
| `backend/app/journal/store.py` | SQLite 用户、账本和 revision 乐观并发控制 |
| `backend/app/journal/router.py`、`scheduler.py` | 认证/账本/汇率 API、请求来源校验、失败次数限制、后台定投与用户级故障隔离 |
| `backend/app/main.py` | 挂载账本 API、原量化 API 统一鉴权、请求体限制、后台服务生命周期、生产静态页面 |
| `backend/app/storage.py`、`research.py`、`workspace.py` | 原量化存储按用户隔离；策略模板主键改为用户与模板 ID 组合，允许不同用户同名模板 |
| `backend/tests/`、`frontend/tests/`、`frontend/src/storage.test.ts` | 原始账本回归、跨语言对照、API安全/隔离/并发、数据库兼容与用户偏好测试 |
| `Dockerfile`、`compose.yaml`、`.dockerignore`、`.env.example`、`scripts/dev.sh` | 单服务生产构建、持久数据卷、环境配置和本地双服务启动脚本 |
| `README.md`、`docs/ARCHITECTURE.md`、本文 | 功能、启动、部署和变更记录 |

旧 Atlas 无用户数据的数据库表会兼容增加 `owner_id`，旧记录保留为 `local` 归属，不自动归给任何新注册用户，避免意外暴露。若将来需要取回这些旧记录，应另行做明确的归属迁移。

## API 约定

- 公开：`GET /api/session`、`POST /api/login`、`POST /api/register` 及健康检查。
- 账本：`GET/PUT /api/ledger`、`POST /api/reset`、`GET /api/fx`。
- 账户：`POST /api/logout`、`POST /api/change-password`。
- 原 `/api/v1/*` 业务接口需要登录；跨用户读取/修改/删除资源返回 404。
- 修改账本及清空需要当前 `revision`；并发冲突返回 409，客户端提示刷新。
- 登录 Cookie 默认七天；改密使其他设备的旧会话失效；HTTPS 下 Cookie 设置 Secure。
- 浏览器通过同源 API 工作。开发由 Vite 代理，生产由 FastAPI 同时提供构建页面与接口。在线接口文档在 `/api/docs`。

## 验证记录

- 后端：`pytest` **182 项通过**，包含 122 个原 TypeScript 校验样本和 21 个自动记账对照样本。对照测试只忽略随机生成的流水 ID，金额、数量、日期、备注和分配结果均比较。
- 前端：Vitest **7 项**、迁入 Node 测试 **61 项通过**；后者保留原始示例数据测试，但生产新账本由后端空状态创建。
- `npm run lint`、`npm run build` 通过；新增认证、账本模块与对应测试的 Ruff 检查通过。
- 浏览器：统一登录、两工作区切换、账户/资产新增保存、资产汇总，1440px 桌面与 390px 手机布局；演示数据回测显示成交、指标、图表和历史记录。
- `bash -n scripts/dev.sh` 和 `docker compose config --quiet` 通过。
- 已直接运行生产构建：FastAPI 首页及其 JS/CSS 资源均返回 200，浏览器显示统一登录入口；默认数据目录没有注册用户，验收账户仅在临时目录。

验证范围：截图 OCR 的解析与 TSV 用例已通过，未用实际图片运行完整识别引擎；首次加载 OCR 语言资源需要网络。当前电脑的 Docker daemon 未运行，因此未执行镜像构建和容器部署；生产配置已完成，服务器首次部署仍需运行构建验收。自动定投只生成账本记录，不执行实盘交易。交易日历沿用原项目的已知年份，后续年份需维护。

测试使用临时数据目录，不写入个人账本。使用方法见项目根目录 README。
