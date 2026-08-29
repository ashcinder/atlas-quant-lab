# Atlas Quant Lab 系统架构

## 1. 总览

```text
React/TypeScript UI
  ├─ 行情工作台与技术指标
  ├─ 单标的策略参数
  ├─ 多资产组合参数
  ├─ 策略实验室（规则、AI 工作流、验证、版本与 SDK）
  ├─ QuantJudge 市场、订阅与发布
  └─ 结果、历史与可信度轨道
             │ HTTP/JSON
FastAPI API
  ├─ Asset Catalog     统一标的与搜索
  ├─ Market Data       数据源适配、标准化、复权、缓存
  ├─ Indicators        SMA/EMA/MACD/RSI/BOLL/ATR/KDJ
  ├─ Strategy Catalog  参数模式与信号生成
  ├─ Backtest Engine   下一根 K 线成交、成本、交易账本
  ├─ Portfolio Engine  再平衡、风险平价、币种归一
  ├─ Risk Analytics    收益、风险、统计和市场阶段
  ├─ Research Service  异步网格研究、留出集、Walk-forward
  ├─ Custom DSL        受限指标规则树与因果信号计算
  ├─ Alert Monitor     后台轮询、冷却去重、通知持久化
  ├─ QuantJudge        Agent 市场、跑分、订阅与回执验证
  ├─ Strategy Lab      规则、私密策略包、AI 工作流、验证与版本编排
  ├─ Proof Attestor    SHA-256 / Merkle / Ed25519 证据链
  ├─ Supervisor RPC    链状态、交易载荷与回执校验
  └─ Workspace Store   SQLite 回测、研究、模板、提醒与通知
             │
Local files
  ├─ SQLite 元数据和回测结果
  └─ 压缩 CSV 行情缓存
```

## 2. 数据源策略

后端使用 provider interface，不让页面或回测引擎依赖具体供应商：

```text
search(query) -> Asset[]
fetch_bars(asset, interval, start, end, adjustment) -> Bar[]
```

首版提供：

- Binance 加密货币公开行情适配器。
- 新浪广覆盖行情适配器：美股、ETF、A 股、外汇和商品。
- 腾讯港股行情适配器，分钟线可使用补充源扩展历史深度。
- Yahoo 兼容备选适配器，不作为当前网络环境的唯一真实源。
- 明确标识的离线演示数据适配器，用于无网络启动和自动测试。

自动模式只会在真实数据源之间切换；真实源全部失败时返回明确错误，禁止静默生成演示数据。
缓存键由数据源、标的、周期、日期和复权方式共同组成，避免不同口径相互覆盖。实时请求使用按周期设置的短 TTL；过期后只从缓存末端附近增量拉取并合并。刷新失败时可显示上一次真实缓存，但会标记为过期。

## 3. 回测事件顺序

```text
bar[t] 收盘
  → 更新只依赖 <= t 的指标
  → 策略产生 target/order intent
bar[t+1] 开盘
  → 应用滑点与价差
  → 检查现金、仓位和最大参与率
  → 扣手续费并写入成交账本
  → 以 bar[t+1] 收盘盯市
```

交易标记来自成交账本，而不是策略信号，保证图表与收益计算一致。

## 4. 存储模型

### backtest_runs

- `id`, `mode`, `strategy_id`, `symbol`
- `request_json`, `result_json`
- `created_at`, `status`, `data_source`

行情使用文件缓存；首版不把大量 OHLCV 写进 SQLite。

### research_jobs / custom_strategies / alert_rules / alert_notifications

- 研究任务持久化状态、进度、请求和最终结果；进程重启会将未完成任务标记为失败，避免错误地长期显示“运行中”。
- 单次研究最多 500 组参数、含 Walk-forward 最多 2,500 次评估，线程池有界且任务可取消。
- 自定义策略只保存通过 Pydantic 校验的规则树，最大 5 层、50 个节点，不接受或执行任意代码。
- 提醒规则保存上次观测值、评估时间和触发时间，用于穿越判断与冷却去重；通知支持已读状态。

### qj_agents / qj_reports / qj_subscriptions

- `qj_agents` 只保存公开元数据、加盐策略承诺和开发者凭证哈希，不保存源码、提示词或参数。
- `qj_reports` 保存平台重算指标、降采样公开收益、决策 Merkle 根、前序回执哈希、Ed25519 签名和可选链上交易定位。原始净值和决策列表不入库。
- `qj_subscriptions` 是授权账本，沙盒与外部支付引用状态明确分离，未配置支付时不会产生真实扣款。

### qj_strategy_packages / qj_workflows / qj_workflow_revisions

- 策略包先经压缩比、路径、凭证文件、manifest、Python AST 与入口类校验，再使用 AES-256-GCM 加密落盘；API 进程不执行上传代码。
- 工作流明文不入库，当前图和每次修订均加密保存，并记录 graph hash。
- 校验器拒绝环、逆阶段连线、禁用节点连线、未审计执行，以及任何绕过确定性 `risk_gate` 的决策路径。

Supervisor 是运行时外部边界：Atlas 只通过 JSON-RPC 适配器与它交互，不导入或修改其源码。交易确认必须同时满足链上成功和 `ATLASQJ1 + receipt_hash` 载荷精确匹配。

## 5. API

- `GET /api/v1/health`
- `GET /api/v1/assets/search?q=`
- `GET /api/v1/market/bars`
- `GET /api/v1/strategies`
- `POST /api/v1/backtests`
- `POST /api/v1/portfolio/backtests`
- `GET /api/v1/runs`
- `GET /api/v1/runs/{id}`
- `DELETE /api/v1/runs/{id}`
- `POST /api/v1/research/jobs`
- `GET|DELETE /api/v1/research/jobs/{id}`
- `GET|PUT|DELETE /api/v1/custom-strategies`
- `GET|POST|PUT|DELETE /api/v1/alerts`
- `POST /api/v1/alerts/evaluate`
- `GET /api/v1/notifications`
- `POST /api/v1/notifications/read`
- `GET|POST /api/v1/quantjudge/agents`
- `POST /api/v1/quantjudge/agents/{id}/reports`
- `GET /api/v1/quantjudge/reports/{id}/verify`
- `POST /api/v1/quantjudge/reports/{id}/anchor`
- `PUT /api/v1/quantjudge/reports/{id}/chain-transaction`
- `GET|POST /api/v1/quantjudge/subscriptions`
- `GET /api/v1/quantjudge/chain/status`
- `GET /api/v1/quantjudge/studio/spec`
- `GET /api/v1/quantjudge/studio/templates`
- `POST /api/v1/quantjudge/studio/workflows/validate`
- `GET|POST /api/v1/quantjudge/agents/{id}/packages`
- `GET /api/v1/quantjudge/agents/{id}/packages/{package_id}/download`
- `GET|PUT /api/v1/quantjudge/agents/{id}/workflows`

## 6. UI设计系统

- 背景 `#0B0F14`，面板 `#111821`，浮层 `#18212C`。
- 分隔 `#253140`，次要文字 `#8B98A8`，主要文字 `#E6EDF5`。
- 盈利/买入 `#22C7A9`，亏损/卖出 `#FF5A67`，强调 `#F3B451`。
- 界面正文使用系统无衬线字体；数字、代码和时间使用等宽字体并启用 tabular numbers。
- 布局为顶部工具栏、左侧资产栏、中间图表、右侧策略参数、底部结果面板。
- 左右栏宽度和底部面板高度由无状态拖拽轨道调整；拖动过程直接更新 CSS 变量，结束后才写入本地偏好，避免高频 React 重渲染。
- 产品的识别元素是“回测可信度轨道”，不增加无关装饰和大面积渐变。
- 顶部“策略实验室”是唯一开发入口，按 `DRAFT → COMPOSE → VALIDATE → VERSION` 组织规则、AI 工作流、研究验证和私密包；QuantJudge 只承担市场、订阅、发布与验证。
- 策略研究使用固定的 `IS → OOS → WF → 稳健性` 验证带，参数热力图明确标注只属于样本内，避免把优化面板误当最终绩效。
- 回放状态作为图表内的紧凑工具条呈现；进入回放后图表、指标和系统交易标记都裁剪到当前时间点。
