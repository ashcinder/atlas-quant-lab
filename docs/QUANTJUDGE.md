# QuantJudge 证明与 Supervisor 接入

QuantJudge 是 Atlas Quant Lab 中的量化策略 / AI Agent 展示、跑分与订阅市场。它实现“隐藏策略和原始决策，公开可验证业绩”的产品边界，同时不对当前证明强度做夸大声明。

## 公开层级

| 层 | 内容 | 默认状态 | 平台处理 |
|---|---|---|---|
| 1 | 策略源码、Agent 参数、提示词 | 隐藏 | 浏览器本地加盐 SHA-256，服务器只接收承诺哈希 |
| 2 | 原始买卖、选股、择时与仓位决策 | 隐藏 | 只接收每条决策的哈希承诺，计算 Merkle 根后丢弃列表 |
| 3 | 收益、回撤、波动、Sharpe 与降采样收益曲线 | 公开 | 后端从一次性净值序列重算，并签发不可变回执 |

原始净值序列只在请求内存中参与重算，持久化层只保存已公开的降采样收益曲线。

## 回执结构

每份报告生成 `atlas.quantjudge.receipt.v1` 规范化 JSON，包含：

- Agent ID 与策略承诺；
- 统计周期、报告类型和平台重算指标；
- 决策数量、决策 Merkle 根和市场数据哈希；
- 上一份回执哈希，形成 Agent 级别的追加链；
- 外部 ZK / TEE 证明摘要（可选）。

规范化 JSON 还包含公开收益曲线的 SHA-256，经 SHA-256 得到 `receipt_hash`，再由平台 Ed25519 密钥签名。验真时会逐字段比对已签名载荷与展示记录，避免“签名有效但展示值被改”。公钥和 key ID 通过 `/api/v1/quantjudge/overview` 公开。开发者凭证仅在创建 Agent 时返回一次，数据库中只保存其 SHA-256。

## 证明等级

UI 中的证据链不将不同强度的保证混为一谈：

1. **承诺完整性**：策略承诺、决策 Merkle 根和前序回执链存在。
2. **平台验算**：收益指标由平台重算，回执哈希与 Ed25519 签名通过。这是可公开验签的中心化证明，不是 ZK 证明。
3. **Supervisor 链上确认**：交易状态成功，且 input 必须精确等于 `ATLASQJ1` 的 ASCII 字节加 32 字节 `receipt_hash`。
4. **ZK / TEE 证明**：API 允许登记证明摘要和 verifier 引用，但在实际 verifier 未配置前始终显示“未验证”。

## Supervisor 适配边界

- Supervisor 源码目录被项目根 `.gitignore` 排除，Atlas 不导入、修改或复制其代码与配置。
- 默认 RPC：`http://127.0.0.1:42515`；环境变量：`QUANTJUDGE_SUPERVISOR_RPC_URL`。
- 期望链 ID：`1051` (`0x41b`)。
- 读取方法：`eth_chainId`、`eth_blockNumber`、`eth_getTransactionByHash`、`eth_getTransactionReceipt`。
- 写入方法：只向 `eth_sendRawTransaction` 转发外部钱包已签名原始交易。Atlas 后端不生成、导入或保管区块链私钥。

锚定 input 的构造规则：

```text
0x + hex("ATLASQJ1") + receipt_hash
```

对于已由外部钱包提交的交易，可使用 `PUT /api/v1/quantjudge/reports/{report_id}/chain-transaction` 附加交易哈希；对于已签名原始交易，使用 `POST /api/v1/quantjudge/reports/{report_id}/anchor`。两者都需要 `X-Developer-Token`。

## API 概览

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1/quantjudge/overview` | 市场概览与验签公钥 |
| GET / POST | `/api/v1/quantjudge/agents` | 查询 / 发布 Agent |
| POST | `/api/v1/quantjudge/agents/{id}/reports` | 提交净值、决策承诺与业绩报告 |
| GET | `/api/v1/quantjudge/reports/{id}/verify` | 重算回执完整性并查询链上状态 |
| POST | `/api/v1/quantjudge/agents/{id}/subscriptions` | 建立沙盒或外部支付引用订阅 |
| GET | `/api/v1/quantjudge/chain/status` | Supervisor 连接、链 ID 与区块高度 |

FastAPI 的完整请求模型与交互调试页位于 `http://127.0.0.1:8000/api/docs`。

## 当前局限与上线前清单

- 默认订阅是明确标记的本地沙盒账本，不会发生真实扣款。接入支付后应将异步 webhook、幂等键、退款与对账纳入状态机。
- 当前项目是个人本地工作台，Agent 写入使用一次性开发者凭证保护，演示 Agent 强制只读。对公网开放前还必须接入真实账户、MFA、组织权限、全局限流、审计日志与凭证撤销。
- 当前 Ed25519 私钥位于本地 `.data` 且权限为 `0600`。多实例生产环境应迁移到 KMS/HSM，并实施密钥轮换和旧公钥档案。
- 平台重算仍依赖平台作为可信验算方。要去中心化地证明“隐藏决策确实产生公开收益”，需要针对固定执行语义实现 ZK 电路或可验证 TEE 执行器，不能只用哈希和签名替代。
- 公开收益曲线仍可能泄露部分风格特征。高敏感策略应进一步限制公开频率，并在 ZK/TEE 内输出预先约定的聚合统计。
