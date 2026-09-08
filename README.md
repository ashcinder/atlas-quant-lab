# Atlas Quant Lab

Atlas Quant Lab 是一个支持多用户的策略研究、历史回测与个人资产账本平台。它提供交易终端式 K 线工作台、常见策略参数化回测、交易标记、风险指标、交易明细，以及全天候、风险平价等多资产组合实验室。

> Strategy developers: see [Atlas Strategy Lab](docs/STRATEGY_DEVELOPMENT.md) for the `.qstrategy` package, Python SDK, private Runner contract, AI workflow permissions, and production safety boundary.

> 新增：[隔离执行、AI / TEE 与程序 ZKP 的实际能力和部署说明](docs/EXECUTION_TRUST.md)。支持有界整数策略程序的真实 ZKP，不等于任意 Python 或 AI 已可证明；TEE 尚无真实硬件端到端验收。

> 本项目只用于研究和历史模拟，不连接实盘账户，也不构成投资建议。

## 核心能力

- 多资产：加密货币、A/H 股、美股、ETF、指数、外汇和商品。
- 多周期：15 分钟、1 小时、4 小时、日线和周线。
- 单标的策略：定投、网格、马丁/反马丁、均线、MACD、RSI、布林带、突破和动量。
- 组合策略：全天候、风险平价和 60/40 再平衡。
- 可信回测：下一根 K 线成交、手续费、滑点、价差、样本量警告、样本外与市场阶段分析。
- 可视化：K 线、成交量、MACD、买卖标记、权益与回撤曲线、交易记录；VOL/MACD 可独立开关。
- 真实行情：加密货币使用 Binance，美股/ETF/A 股/外汇/商品使用新浪广覆盖行情，港股使用腾讯并配置分钟线补充源，Yahoo 作为兼容备选；真实源失败时明确报错，不会伪造演示 K 线。
- 金融指标：右侧按需查看 PE、PB、PS、PEG、EV/EBITDA、ROE/ROA、利润率、成长、偿债、现金流、分红、ETF 与市场/供给等约 60 项适用指标；显示数据源、时间、覆盖率、缓存状态和派生口径，缺失值不做估算。
- 流畅交互：行情定时增量刷新、短时缓存、响应压缩、请求取消与图表原位更新。
- 可调布局：左侧市场、右侧策略、底部结果均可拖动调整，价格轴保留安全宽度；回测结果可收起、还原或最大化。
- 参数化研究：每个单标的策略提供 4–5 个有实际信号影响的专属参数，并共享仓位上限、成交量参与率、止损和止盈等风控设置。
- 策略实验室：把规则构建、AI 工作流、研究验证、私密版本包和 SDK 收敛到 `DRAFT → COMPOSE → VALIDATE → VERSION` 生命周期；切换阶段保留编辑状态，并可从 QuantJudge 一键返回开发上下文。
- 策略验证：并行比较多个策略、受限参数网格、独立留出集、Walk-forward 滚动验证、过拟合警告和稳健性排名；任务在后端异步执行并可取消。
- 可视化规则构建器：用指标、比较关系和 AND/OR 条件组合策略，模板持久化到本地；只执行受控 DSL，不执行用户代码。
- 历史回放：逐根推进 K 线且严格隐藏未来数据，支持播放、单步、带手续费与滑点的模拟买卖，并按标的恢复回放进度。
- 提醒中心：支持价格、单根涨幅、RSI 和 MACD 条件；后端独立轮询、冷却去重、通知持久化，并可选浏览器桌面通知。
- 统一口径：CNY、USD、USDT 基准币种与自动/前复权/后复权/不复权设置。
- 本地优先：邮箱注册后使用独立工作区，账本、策略模板、回测历史与提醒保存在 SQLite。

## 整合后的资产账本

顶部可在“策略工作台”和“资产账本”之间切换，统一使用 Atlas 深色界面。

- 资产总览、USD/CNY 汇总、资产配置、收益与历史曲线。
- 账户、账户图片、资产管理；当前金额与本金/收益额/收益率三种录入依据。
- 流水、账户间转账、估值、本金更正、归档、删除和筛选。
- 多资产金额/比例定投，北京时间调度，CN/US/Crypto 交易日历，暂停、跳过与补记。
- 投资手记、月度预算、汇率更新、手工汇率和休市日历维护。
- 浏览器内截图 OCR，确认后原子保存；JSON 备份恢复、CSV 流水导出、两种清空模式。
- 注册、登录、退出与改密；账本、回测、研究任务、模板、提醒和通知均按用户隔离。

生产业务后端统一为 **FastAPI + SQLite**，不需要澄明 Node 服务、Cloudflare、D1 或 ChatGPT 登录。原澄明项目保留原样作为参考，整合后的应用可独立运行。

新用户从空账本开始，不迁移原数据库。JSON 导入/导出仍兼容澄明 v1 账本格式。内置汇率是标有日期的历史参考值，自动更新失败时可手工维护；自动定投只记账、不执行真实交易。

完整功能映射、修改位置和验证记录见 [整合说明](docs/INTEGRATION.md)。

## QuantJudge 与可信策略开发

策略项目和订阅按登录账号隔离；公开 Agent 与跑分可在登录后浏览，私密包和工作流还需要对应开发者凭证。
- QuantJudge 市场：量化策略 / AI Agent 公开跑分、分类排行、证据账本、本地沙盒订阅和开发者发布流程。
- 隐私证明：固定 RISC Zero zkVM guest 可证明私密 SMA 参数或 v2 有界整数策略程序在指定行情和成本模型上生成公开业绩；证明路径不保存 witness、参数或逐笔决策。普通 Python 上传包仍为平台可解密存储，不具备此保密性。
- Supervisor 验证：通过独立 JSON-RPC 适配器读取链 ID、区块与交易回执；只接收外部钱包已签名交易，平台不保管链上私钥。

## 项目结构

```text
backend/       FastAPI API、行情、回测、研究任务与本地数据
frontend/      React + TypeScript 交易与策略实验室界面
strategy/      策略 SDK、示例、打包工具和 RISC Zero ZKP 工程
docs/          产品、架构、策略开发与证明协议文档
Supervisor/    用户配置的外部链监督节点，只读且不纳入本仓库
.artifacts/    本地测试截图等临时产物，不纳入 Git
```

完整职责和维护边界见 [项目目录说明](docs/PROJECT_STRUCTURE.md)。

## 本地启动

新版工作空间说明见 [UI 重构记录](docs/UI_REDESIGN.md) 和 [本轮功能与部署进度](docs/REFACTOR_PROGRESS.md)。
容器化本机 / 私网部署见 [部署、持久化与备份指南](docs/DEPLOYMENT.md)；当前不是可直接暴露公网的多用户服务。

### 后端

部署锁文件针对 Python 3.14；请使用对应解释器创建虚拟环境。

```bash
cd backend
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
uvicorn app.main:app --reload --port 8000
```

### 前端

```bash
cd frontend
npm ci
npm run dev

```

访问 `http://localhost:5173`，首次使用点击“创建账号”。前端通过 Vite 代理访问同源 `/api/*`，后端运行于 `8000` 端口。

安装完成后，也可在项目根目录运行 `./scripts/dev.sh` 同时启动前后端。源码支持 Python 3.11+（本地验证使用 3.12）；部署锁文件与 CI 使用 Python 3.14。Node.js 需要 24–26。macOS 的 TEE 证书校验需将 OpenSSL 3 加入 PATH，不能使用系统 LibreSSL。

## 测试

```bash
cd backend && .venv/bin/pytest
cd frontend && npm test && npm run build
```

页面中的 K 线使用标的原始报价币种。顶部“组合基准币种”仅用于多资产组合回测的历史汇率换算。`演示数据` 必须手动选择，适合离线体验与测试，不代表真实市场。

金融指标页提供的是带时间戳的当前快照，用于查看和横向比较。它不会自动进入历史回测；在接入 point-in-time 财报库之前，禁止使用当前 PE、PB 等字段回填历史时点，以免产生前视偏差。

研究任务和提醒监控由后端进程承载；关闭后端会停止新任务和行情轮询，但已保存的策略、任务结果、提醒规则与通知不会丢失。

QuantJudge 默认使用 `http://127.0.0.1:42515` 读取 Supervisor JSON-RPC，可通过 `QUANTJUDGE_SUPERVISOR_RPC_URL` 修改。未连接 Supervisor 时仍可发布和验证本地密码学回执，但界面会明确标记为“待锚定”，不会冒充链上确认。

更多信息见 [产品规格](docs/PRD.md)、[系统架构](docs/ARCHITECTURE.md)、[ZKP 协议与威胁模型](docs/ZKP.md) 和 [QuantJudge 证明与链接入](docs/QUANTJUDGE.md)。

## 界面预览

![单标的策略回测](docs/assets/ui-single.png)

![多资产风险分析](docs/assets/ui-portfolio.png)

## 独立服务器部署

```bash
cp .env.example .env
# 编辑 .env，将 ATLAS_ALLOWED_ORIGINS 设置为实际 HTTPS 域名。
docker compose up -d --build
```

Compose 使用前端 Nginx 与后端 API 两个容器，仅映射 `127.0.0.1:8080`。SQLite、行情缓存和会话/证明/包加密密钥保存在 `atlas-data` 命名卷中。后端单进程启动研究、提醒和自动定投。旧单镜像 `Dockerfile` 仍可单独构建使用。已有部署升级前请阅读 [部署指南](docs/DEPLOYMENT.md)，核对原 Compose 项目名和数据卷，避免连接空卷。

例如 Nginx 的站点 location（证书配置由服务器管理）：

```nginx
location / {
    proxy_pass http://127.0.0.1:8080;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    client_max_body_size 20m;
}
```

首次注册自己的账号后，可将 `ATLAS_ALLOW_REGISTRATION=false` 关闭公开注册，再重建容器配置。默认会话密钥首次生成后保存在数据目录 `.session-secret`；也可显式提供不少于 32 字符的 `ATLAS_SESSION_SECRET`。修改密码会使其他设备的会话失效。

不使用 Docker 时，先构建前端，然后运行：

```bash
cd frontend && npm ci && npm run build
cd ../backend
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

环境变量：`ATLAS_DATA_DIR` 指定存储目录；`ATLAS_STATIC_DIR` 指定前端构建目录；`ATLAS_ALLOWED_ORIGINS` 是逗号分隔的前端来源。对外服务请配置 HTTPS，并只信任实际反向代理传入的转发头。
