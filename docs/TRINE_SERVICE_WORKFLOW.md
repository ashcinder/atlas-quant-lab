# Trine 账户、BKC 支付与证明服务

## 用户流程

1. 顶栏设置 → Supervisor 账户与私钥：输入账户私钥和本地解锁密码（至少12字符），加密保存。私钥不会发送到后端；切换用户、退出登录或15分钟后锁定。刷新需重新解锁。
2. 顶栏及资产总览显示配置账户的 BKC 链上余额；未连接时不显示虚构余额。
3. 模板、图形化或代码策略保存为不可变版本后，可以直接公开。版本初始显示「无 ZKP 验证」。在策略市场的「可运行策略」中设置该版本 BKC 订阅价格，所有新订阅均使用 BKC，未设价不能免费领取。作者使用自己的版本不额外向自己付费。旧授权不会追溯扣款。
4. 订阅时核对金额与收款地址，点击确认支付。浏览器签名，后端仅转发与订单一致的已签名交易。链上成功回执核对账户、金额、收款、订单数据、创世块和规范区块后才授予权限。等待或失败均不授予权限。网络中断保留原交易哈希，只重播同一签名，不再次付款。
5. 行情与回测 → 策略来源：选择自己开发或已订阅的版本；服务端再次检查权限并使用不可变快照，不能通过修改浏览器传参偷换策略。
6. 受限 Python 版本可申请「云端生成 Proof」。选择 BTC/ETH/SOL 日 K 与 UTC 区间，确认服务器可读取程序，创建订单并支付 BKC。付费确认后进入排队/生成中/已验证；失败保留任务与原支付。支持3–256根K线。模板/图形规则未自动转换成等价的 zkVM 程序，不能将普通回测冒充为执行证明。

## 服务端配置

- `QUANTJUDGE_SUPERVISOR_RPC_URL`：实际 Supervisor JSON-RPC 地址；链 ID 必须为1051。不能因链 ID 相同就把不同创世块视为同一网络。
- `TRINE_PROOF_PRICE_BKC`：每次证明的正数 BKC 价格。
- `TRINE_PROOF_RECIPIENT`：服务方收款地址。
- `strategy/zkvm/target/release/atlas-zkvm`：与登记 image ID 一致的原生执行器。
- 运行环境需要 Python 虚拟环境、Node.js 和 `contracts/node_modules`（ethers 用于检查已签名交易）。Linux 云主机必须构建 Linux 版证明执行器；Mac 二进制不可直接上传运行。

配置缺失时，服务禁止创建付费任务。服务随后端启动一个持久化队列工作器，文件锁防止多个进程并发证明；任务在 SQLite 中持久化，输入保存在服务端受限目录。请保护服务器及备份，因为云端生成意味着服务器可以读取策略程序和 witness，不能宣称服务器零知晓。

## 本地工具完整保留

`strategy/zkvm/`、`scripts/prepare-zk-witness.py`、`scripts/prove-private-program.py`、`scripts/verify-proof-bundle.py` 都保留。云端工作器复用原生证明/验证流程；高级用户仍可按 CODE_TO_PROOF_WALKTHROUGH.md 在自己的设备生成和验证 Proof。

## 验证范围

密码学证明绑定编译后的有界程序、已登记历史数据根、区间、费用和收益；不证明市场数据来自交易所的密码学真实性，不是 zkTLS，也不是实盘盈利保证。旧版仅登记身份的沙盒订阅入口关闭，真实授权以具体可运行版本的 BKC 订单为准。

## 容器运行

部署后端镜像已包含支付交易解码依赖及证明脚本。Linux 上先构建并检查固定 image ID 的原生执行器，再设置 `TRINE_LINUX_ZKVM_BINARY` 为其绝对路径，使用 `docker compose -f compose.yaml -f compose.zkvm.yaml up -d --build`。覆盖文件为证明进程提供4核/8GB上限，并只读挂载执行器；它不包含本机数据库、客户私钥或 witness。本轮未完成远端 SSH 部署，容器在目标 Linux 机器上仍需构建验收。

## 恢复与支付核验（2026-09-17）

- 后台启动收费前检查本机 zkVM 执行器与登记 image ID 是否一致。
- 新订阅在支付模块未初始化时拒绝授权。版本存证也使用设置中的 Supervisor 签名账户，无需 MetaMask。
- Proof 失败保留原付款供重试；当前不提供自动退款。
- 使用真实原生 receipt 验证了登记后中断的恢复：恢复已有 Proof 和报告，不重复发布；损坏 receipt、错误 image ID、重复登记均被拒绝。
- 本次原生 Proof 验收的支付为测试夹具，不能作为真实 BKC 扣款验收。

## 2026-09-18 实际验收与市场界面

- 已将未验证运行版本改为与 ZKP 报告一致的六列紧凑行，订阅、Proof、版本指纹和链上记录在右侧展示。
- 发布窗口使用原生 modal dialog 顶层，支持 Escape 关闭与焦点恢复，避免编辑器覆盖。
- `POST /strategy-releases/{id}/proof-anchor-order` 重新验证原生 receipt 后，将版本哈希、Proof 哈希、image ID、公开 journal 与其哈希写入交易数据。`GET /strategy-releases/{id}/anchors` 展示已确认记录。
- 这是公开结果与 Proof 摘要存证，**不是链上合约执行 ZKP 验证**；原始 receipt 保留在原 Proof 下载/验证接口。本地证明程序继续保留。
- 隔离 Supervisor 42516 实际确认：区块 18，交易 `0x5b437e6d09ab7e2c1694f313df9d1ab11d0cf5ec4c5615a5111bf8534c137190`。原始估算漏算 calldata 导致第一笔失败；保留失败记录，修正签名前 intrinsic gas 下限后，另一个测试签名账户成功存证。
- 实际付费证明 `qzp_c79ddd087e574ab89d` 独立复核通过，生成约 240 秒；BKC 订阅成功，Binance demo 有实际成交回执。行情过期导致暂停后，刷新成功、账户同步并恢复运行。运行仍依赖行情供应商可用性，不会使用过期行情强行成交。
- 完整验收 ID 保存在 `TRINE_E2E_LIVE_STATUS.json`；只读复核命令：`backend/.venv/bin/python scripts/check-trine-e2e.py`。
