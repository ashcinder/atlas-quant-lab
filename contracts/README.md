# Atlas 链上 ZKP 验证

已在隔离的本地 Supervisor（链ID1051，RPC `http://127.0.0.1:42516`）部署并验收。它与原42515实例拥有不同数据库/状态，不能仅凭相同chainId混用部署地址。

## 合约

- 官方 `RiscZeroGroth16Verifier`：`0xc375c2a1925377ef55149bb7a3c54e35ecd2d5bd`
- `AtlasReceiptRegistry`：`0x7069968d85263366c69e7a61390f1b40ac59c160`
- 真实策略证明验证交易：`0xf0625b5427646e4c67418796797c04cb0915fa4aaf4f4417f2767a01b1d8e11e`，区块6。

验收见 `docs/SUPERVISOR_ZKP_ACCEPTANCE.json`，部署回执与运行字节码哈希见 `docs/SUPERVISOR_ISOLATED_ZKP_DEPLOYMENT.json`。真实receipt转换出的260字节seal在合约中调用BN254配对验证；不是平台签名，也不是仅锚定哈希。

Registry固定guest image，校验原始journal摘要，记录已验证digest并拒绝重复提交。没有管理员跳过证明入口。当前journal是回测guest输出；合约不解析策略ID，不证明实盘来源，也未实现按账户连续报告的状态机。

## 构建和验证

```bash
cd contracts
npm ci
npm run compile
ATLAS_SUPERVISOR_HTTP=http://127.0.0.1:56742 node scripts/supervisor-account.mjs
ATLAS_SUPERVISOR_RPC=http://127.0.0.1:42516 node scripts/deploy-supervisor.mjs
ATLAS_SUPERVISOR_RPC=http://127.0.0.1:42516 node scripts/verify-supervisor.mjs artifacts/atlas-groth16.json
```

本次验收的公开Groth16输入保存为 `contracts/atlas-acceptance-groth16.json`。已有部署可用 `node scripts/check-deployment.mjs` 再次核对字节码哈希、成功回执、精确调用内容和登记状态，无需私钥，不重新提交交易。

领币只执行一次，日额度耗尽不能绕过。`verify-supervisor`适用于尚未提交的journal；重复运行会按预期拒绝，不能重复生成成功报告。

转换工具是独立host，不改变guest或Python/AI执行语义。它先验证原receipt，再使用本地prover压缩成Groth16，独立验证压缩receipt，并确认journal字节相同。使用真实Docker证明镜像，禁用dev mode：

```bash
cargo build --release --locked --manifest-path strategy/zkvm/ethereum-export/Cargo.toml
RISC0_PROVER=local RISC0_DEV_MODE=0 DOCKER_DEFAULT_PLATFORM=linux/amd64 \
  strategy/zkvm/ethereum-export/target/release/atlas-ethereum-export \
  /absolute/receipt.r0 02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4 \
  /absolute/new-ethereum.json
```

本轮构建复用了 `CARGO_TARGET_DIR=strategy/zkvm/target`，因此可执行文件实际位于该目录。输出文件必须不存在；内容为公开seal/journal，不含私有策略witness。

## Supervisor 必要修正和隔离

原实例部署实际返回HTTP500，现有状态根对应trie/reader不可读；源码忽略初始化错误，导致空指针。未重置、覆写或迁移原链数据。

隔离实例目录：`~/.local/share/atlas-supervisor-zkp-isolated`。数据库：`atlas_zkp_isolated_20260913`。原有表结构和config复制用于初始化；未复制历史账户/成交/证明。新链水龙头创世分配1000测试BKC到源码固定水龙头地址，部署账户通过正常签名claim领取1BKC。不是原链充值或真实资产。

对隔离源码作出的功能修正：

1. RPC42516、HTTP56742、内部TCP38801/56744，保留原实例端口。
2. `vm/contracts.go` 的 `activePrecompiledContracts` 原本硬编码Homestead，改为已有Byzantium集合，启用0x06/0x07/0x08。这是测试链执行规则变更；现有网络升级需要所有节点一致采用并明确激活高度，不能热改生产共识。
3. `eth_sendRawTransaction` 路由原本把nil结果当error输出，改为JSON-RPC -32000和真实错误消息。负例的结果为明确execution reverted，链没有保留其失败回执，因此验收中不伪造负例交易哈希。

Supervisor的 `eth_call` 实现会触碰状态/区块，和标准Ethereum只读调用不同。本轮只在隔离实例执行此类验收。该链仍需修复只读语义、失败交易记账/nonce、启动状态检查和共识部署治理，才能考虑生产安全。

前端原Supervisor配置仍指向42515；本轮合约验收没有伪装成旧界面的摘要锚定确认。公开验收记录明确标记独立网络。

## 依赖来源

`vendor/risc0`来自RISC Zero官方仓库v3.0.1，commit `365e7b2db4f620fa256580c27558d2623362b9ae`，原文件保留许可证声明。其中Groth16 verifier为GPL-3.0，其余按文件头许可。OpenZeppelin5.2.0、Solidity0.8.28、编译目标Paris，依赖锁定于package-lock。未使用mock verifier。官方测试向量仅用于先期兼容性测试；最终验收使用项目自己的策略receipt。

本轮是开发验收，不替代合约安全审计或生产部署。完整实盘协议见 `docs/LIVE_PROFIT_PROOF_DESIGN.md`；Python/AI评估见 `docs/PYTHON_AI_PROOF_FEASIBILITY.md`。

官方来源：[RISC Zero Ethereum v3.0.1](https://github.com/risc0/risc0-ethereum/tree/v3.0.1)、[验证合约](https://github.com/risc0/risc0-ethereum/blob/v3.0.1/contracts/src/groth16/RiscZeroGroth16Verifier.sol)。隔离实例改动保存在 `supervisor-isolated.patch`，对应来源/结果哈希在 `supervisor-source-manifest.json`；没有修改项目内原Supervisor源码。
