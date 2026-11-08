# DeAI Quant Hub 系统架构全景

架构初稿日期为 2026-11-05，按 2026-11-09 的 r23 本机验收更新。版本、验收条件和边界见[当前状态](CURRENT_STATUS.md)。

## 1. 系统定位与边界

DeAI Quant Hub 将策略开发、投资研究、策略发布订阅、证据验证、账户运行和个人投资账本连接在一个应用中。

核心分工：**浏览器承担主要研究计算；平台承担记录、身份与权限、保密策略执行和真实验真；作者设备生成 Proof；公共文件通过对象存储和 CDN 分发。**

平台不在主站部署模型推理，不托管用户资金。研究结果、模拟成交、交易建议、交易所确认成交、普通签名报告和 ZKP 分别记录，不能相互冒充。

系统目前以一个前端和一个模块化后端应用为主，保密计算使用后端启动的独立子进程；不是每个业务模块各自部署一个微服务。Supervisor/MySQL 是独立服务，行情发布器也是独立生命周期。

| 层 | 技术与实现 |
| --- | --- |
| 用户界面 | React 19、TypeScript、Vite；Lightweight Charts/Recharts；Tesseract 浏览器 OCR |
| 浏览器计算 | TypeScript ES Module Worker、BigInt、Web Crypto SHA-256、IndexedDB |
| 服务端 | Python FastAPI、Pydantic、Uvicorn；原计算基准依赖 NumPy/Pandas/SciPy |
| 持久化与分发 | 主业务 SQLite、内容地址文件、可选公共 S3/CDN；链侧 MySQL/节点状态 |
| 证明工具链 | 作者侧 Rust/RISC Zero zkVM、固定 guest/profile/Image ID；服务端真实 receipt 验证器 |
| 链与部署 | Supervisor Go 服务、JSON-RPC；Docker Compose、Nginx、独立持久卷 |

## 2. 全局逻辑架构

~~~mermaid
flowchart TB
  subgraph Browser["用户设备：浏览器"]
    UI["React 界面\n研究、策略实验室、市场、交易、账本"]
    C["计算客户端\n身份、能力、任务编排"]
    W["TypeScript Web Worker\n回测、组合、研究、指标、评分、运行信号"]
    IDB[("IndexedDB\n清单、数据块、任务、研究、结果")]
    UI --> C
    C --> W
    C <--> IDB
  end
  subgraph App["平台主站：轻量服务端"]
    WEB["Nginx\n静态前端、API 反向代理"]
    API["FastAPI 模块化应用\n认证、权限、记录、运行、支付、验真"]
    SQL[("SQLite\n账户、版本、授权、索引、账本、订单")]
    PRIV["Linux 受限独立进程\n保密订阅策略：单次回测 / 按需信号"]
    OBJ[("私有持久文件\n结果对象、策略材料、receipt、服务密钥")]
    WEB --> API
    API <--> SQL
    API --> PRIV
    API <--> OBJ
  end
  subgraph Publication["公共数据与分发"]
    PUB["独立行情采集与发布器"]
    STORE[("公共对象目录 / 对象存储\n不可变行情块、公开报告、已发布 receipt")]
    CDN["CDN 分发\n外部服务待配置"]
    PUB --> STORE
    STORE --> CDN
  end
  AUTHOR["作者本机\n源码、私有 witness、RISC Zero 证明器"]
  SOURCES["外部行情源 / 历史汇率"]
  MODEL["用户配置的外部云模型"]
  VENUE["交易所 / 交易测试服务"]
  CHAIN["Supervisor RPC\n独立链服务"]
  MYSQL[("MySQL + 链状态\n独立资源预算")]
  C -->|"会话、能力、清单、保存"| WEB
  CDN -->|"公共文件直接下载、SHA 校验"| C
  SOURCES --> PUB
  PUB -->|"登记版本与清单"| SQL
  API -->|"公开制品白名单导出"| STORE
  API <-->|"轻量代理；不承载模型推理"| MODEL
  API <-->|"授权、确认、订单核对"| VENUE
  API <-->|"支付收据与存证核对"| CHAIN
  CHAIN <--> MYSQL
  AUTHOR -->|"仅提交生成的 receipt；不提交私有 witness"| API
~~~

图中的对象存储/CDN是已实现的发布接口与目标部署关系。默认配置仍可由 API 提供公共文件；尚未接入真实外部 CDN 时，公共下载仍消耗应用服务器带宽。

## 3. 每项工作在哪里执行

| 工作 | 当前执行位置 | 服务器保留的职责 |
| --- | --- | --- |
| 自有策略、获得使用权限的公开逻辑策略，单次回测 | 浏览器 Worker | 权限、不可变版本、数据清单、结果保存 |
| 组合回测、再平衡、风险平价 | 浏览器 Worker | 发布组合所需数据及历史换汇版本、保存索引 |
| 参数网格、样本外、Walk-forward、稳健性研究 | 浏览器 Worker | 研究结果记录、项目制品关联 |
| 技术指标、绩效指标、六维评价 | 浏览器 Worker | 公共报告和 Proof 的独立绑定/验真规则仍在后端 |
| 提醒条件 | 浏览器计算，指标由 Worker 生成 | 归属、启用状态、冷却去重、通知入库 |
| 自有/公开行情策略的按需运行信号 | 浏览器 Worker | 数据版本、租约、账户、资金与订单规则 |
| 保密订阅策略单次回测、行情信号 | 服务端受限独立进程 | 权限复查、并发与资源限制、返回值脱敏 |
| 实时报价联调、作者签名信号 | 专用服务端运行路径 | 只支持对应按需运行；不是历史回测能力 |
| 受限 Python 编译 | 服务端轻量编译接口 | AST/受限语法校验，输出既有指令表示 |
| 受限 Python 指令计算 | 浏览器 BigInt；保密版本在受限子进程 | 不开放任意 Python 执行 |
| ZK Proof 生成 | 作者本机工具 | 不再默认创建服务器 Proof 计算任务 |
| receipt 真实验真、报告绑定、离线包导出 | 服务端；离线包可在下载后独立验真 | 合法 profile、Image ID、journal/报告一致性 |
| 云模型推理 | 用户自行配置的外部服务 | 会话配置、必要代理、结构化响应校验 |
| 账本校验、账本定投计划、支付和真实交易核对 | 服务端 | 账本与研究计算不共用可信等级 |
| 行情采集、不可变文件发布 | 独立发布任务 | 不因普通回测请求临时采集 |

“公开逻辑”与“有权使用”是不同判断：能力接口仍先检查作者身份或活动订阅。公开可见性决定授权后是否可以把策略逻辑交给浏览器，不自动免除订阅检查。

## 4. 浏览器内部架构

### 4.1 界面与计算分层

界面通过原 API 客户端入口调用新的计算客户端。客户端负责取得身份与能力、选择数据集、校验覆盖范围、启动 Worker、处理进度与取消、保存本地任务并上传结果。界面不直接实现成交模拟。

~~~mermaid
flowchart LR
  V["业务界面"] --> A["api.ts / compute/client.ts"]
  A --> CAP["服务端能力与身份"]
  A --> M["market.ts\n清单、分块、SHA、缓存"]
  A --> P["persistence.ts\nIndexedDB 与中断恢复"]
  A <-->|"任务 / 进度 / 完成 / 错误"| W["worker.ts"]
  W --> B["backtest.ts\n单策略成交引擎"]
  W --> PF["portfolio.ts\n组合与优化"]
  W --> R["research.ts\nIS / OOS / WF"]
  W --> I["indicators.ts / metrics.ts\nevaluation.ts"]
  W --> S["strategies.ts\npythonProgram.ts / runtime.ts"]
  W -->|"可选 AI 审核消息"| A
~~~

主要目录：[frontend/src/compute](../frontend/src/compute)。

### 4.2 算法范围与时序

- 单策略覆盖现有定投、逢跌定投、网格、马丁/反马丁、均线、MACD、RSI、布林、突破、动量，以及受限规则树与整数程序。
- 组合覆盖全天候、风险平价、60/40、权重约束、现金缓冲、换汇和再平衡。组合使用预发布换汇数据集；单次回测沿用原报价币种。
- 研究包含训练窗口选参、样本外评估、Walk-forward 和过拟合风险提示。测试窗口不反过来选参。
- 六维评价包含收益、风险调整效率、风险控制、市场适应性、回测实盘一致性、策略纯度。缺少配对实盘、风格/持仓等证据时明确不可评估，不补造总分。
- 原有 Python 引擎保留为保密运行和算法对照基准，不再作为普通浏览器任务失败后的计算回退。

共同成交时序：

~~~mermaid
flowchart LR
  A["第 t 根收盘\n仅使用截至 t 的数据"] --> B["计算指标与目标仓位"]
  B --> C["第 t+1 根开盘\n执行挂起交易意图"]
  C --> D["滑点、价差、现金和参与率约束"]
  D --> E["费用、部分成交与成交账本"]
  E --> F["收盘盯市、权益与绩效指标"]
~~~

图表成交标记来自实际模拟成交记录，不能用策略信号替代成交。预热、缺数、费用、日历和再平衡规则均属于算法契约。

### 4.3 本地任务生命周期

IndexedDB 按用户隔离，包含 chunks、manifests、runs、tasks、jobs 五类存储。数据块以内容哈希索引，任务保存请求、数据集引用、进度、错误与完成结果。

每次计算启动独立 Worker；取消时终止 Worker。页面关闭、会话失效、账号切换会停止计算。完成结果保留；刷新后原页面尚未完成的任务标记中断，需要重新运行，不能显示成后台持续计算或自动续算。

浏览器必须支持 Worker、IndexedDB、安全摘要。能力不足、空间不足、数据错误或算法失败都明确报错，不切到服务器普通回测。

缓存可避免再次下载和计算指标所需数据，但当前应用不是完整离线站点：登录、权限、新任务能力查询和跨设备同步仍有服务端依赖。

## 5. 数据供应、版本与存储

### 5.1 公共历史行情路径

~~~mermaid
sequenceDiagram
  participant S as 行情源/汇率源
  participant P as 独立发布器
  participant D as SQLite 清单登记
  participant O as 公共对象存储/CDN
  participant B as 浏览器
  participant W as Worker
  P->>S: 按明确标的、周期、复权、范围采集
  P->>P: 数据校验、历史换汇、每1000根分块
  P->>O: 原子写入内容哈希命名的不可变块
  P->>D: 登记 dataset_id、清单和当前查询版本
  B->>D: 经 API 查询已发布清单
  alt 数据未发布
    D-->>B: 202 preparing，不临时触发采集
  else 数据就绪
    D-->>B: 版本、来源、覆盖、块 URL 和 SHA-256
    B->>O: 直接下载缺失分块，不携带会话 Cookie
    B->>B: 校验哈希、顺序、数量、OHLCV，写入 IndexedDB
    B->>W: 提交固定输入并计算
  end
~~~

发布器入口：[backend/app/data/publish_market.py](../backend/app/data/publish_market.py)。行情源适配器、CandleStore 和历史汇率复用原数据层；明确 demo 数据始终保留演示标识，真实源失败不能静默切成演示行情。

清单包含 dataset_id、schema、标的、周期、复权方式、来源、抓取时间、stale 状态、数据起止/数量、发布查询 coverage、分块描述和换汇版本引用。coverage 与实际交易日首尾不同：周末和休市不制造 K 线；coverage 只是发布查询口径，不是来源完整性认证。

行情块每块最多1000根，文件名为 SHA-256.json。相同版本不可修改。清单当前指针可以更新，历史版本保留，单次研究固定所引用的版本。

校验失败、缺失、覆盖不足、指定来源不符时不能静默换输入。坏缓存删除后仍抛错，不将重新下载伪装成本次无误计算。哈希证明取得的字节与清单一致，不证明原始行情真实、完整或经过 zkTLS。

### 5.2 五类数据归属

| 数据位置 | 保存内容 | 访问与缓存 |
| --- | --- | --- |
| 浏览器 IndexedDB | 清单、行情块、任务、研究、完成结果 | 按用户分区；不是跨设备主数据库 |
| 主站 SQLite | 身份、会话、项目、版本、订阅、研究和回测索引、运行、订单、账本、清单登记 | 服务端授权；不接受客户端 owner 选用户 |
| 公共对象文件 | 行情块、白名单公开报告、已发布且绑定的 receipt | 公共 GET、immutable；可接 CDN |
| 私有持久文件 | 大结果对象、私有策略/工作流材料、旧云Proof恢复任务私有输入（若启用）、服务端签名/加密资料 | 鉴权访问，私有响应 no-store，不同步公共 bucket |
| Supervisor 的 MySQL/链状态 | 链侧交易和节点状态 | 独立服务和卷，不替代主站业务 SQLite |

当前对象实现是本地持久目录或对象存储挂载；显式配置 S3 后，通过 AWS CLI 上传公共块/公开制品。尚未实现或验证“所有私有结果直接写原生 S3 并用签名 URL 下载”的完整后端，不能把对象目录抽象当作已经完成云存储部署。

公开报告与 receipt 使用单独 artifacts-public 目录及登记白名单，只导出已经允许公开的字段与原始 receipt。私有源码、witness、开发者令牌和私有快照不能混入公共导出。离线验证包可通过原下载流程取得并自行分发，但不属于此CDN白名单，不应将整个输出目录同步到公共存储。

### 5.3 结果记录流

浏览器完成计算后先保存本地结果，再向 POST /api/v1/compute/runs 上传既有结构，附 engine_version、dataset_ids、strategy_version。

服务器完成以下工作：校验登录与引用版本；校验结果结构；生成记录 ID、所有者与入库时间；固定执行来源为 browser、证明状态为 unverified；将完整结果放私有对象；在 SQLite 中保留摘要、指标、权限和对象哈希。研究另外生成可用于项目关联的服务端研究 ID。

行情不重复嵌进每个新结果。打开历史结果时，浏览器按引用数据集补齐 K 线、重新计算展示指标，并裁剪到该次结果的原区间。旧记录仍可读取，不为迁移而重写历史 Proof 的数据字节或哈希。

### 5.4 关键实体与关系

下表是领域关联，不宣称所有关系都由数据库外键实现。

| 领域 | 主要实体/表 | 关联与作用 |
| --- | --- | --- |
| 身份 | users、sessions | 用户归属；会话哈希、版本、过期与撤销 |
| 个人账本 | ledgers | 每用户JSON状态＋revision；账户、资产、计划、手记等保存在该结构内 |
| 策略开发 | strategy_projects、自定义策略、工作流/修订、策略包 | 项目关联研究和制品ID/哈希，不以界面勾选替代验证门禁 |
| 不可变版本 | strategy_releases | 作者、版本、内容哈希、固定快照、公开可见性；后续运行绑定此版本 |
| 授权和支付 | strategy_subscriptions、bkc_offers、bkc_orders | 用户→指定release；订单同时绑定版本内容与链身份 |
| 回测/研究 | backtest_runs、research_jobs | owner、摘要、数据集引用、私有对象哈希、计算来源 |
| 行情出版 | market_publications、market_versions | 查询→当前dataset；dataset→不可变清单→内容地址块 |
| 策略运行 | strategy_accounts、strategy_runs、strategy_signals | 账户/版本/环境/标的/租约→目标信号和交易建议 |
| 资金与成交 | strategy_orders、strategy_fills、strategy_external_fills、strategy_fund_events、strategy_equity | 区分模拟与外部成交；订单、资金事件和净值保留对应归属 |
| 市场证据 | qj_agents、qj_reports、qj_zk_proofs、qj_market_datasets | 作者承诺→receipt/journal→报告→可选链定位 |
| 分发 | public_artifact_files、public_report_exports | 哪个报告允许导出哪些不可变公开文件 |
| 工作区记录 | alert_rules、alert_notifications等 | 规则状态、最近观测、冷却、通知与已读归属 |

业务流程可读成：开发和研究→准备策略版本→确认BKC订单→取得该release订阅→创建账户运行→产生信号/建议/模拟或外部成交记录。项目冻结和release发布是独立实体/接口，目前没有数据库外键将两者强制连成一条状态机。研究结果是项目制品之一，Proof报告是另一条独立证据链，不能只靠共享某个策略名称就自动绑定。

## 6. 保密策略执行与在线运行

### 6.1 保密单次回测

~~~mermaid
sequenceDiagram
  participant U as 已登录订阅者
  participant A as FastAPI
  participant R as 不可变版本与订阅登记
  participant Q as 串行执行通道
  participant X as Linux受限子进程
  U->>A: release_id、dataset_id、日期/资金/费用设置
  A->>R: 检查活动订阅与执行位置
  A->>Q: 每账号1项；全局1执行+最多4等待
  Q->>R: 出队后再次核对授权与固定版本
  Q->>X: 服务器登记的行情、策略快照与受限程序
  X-->>Q: 原后端引擎结果
  Q->>R: 完成后再次核对授权
  Q->>Q: 校验结构、去除秘密参数和调试信息
  Q-->>A: 平台计算、unverified
  A-->>U: 脱敏结果与服务端生成记录
~~~

订阅者不能提交源码、替换目标信号、内部指令、秘密参数或行情字节；仅接受固定版本与服务器登记的数据集。作者离线不影响托管行情策略执行。作者自有和明确公开的策略不能用此入口绕回服务器计算。

限制：Linux；每账号一项；全局串行；最多四项等待；排队60秒；子进程 CPU 30秒、墙钟60秒、地址空间1280MiB；输入/输出各16MiB。繁忙429、超时/执行失败明确返回通用错误。普通任务不进入该通道。

这是平台托管执行和资源隔离：防止订阅者直接取得实现，但不对平台运营者保密，也不承诺无法从输出推测策略。此子进程执行固定受限表示，不是任意上传 Python 的通用沙箱，也不等于真实 TEE。

并发锁和队列目前属于进程内状态；后续不能只增加 API 多进程数量就宣称仍满足全局唯一通道，需要共享协调和重新验收。

### 6.2 在线运行生命周期

浏览器每15秒心跳，续45秒需求租约；服务端另有135秒计算互斥锁，两者分别负责“用户还在要求运行”和“同一运行不重叠计算”。

自有/公开行情策略由浏览器提交当前已闭合行情版本的目标信号；保密策略由服务器受限进程计算。服务器校验版本、活动授权、信号时间和目标范围，并负责资金、账户、交易建议、订单确认和对账。

租约到期不再推进。重新打开后从当前数据重新锚定，过时建议失效；可以重跑研究，不补造离线期间的真实订单或成交。现有订单核对是已发生事实的同步，不等于策略继续自动运行。

默认浏览器模式不启动原通用策略定时执行器和后端提醒计算器。账本计划调度与人工交易同步保留；关闭研究网页不等于所有账户维护任务停机。

## 7. 业务模块、开发与授权

### 7.1 用户看到的产品结构

~~~mermaid
flowchart TB
  LOGIN["登录 / 注册 / 会话"] --> SHELL["AtlasShell 统一应用外壳"]
  SHELL --> Q["策略中心"]
  SHELL --> PROOF["Proof 验证"]
  SHELL --> TRADE["策略交易"]
  SHELL --> JOURNAL["资产总览 / 个人账本"]
  Q --> SINGLE["单标的行情与回测"]
  Q --> PORT["组合研究"]
  Q --> LAB["策略实验室\n假设、规则、流程、研究、版本"]
  Q --> MARKET["QuantJudge 市场\n发布、订阅、报告与验证"]
  TRADE --> RUN["版本运行与账户\n信号、建议、模拟记录"]
  TRADE --> MANUAL["限价单预览\n逐笔确认、查询与撤单"]
  JOURNAL --> HOLD["账户资产、定投计划\n投资手记、收益分析"]
  JOURNAL --> OCR["浏览器OCR\n用户复核后入账"]
~~~

完整应用保留统一身份、研究工作台、策略实验室、市场与证据、运行交易、个人账本。具体源码核对见后文索引。逻辑模块共同运行在 FastAPI 内，名称不代表独立服务。

### 7.2 身份与会话

密码使用 scrypt 加盐哈希。会话同时验证签名 Cookie 与服务端登记的session-id哈希、版本和过期时间；Cookie为HttpOnly、SameSite=Strict，HTTPS部署需启用Secure。会话有效期七天；修改密码废止原会话。

注册/登录等入口有来源检查和限速。API根据会话确定用户，索引/对象下载根据该用户鉴权。前端隐藏按钮不构成授权措施。

### 7.3 策略项目与版本

策略项目将假设、标的、周期、基准、目标、研究和发布制品连接起来。更新使用 revision 乐观锁；冻结版本绑定实际定义与制品哈希；改变研究上下文或项目定义不能沿用过期验证结论。

版本发布和订阅以不可变 release 为授权对象。市场上架不等于逻辑公开。非作者新订阅需要作者已设置BKC价格、支付服务就绪以及同用户/版本的confirmed订单；已有订阅保留相应版本权益。取消订阅会停止对应运行；升级版本不会自动继承新的授权。旧 Agent 订阅历史继续可读，旧创建入口410。

策略源码/受限编译指令、私有包和作者签名运行属于不同表示与执行路径：不能把“上传了包”“代码可编辑”“远程 runner 可配置”统一描述成已经支持任意策略的保密历史回测。

### 7.4 云AI和流程约束

用户在当前登录会话配置 DeepSeek或通义接口，当前provider枚举为deepseek/qwen；Key按用户与会话隔离，只驻留单进程内存，超时清理，不写SQLite或研究载荷。进程重启后需要重新配置；横向增加API实例需要处理会话配置归属。

Worker遇到已启用的AI审核阶段，通过消息交给主线程，主线程调用轻量代理，代理调用用户外部模型，再把受限的权重/状态返回Worker。AI响应必须符合结构和请求绑定；失败不能伪装成成功推理。

AI可用于受控代码辅助和交易意图审阅。流程中的确定性risk gate不能绕过；advisory不改变权重，reduce-only不能增仓。模型判断不成为真实成交或密码学证明。

旧执行适配器仍存在local Ollama配置字段和开发接口，但它不属于当前轻量主站部署路径；不能据此把本地模型推理列为新主站资源需求。

### 7.5 个人账本与本地OCR

个人账本是服务端SQLite中的用户JSON状态和revision。读取可物化到期定投；更新经schema/业务校验和CAS乐观锁，冲突409；后台账本计划调度仍保留。账本定投是账务功能，不会自动向交易所下单。

持仓截图经浏览器canvas和锁定版本的Tesseract Worker/Core识别，解析结果逐行让用户复核；图片和原始识别TSV不上传API。确认后的账本数据可以提交服务器。OCR是辅助录入，不是券商账单验真、zkTLS或链上资产证明。

个人账本的即时汇率接口与历史回测换汇版本不同；后者由独立发布器预先准备并固定引用。

### 7.6 账户与真实交易

账户接入分两类：用户会话临时配置的Binance/OKX只读余额连接，明确不能交易；服务端配置并许可的交易账户，用于人工确认现货限价单。二者不因为界面都叫“账户”就共享交易权限。

~~~mermaid
sequenceDiagram
  participant U as 账户所有者
  participant API as 服务端交易API
  participant DB as 订单/资金预留登记
  participant EX as Binance/OKX或测试环境
  U->>API: 请求限价单预览
  API->>API: 账户许可、环境开关、单笔限额、资金约束
  API-->>U: 预览与所需确认内容
  U->>API: 逐笔确认并提交
  API->>DB: owner绑定订单与资金预留
  API->>EX: 提交订单
  EX-->>API: 返回状态或不确定的网络结果
  API->>EX: 按订单身份查询/核对成交
  API->>DB: 保存真实状态、成交和账本映射
  API-->>U: 订单/成交状态；允许查询或撤单
~~~

自动策略或AI不直接触发真实下单。交易总开关默认关闭，实盘还有额外显式许可。提交网络超时不自动重试下单，先查询，避免重复成交。模拟账户的成交与外部核对成交分别记录。

### 7.7 仍由API提供的轻量市场服务

标的搜索、金融/基本面快照、实时联调报价和账本即时汇率仍有服务端接入路径。指标与历史回测移入浏览器，不意味着应用服务器完全不访问上游服务。基本面当前快照不自动成为可回测的历史因子，演示/过期/来源信息必须保留。

独立行情发布器处理公共历史研究数据；以上轻量服务根据各自缓存与用途工作，不能把它们画成“用户每次普通回测重新采集行情”的旧流程。

## 8. Proof、报告与链上信任

### 8.1 证据生成与验证

~~~mermaid
sequenceDiagram
  participant A as 作者本机
  participant D as 固定证明数据集
  participant P as 本机RISC Zero证明器
  participant API as 平台API
  participant V as receipt验证与报告绑定
  participant C as 公共分发/离线复验
  D->>A: 保留原始数据字节及其哈希
  A->>P: 策略、私有witness、固定profile
  P-->>A: 真实receipt与公开journal
  A->>API: 上传receipt与必要报告绑定信息
  API->>V: 真实验真、Image ID/profile、journal绑定
  alt 验证或绑定失败
    V-->>API: 拒绝ZKP状态
  else 验证通过
    V-->>API: 保存真实证明及绑定状态
    API->>C: 导出获准公开报告/receipt或离线包
  end
~~~

作者包装工具是 scripts/author-proof.py，复用已有 prepare/prove 工具和既有证明器，不改变 guest、Image ID 或 profile。证明器不是随 Git 自动附送的原生产物，作者需要匹配平台的可执行工具。

离线包下载本身仍受全局登录检查；包可带走独立复验，路由不要求另交开发者令牌，不等于匿名公开下载接口。普通私有策略包不包含source/witness；只有刻意公开且绑定检查通过的示例才带相应公开验证材料。

普通行情 dataset_id 与历史 Proof 的证明数据集/market_hash 有各自版本契约；新 CDN 分块不能取代或改写旧证明输入。在线验真和离线包复验使用原始证明材料，不能只比较上传摘要就声称密码学验证通过。

普通 QuantJudge 报告保留平台计算的摘要指标、承诺、签名和可选链定位；此报告路径仍可能有有限的服务端汇总重算，不是把所有服务端算术都清零。浏览器结果保存本身不会生成这类平台证据或 ZKP。

ZKP 只覆盖对应 profile/guest 实际执行的陈述。数据哈希匹配不等于行情来源真实；某个整数程序执行证明也不自动覆盖所有浏览器浮点指标、任意 AI 行为和真实交易。

### 8.2 三个独立信任维度

| 维度 | 示例 | 不能推出的结论 |
| --- | --- | --- |
| 计算来源 | browser / server_private | 平台算过不等于有ZKP |
| 证明状态 | unverified / 对应receipt真实验真且报告绑定通过 | 上传哈希、签名或用户声明不能升级为ZKP |
| 事实性质 | 历史研究 / 模拟 / 建议 / 经外部服务核对的真实成交 | 回测成交不能写成真实交易事实 |

浏览器上传接口禁止客户端指定 owner、execution_location、proof_status、verified、receipt 等可信字段。平台执行的保密回测同样默认为 unverified。

### 8.3 链侧职责

主站通过 JSON-RPC 访问 Supervisor；Supervisor 独立使用 MySQL 和链状态。链用于支付核对、报告/版本承诺定位等，不存放每次回测的全量行情、秘密源码和全部用户账本。

链上交易成功还必须匹配预期载荷和业务对象；普通报告、ZKP、BKC 使用各自版本化绑定。支付订单绑定链身份，不能只信任浏览器提交的交易哈希，也不能用重新创建的临时开发链恢复原付款订单。

~~~mermaid
sequenceDiagram
  participant U as 用户外部钱包
  participant A as BKC订单API
  participant S as Supervisor测试链RPC
  participant R as 版本订阅登记
  U->>A: 为固定release创建订阅订单
  A->>S: 核对chain和genesis身份
  A-->>U: 绑定版本哈希/价格/收款方/载荷的待签交易
  U->>U: 本机钱包签名，不交付私钥
  U->>A: 提交签好的raw transaction
  A->>A: 解码核对from/to/value/data/chainId并登记
  A->>S: 广播并查询交易、receipt、规范区块
  S-->>A: 链上确认事实
  A->>A: 校验金额、载荷、订单身份和防复用
  A->>R: confirmed后授予对应release订阅
~~~

当前Supervisor/MySQL部署属于chain ID 1051的单节点测试链，不是生产共识或真实资金网络。API转发外部钱包签好的交易，不要求把用户钱包私钥交给平台。当前主站的链锚定记录承诺/哈希，不在链上重新运行zkVM验真。

普通报告使用ATLASQJ1类绑定，ZKP锚定使用对应ATLASZK2绑定，支付使用BKC订单载荷。它们是不同协议，不可用“某笔交易成功”替代业务验证。

### 8.4 独立实验/兼容执行能力

| 能力 | 已有实现 | 当前默认边界 |
| --- | --- | --- |
| 托管受限策略 | Linux子进程、固定版本、配额、脱敏 | 当前保密订阅回测/行情信号路径；非TEE |
| 开发者私有Python包 | 包校验/加密、Docker/gVisor执行适配、单槽限制 | 独立开发者接口，需显式配置；结果不自带ZK或TEE等级 |
| 作者签名runner | 版本/代码承诺、公钥、签名、nonce和顺序校验 | 作者需提供相应签名信号；不保证其离线后继续产生新信号，不能与平台托管策略混同 |
| Nitro证明通道 | challenge、真实证书/PCR校验实现 | execution_available=false；真实Nitro/KMS云端E2E未验收，不证明策略绩效 |
| 本地模型适配 | 保留实验执行接口 | 当前主站不部署模型推理 |
| 旧云Proof队列 | 历史订单/输入/profile/恢复实现 | 仅显式legacy和generation开关才启用；新流程使用作者本机 |

新架构关闭服务器 Proof 建单和自动生成；历史订单、证明、profile、Image ID 继续保留。迁移前发现已付款/已提交交易而未完成的任务，必须先处理，不能直接停掉旧执行器遗留付费工作。

### 8.5 可选链上Groth16验证工具链

仓库另有一条真实密码学验证合约路径，与当前主站默认的报告哈希锚定分开：

~~~mermaid
flowchart LR
  R["原始RISC Zero receipt"] --> E["作者本机ethereum-export\n先验原receipt，再压缩为Groth16"]
  E --> J["seal + 原样journal\n本地复验；尚未链上确认"]
  J --> T["独立部署/提交脚本\n外部钱包签名"]
  T --> G["AtlasReceiptRegistry\n固定imageId、SHA journal、防重复"]
  G --> V["RiscZeroGroth16Verifier\nEVM配对验证"]
~~~

[contracts/README.md](../contracts/README.md)记录它曾在独立本地42516验收链部署，使用真实策略receipt验证。该历史环境与当前主站/新启动器的链身份、状态及部署地址不同；本轮未重连复验，也未部署新合约。

当前主站报告/BKC接口没有调用该Registry的ABI或submit(seal,journal)。这是一条保留的可选工具链，不能因为仓库含有验证合约就将所有“已锚定”报告标成“链上ZKP已验真”。合约只证明固定guest对应的journal陈述，不解析完整策略生命周期，不证明实盘来源。

## 9. 接口分区

| 接口族 | 责任与典型入口 |
| --- | --- |
| 会话与账本 | /api/session、register/login/logout/change-password、/api/ledger、/api/fx |
| 浏览器计算 | /api/v1/compute/identity、capabilities、compile、runs、ai-review |
| 公共数据 | /api/v1/market/manifest、market/datasets/{id}、market/files/{sha}.json |
| 私密计算与租约 | /api/v1/compute/private-backtests、compute/runtime/{id}/heartbeat、signal |
| 提醒记录 | /api/v1/alerts、compute/alerts/{id}/observations、notifications |
| 历史结果与研究 | /api/v1/runs、research/jobs/{id}；保留读取旧数据 |
| 策略生命周期 | /api/v1/strategy-projects、strategy-releases、strategy-subscriptions |
| 账户与运行 | /api/v1/exchange-account只读连接；/api/v1/trading/accounts和runs；/api/v1/trading人工订单接口 |
| 市场与证据 | /api/v1/quantjudge/agents、reports、zkp、zk-proofs |
| 公共制品 | /api/v1/public-artifacts/{sha}.json 或 .r0，公开白名单 |

默认 browser 模式下，旧 POST backtests、portfolio/backtests、research/jobs、alerts/evaluate 与旧 GET market/bars 返回410兼容错误。历史结果、历史研究状态和证明读取继续保留；显式 legacy 模式是兼容恢复路径，不是运行时自动回退。

## 10. 部署拓扑与真实状态

### 10.1 目标部署关系

~~~mermaid
flowchart TB
  U["用户浏览器"] --> TLS["HTTPS入口 / 可信反向代理"]
  TLS --> WEB["Web容器：Nginx\n静态构建与API代理"]
  WEB --> API["API容器：FastAPI\nSQLite与保密子进程"]
  API <--> DATA[("atlas-data持久卷\n业务DB、对象、证明、密钥材料")]
  API --> SUP["Supervisor容器\n内部RPC"]
  SUP <--> STATE[("supervisor-state卷")]
  SUP <--> DB["MySQL容器\n内部专用网络"]
  DB <--> DBV[("supervisor-mysql卷")]
  JOB["独立采集发布进程/计划任务"] --> PUB[("公共对象存储")]
  PUB --> CDN["CDN"]
  CDN --> U
  JOB -->|"当前实现需访问清单登记和对象根"| DATA
~~~

基础 Compose 部署 Web/API；chain overlay 增加 Supervisor/MySQL；browser overlay 设置浏览器模式、停用服务器 Proof 生成并增加独立行情发布器。

当前发布器通过本地数据库/对象根登记，通常需要与对应持久化协调；尚未提供任意远程发布器直接调用中心清单登记 API 的完整方案。静态前端可以再放CDN，但当前 Compose 仍由 Nginx 提供。

API/链/数据库不直接发布公网端口，Web 默认只绑定宿主127.0.0.1，再由受信任入口处理HTTPS。容器采用只读根、权限收紧、tmpfs、健康检查和有界日志；不能把这些配置当作真实 TEE 或完整外部攻防验收。

多个 Compose 文件顺序会覆盖资源设置：旧 chain overlay 仍包含历史 API 6GiB 配置，不能叠上文件后就宣称实际总预算是2GiB。运行限额以最终解析的配置和实际容器为准。

### 10.2 r23 本机验收

| 项目 | 状态 |
| --- | --- |
| 本机 Docker | Web、API、独立行情发布器、Supervisor 和 MySQL 通过更新验收，连续观察 30 分钟 |
| 浏览器和容量 | Chromium、Firefox、WebKit 各 138 个用例通过。50 个独立 Chromium 会话持续一小时及恢复验收通过 |
| 数据和 Proof | 独立环境验收公开行情、重启、备份恢复以及现有 v2 Proof 的密码学验真 |
| 外部存储和独立执行环境 | 默认从本机提供公共对象。真实外部 CDN、TEE、实盘和真实资金未纳入 r23 本机验收 |

本机正式容量验收使用 API 与 Web 合计 4 CPU / 4 GiB。链、MySQL、行情发布器和浏览器压力端单独计量。详细结果见[r23 验收报告](testing/comprehensive-20261108/FOLLOWUP.md)。

## 11. 安全边界与恢复约束

- 用户身份来自服务端验证会话；写请求校验来源，业务表按owner隔离。前端传owner不能改变记录归属。
- 平台知道托管保密策略实现；订阅者拿不到实现。离线作者证明的私有witness留在作者设备，两种保密边界不同。
- 用户云模型配置只在登录会话内存中，不进Worker、IndexedDB、镜像或导出；不在主站运行模型推理。
- 公共文件通过内容哈希和白名单分发；私有结果鉴权、no-store。内容地址不能代替权限。
- 业务数据库、私有包、签名/加密材料、原receipt需要成套保护；不能将.data或.artifacts整体当可丢弃缓存。
- 业务SQLite、链状态和MySQL没有跨库崩溃原子性承诺。冷备恢复需保护一致性与创世身份，不能只恢复一个数据库就宣称支付恢复。
- 应用升级需要检查未完成付费任务、备份、数据、权限和证明兼容，并保留可验证的回退。

## 12. 源码导航与核对入口

| 模块 | 主要源码 |
| --- | --- |
| 前端外壳与工作区 | [AtlasShell.tsx](../frontend/src/AtlasShell.tsx)、[components](../frontend/src/components)、[journal](../frontend/src/journal) |
| 计算协议与任务 | [client.ts](../frontend/src/compute/client.ts)、[worker.ts](../frontend/src/compute/worker.ts)、[persistence.ts](../frontend/src/compute/persistence.ts) |
| 市场数据与浏览器算法 | [market.ts](../frontend/src/compute/market.ts)、[compute目录](../frontend/src/compute) |
| 应用装配与认证 | [main.py](../backend/app/main.py)、[auth.py](../backend/app/auth.py) |
| 能力、记录与租约 | [browser_compute.py](../backend/app/browser_compute.py)、[browser_runtime.py](../backend/app/browser_runtime.py)、[storage.py](../backend/app/storage.py) |
| 发布器与对象 | [publish_market.py](../backend/app/data/publish_market.py)、[market_publication.py](../backend/app/market_publication.py)、[compute_objects.py](../backend/app/compute_objects.py)、[public_artifacts.py](../backend/app/public_artifacts.py) |
| 受限保密执行 | [private_compute.py](../backend/app/private_compute.py)、[private_compute_worker.py](../backend/app/private_compute_worker.py) |
| 版本、订阅、运行 | [strategy_runtime.py](../backend/app/strategy_runtime.py)、[strategy_projects.py](../backend/app/strategy_projects.py) |
| Proof与作者工具 | [author-proof.py](../scripts/author-proof.py)、[zkp.py](../backend/app/zkp.py)、[zkp_bindings.py](../backend/app/zkp_bindings.py)、[zkp_bundle.py](../backend/app/zkp_bundle.py)、[zkvm](../strategy/zkvm) |
| 可选链上验证工具 | [AtlasReceiptRegistry.sol](../contracts/src/AtlasReceiptRegistry.sol)、[Groth16 verifier](../contracts/vendor/risc0/groth16/RiscZeroGroth16Verifier.sol)、[ethereum-export](../strategy/zkvm/ethereum-export)、[合约历史验收](../contracts/README.md) |
| 市场、支付与链 | [quantjudge.py](../backend/app/quantjudge.py)、[bkc_payments.py](../backend/app/bkc_payments.py)、[supervisor_client.py](../backend/app/supervisor_client.py)、[supervisor-src](../contracts/supervisor-src) |
| 云模型、交易与账本 | [cloud_ai.py](../backend/app/cloud_ai.py)、[trading.py](../backend/app/trading.py)、[journal](../backend/app/journal) |
| 部署 | [compose.yaml](../compose.yaml)、[compose.browser.yaml](../compose.browser.yaml)、[compose.chain.yaml](../compose.chain.yaml)、[nginx.conf](../deploy/nginx.conf) |

补充说明见[浏览器计算与部署](BROWSER_COMPUTE.md)和[隔离验收](testing/comprehensive-20261108/FOLLOWUP.md)。旧架构保留服务器研究、Proof 生成和后台提醒的兼容资料。
