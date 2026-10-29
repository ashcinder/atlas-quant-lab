# QuantJudge 证明与 Supervisor 接入

QuantJudge 是 Atlas Quant Lab 的量化策略 / AI Agent 展示、跑分与订阅市场。说明于2026-10-29按 `672e8b8` 核对。证据需区分平台验算、真正的zkVM执行证明与链上存证。当前界面仍有 `LIVE/实盘类报告` 标签，它来自报告自报分类，不是交易所来源或真实收益已验证的保证；应以实际核验结论为准。

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

当前榜单使用 `performance_score` 业绩分，证据等级单列，不因ZKP/链上存证而增加业绩。旧 `score`（`legacy_evidence_v1`）保留兼容算法，其中ZK加分仅识别真正的 `evidence_level=zk_verified`，不是当前业绩排名依据。用户填写proof类型或外部摘要不能制造该字段。

`report_type=live` 仅为报告类型，核验并不证明交易所数据来源或完整实盘收益；`verification_claims`、receipt完整性、具体profile和链状态必须分别查看。

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

- 项目已包含 `contracts/supervisor-src/` 的脱敏加固源码与隔离链runner；旧外部 `Supervisor/` 目录不是当前交付入口。API通过JSON-RPC访问独立链进程。
- 默认 RPC 为 `http://127.0.0.1:42515`，环境变量为 `QUANTJUDGE_SUPERVISOR_RPC_URL`。
- 期望链 ID 为 `1051` (`0x41b`)。
- 只读取 `eth_chainId`、`eth_blockNumber`、交易和回执；写入只转发外部钱包签名的原始交易。
- 浏览器钱包签名，后端不保管钱包私钥；本机账户生成工具仅用于隔离测试。BKC订单额外绑定创世哈希，持久链与一次性开发链不可混用，见 [部署指南](DEPLOYMENT.md#supervisor与付款恢复)。

传统报告沿用 `ATLASQJ1 || receipt_hash`。ZKP 报告使用版本化的 `ATLASZK2` payload；具体字段见 [ZKP.md](ZKP.md)。当前版本/报告摘要存证流程不执行RISC Zero链上验证。历史隔离42516链另有真实Groth16合约验收，见 [合约说明](../contracts/README.md)；不能推为所有网络或现有BKC存证交易均执行了该合约。链确认也不等于来源认证或去中心化共识已验收。

## 其他 QuantJudge API

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/v1/quantjudge/subscriptions` | 只读查看旧Agent订阅历史 |
| GET / POST | `/api/v1/quantjudge/agents` | 查询 / 发布 Agent |
| POST | `/api/v1/quantjudge/agents/{id}/reports` | 发布平台验算报告（非 ZKP） |
| GET | `/api/v1/quantjudge/reports/{id}/verify` | 验证展示、平台签名、ZKP 文件绑定与链状态 |
| POST | `/api/v1/quantjudge/agents/{id}/subscriptions` | 已停用，固定410；当前具体版本需BKC授权 |
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
