# main → QuantJudge 合并交付与运行指南

更新：2026-09-08。来源为 `origin/main` 的 `b7e06dc`（投资账本整合）；目标为已有程序 ZKP 与隔离 Runner 的 `QuantJudge`。采用保留双亲历史的 Git merge，不替换现有项目，不修改 Supervisor。

## 合入功能

- 账号：注册、登录、退出、改密、七天签名 HttpOnly 会话；注册后的投资账本为空。
- 资产账本：USD/CNY 总资产、投入/收益、资产配置、账户和图片、数量或金额持仓、账户转账与流水。
- 定投与手账：多资产定投、金额/比例分配、交易日历、跳过/补记/暂停、月度预算与投资手记。后台每分钟检查，只生成账本记录，不下单。
- 数据工具：汇率获取/历史维护、截图 OCR 预览确认、JSON v1 备份导入导出、CSV 导出、版本冲突提示与带确认的清空。
- 保留：金融指标、单标的/组合回测、研究与策略实验室、QuantJudge、私密策略包、gVisor 研究执行、程序 ZKP v2。

## 本次额外优化

1. 统一 pnpm 和固定版本锁文件，避免同时维护 npm/pnpm 两套依赖；保留非 root、只读、资源受限的 api/web 部署。
2. 将量化 CSS 限定在量化容器内，防止账本的导航、表格和表单受原样式干扰；延迟加载两个工作区和 OCR / 图表模块。
3. 使用 React Activity 保留已访问工作区的草稿，隐藏时清理其 Effects；登录失效或更换账号则卸载私密页面。异步会话响应有过期保护。
4. 修复新增 JSON-only 中间件误拦策略包和 ZKP 上传：按路由限制 10 MiB 包 / 16 MiB receipt，普通账本 JSON 仍限制 4 MB；上传前要求登录，私密操作仍要求开发者凭证。
5. 策略项目、同 ID 策略模板、研究制品和订阅补上账户隔离；绑定私密包/工作流必须验证 Agent 凭证，不能凭猜到 ID 关联他人制品。
6. OCR Worker 和 WASM 执行代码从锁定依赖构建为本站静态资源，不从外部 CDN 加载执行代码；英文语言数据首次仍需 CDN，可缓存。图片在浏览器内识别，不发送第三方 OCR 服务。
7. 更新真实容器冒烟测试，验证登录、空账本、离线回测、数据卷及会话/证明密钥跨重建保留。

删除的重复 `frontend/package-lock.json` 和根 `Dockerfile` 仅是被替代的配置；可从 `main` 的 Git 历史恢复，不涉及个人数据。

## 启动：本地开发

使用 Python 3.14、Node 24、pnpm 11.19.0。以下是两个独立终端，不要重复启动已占用的 8000/5173 端口。

```bash
# 终端一
cd /Users/tangyucinder/开发/加密货币投资
# 已存在且可用的 .venv 不必重建
python3.14 -m venv backend/.venv
backend/.venv/bin/python -m pip install -r backend/requirements-dev.lock
cd backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

```bash
# 终端二
cd /Users/tangyucinder/开发/加密货币投资/frontend
npm install --global pnpm@11.19.0
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1 --strictPort
```

浏览器访问 **http://127.0.0.1:5173**，首次创建账号，再选择“策略工作台”或“资产账本”。API 文档为 http://127.0.0.1:8000/api/docs，业务 API 需要登录 Cookie；健康检查公开。正常开发不必配置 `VITE_API_ROOT`，避免认证和账本请求跨域。

安装完依赖后，也可以在根目录用 `bash scripts/dev.sh` 一次启动两项服务，Ctrl+C 停止。不要同时运行脚本和上述两个终端。

## 启动：本机 / 私网容器

```bash
cd /Users/tangyucinder/开发/加密货币投资
docker compose config --quiet
docker compose up --build --detach --wait --wait-timeout 180
docker compose ps
```

打开 **http://127.0.0.1:8080**。前端 Nginx 和后端 FastAPI 共用来源，仅前端发布回环端口；需要先启动 Docker Desktop。停止用 `docker compose down`，不要加 `--volumes`。持久化数据位于命名卷 `atlas-data`，不是开发时的 `backend/.data`，两种运行方式的账号不自动共享。

基础 Compose 不启动 gVisor Runner、模型、TEE、zkVM 证明者或 Supervisor。可选能力见 [执行与信任说明](EXECUTION_TRUST.md)。不要将 macOS 编译的 zkVM 二进制直接复制进 Linux 容器。

## 技术栈和职责

| 技术 | 在本项目的作用 |
| --- | --- |
| React 19 + TypeScript | 登录与双工作区、策略编辑器、账本表单、状态管理和类型检查；Activity 保留切换状态 |
| Vite + pnpm | 本地开发/同源 API 代理、按需拆包、生产构建；锁定依赖版本 |
| CSS / Tailwind 4 / Base UI | 量化界面的自有设计系统，账本工具类和可访问对话框等基础组件；样式相互隔离 |
| Lightweight Charts / Recharts | 前者绘制 K 线、指标、交易标记；后者展示账本资产、配置与收益图 |
| Tesseract.js + Web Worker / WASM | 浏览器本地 OCR，后台线程避免阻塞页面，用户确认后才写入账本 |
| Python 3.14 + FastAPI / Uvicorn / Pydantic | 统一 HTTP API、认证、账本及策略业务、请求校验、后台任务和服务运行 |
| NumPy / pandas / SciPy | 行情序列、指标、单标的/组合模拟与风险统计；不能把计算结果本身等同 ZKP |
| SQLite + WAL / revision | 持久化账号、账本、回测和项目，按用户查询；乐观并发检查防止账本互相覆盖 |
| scrypt / HMAC / cryptography | 密码散列、会话签名、包静态加密与平台签名；静态加密不等于对运营者保密 |
| HTTPX / 行情适配器 | 获取行情、财务指标与汇率；外部服务失败会明确显示，不伪造数据 |
| Rust + RISC Zero | 固定版本 guest 运行私密策略并生成可验证 receipt；v2 为有界整数程序，不是任意 Python ZKP |
| Docker / gVisor | 前后端部署和受限 Python 策略隔离；二者不等于 TEE |
| Nitro 验证器 / Supervisor RPC | 前者校验硬件通道证明但尚无真实机密执行；后者维持已有只读连接边界 |
| Nginx / Compose / GitHub Actions | 同源反向代理、静态资源、安全响应头、持久卷及自动测试和真实容器验收 |

## 数据与能力边界

- 首次升级前请停服备份整个 `backend/.data/`，包括隐藏密钥。不会自动导入另一项目的私人账本或示例记录。
- 旧无账号数据仍在原表，归属 `local`，不会自动让首个注册者继承；需单独确认迁移归属，不能以删除数据库解决。
- 邮箱目前仅用作登录标识；没有邮件验证、找回密码、多租户配额及完整公网安全审计，建议保持本机/私网部署。
- 自动定投是账本计划，不连接券商/交易所成交；日历支持沿用的已知年份，未知年份需人工维护。
- 上传 Python 包不自动获得 ZKP/TEE；真实 AI、真实 Enclave 和通用 Python ZKP 的未完成项继续如实标注。

## 验证方式

```bash
cd backend && .venv/bin/pytest && .venv/bin/pip check
cd ../frontend && pnpm test && pnpm lint && pnpm build
cd .. && docker compose config --quiet
# 只创建与删除带随机名称的临时容器/卷：
python3 deploy/smoke.py
```

本轮额外测试覆盖跨账号项目读写/制品关联/订阅、multipart 上传、工作区切换保留草稿及会话失效卸载。真实浏览器使用独立临时数据库，不注册或修改个人数据目录。
