# QuantJudge 证明与 Supervisor 接入

QuantJudge 是 Atlas Quant Lab 的量化策略 / AI Agent 展示、跑分与订阅市场。它把证据分为平台验算与真正的 zkVM 执行证明，UI 和 API 不把两者混为一谈。

## 隐私层级

| 层 | 内容 | 默认状态 | ZKP 报告处理 |
|---|---|---|---|
| 1 | 策略源码、参数、提示词、salt | 隐藏 | 仅存在于本地 witness，服务器接收承诺 |
| 2 | 买卖、选股、择时与仓位决策 | 隐藏 | guest 计算逐条承诺并公开 Merkle 根 |
| 3 | 收益、回撤、波动、Sharpe、降采样曲线 | 公开 | guest 输出 journal，后端验证 receipt 后直接发布 |

非 ZKP 报告仍可由平台从一次性净值序列重算并签发 `atlas.quantjudge.receipt.v1`。ZKP 报告使用 `atlas.quantjudge.receipt.v2`，来源是已验证的公开 journal，不能由普通报告接口或浏览器字段创建。

## 证据等级

1. **浏览器承诺 / 平台报告**：策略承诺、平台重算、Ed25519 回执有效；这是中心化可验签报告，不是 ZKP。
2. **zkVM 已验证**：RISC Zero receipt 对固定 image ID 验证通过，journal 与 Agent、行情、成本、指标、曲线和回执链完全绑定。
3. **Supervisor 已锚定**：链、交易状态和 input 精确匹配。ZKP 报告锚定 receipt、proof、public-input 与 nullifier 四个哈希。

跑分只给真正的 `evidence_level=zk_verified` 证明加 ZK 证据分。用户提交的 proof 类型说明或外部摘要不能影响该字段。

## ZKP API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1/quantjudge/zkp/profiles` | 获取固定 profile、image ID、支持范围与 verifier 状态 |
| POST | `/api/v1/quantjudge/zkp/market-datasets` | 从平台真实行情注册规范化数据集 |
| GET | `/api/v1/quantjudge/zkp/market-datasets/{hash}` | 下载按哈希锁定的公开 witness 行情 |
| POST | `/api/v1/quantjudge/agents/{id}/zk-proofs` | 上传并验证 receipt；需要开发者凭证 |
| GET | `/api/v1/quantjudge/zk-proofs/{id}` | 获取证明元数据和公开 journal |
| GET | `/api/v1/quantjudge/zk-proofs/{id}/receipt` | 下载 receipt，供独立验证 |
| POST | `/api/v1/quantjudge/agents/{id}/reports/zkp` | 原子消费证明并发布 ZKP 报告 |

完整协议、数据库边界与命令见 [ZKP.md](ZKP.md)。

## Supervisor 适配边界

- `Supervisor/` 被根目录 `.gitignore` 排除；Atlas 不导入、修改或复制其代码与配置。
- 默认 RPC 为 `http://127.0.0.1:42515`，环境变量为 `QUANTJUDGE_SUPERVISOR_RPC_URL`。
- 期望链 ID 为 `1051` (`0x41b`)。
- 只读取 `eth_chainId`、`eth_blockNumber`、交易和回执；写入只转发外部钱包签名的原始交易。
- Atlas 不生成、导入或保管链上私钥。

传统报告沿用 `ATLASQJ1 || receipt_hash`。ZKP 报告使用版本化的 `ATLASZK2` payload；具体字段见 [ZKP.md](ZKP.md)。Supervisor 当前负责不可篡改锚定，不在链上执行 RISC Zero verifier。

## 其他 QuantJudge API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET / POST | `/api/v1/quantjudge/agents` | 查询 / 发布 Agent |
| POST | `/api/v1/quantjudge/agents/{id}/reports` | 发布平台验算报告（非 ZKP） |
| GET | `/api/v1/quantjudge/reports/{id}/verify` | 验证展示、平台签名、ZKP 文件绑定与链状态 |
| POST | `/api/v1/quantjudge/agents/{id}/subscriptions` | 建立沙盒或外部支付引用订阅 |
| GET | `/api/v1/quantjudge/chain/status` | Supervisor 连接、链 ID 与区块高度 |
| GET / POST | `/api/v1/quantjudge/agents/{id}/packages` | 查询 / 上传加密 `.qstrategy` 包 |
| POST | `/api/v1/quantjudge/studio/workflows/validate` | 验证 AI 权限、DAG、审计路径与硬风控 |

## 上线前要求

- 多租户公网版本仍需真实账户、MFA、组织权限、限流、审计、凭证撤销与支付对账。
- 平台 Ed25519 私钥需迁移到 KMS/HSM 并保留轮换公钥档案。
- 市场数据注册需要提供方签名或独立受证明的摄取流水线；当前证明只保证对已注册数据的计算正确。
- 每个新增策略或 AI 执行环境都必须发布独立、可复现、经审查的 profile/image，不能复用 SMA profile 名义。
- 公布收益曲线本身可能泄露风格特征；高敏策略应降低采样频率并预先约定公开统计。

FastAPI 交互文档位于 `http://127.0.0.1:8000/api/docs`。
