# 私密策略执行与证明：交付边界

更新：2026-09-08。**研究执行、硬件证明和零知识证明是三条不同的能力，不可相互替代。** 当前不是“上传任意 Python 即可对平台保密并自动生成 ZKP”的产品。

## 能力矩阵

| 能力 | 当前实现 | 尚不包含 |
| --- | --- | --- |
| Python 隔离研究 | `.qstrategy` / `atlas.strategy/v1`，gVisor、只读容器、无网络、资源限制、逐根供数、平台独立记账 | 任意依赖安装、多资产、实盘、自动执行可视化 DAG、对平台运营者保密 |
| 本地 AI | Ollama 结构化风险审查与多语言策略代码辅助；请求绑定、减仓/否决权限、失败关闭、最终硬风控 | 已验证的真实模型实例、机密推理、zkML、AI 决策正确性的保证 |
| Nitro 验证 | AWS 根证书固定、证书链、COSE ES384、PCR、时效、nonce、绑定及一次性挑战 | 已部署的 Enclave、私密密钥交付、在 Enclave 内执行策略/模型、业绩硬件证明 |
| 程序 ZKP v2 | 真实 RISC Zero receipt；私密有界整数程序、16 个状态寄存器、因果行情、成本后收益和公开报告绑定 | 任意 Python/LLM 证明、多资产、真实成交真实性、数据源签名 |

平台签名、包哈希、沙箱成功或通过 TEE 通道验证，均不能将报告升级为 ZKP 业绩。界面和 API 分别显示这些能力。

## Python 路径

1. 开发者用 SDK 的 `initialize(parameters)` 和 `generate_targets(context)` 编写策略，按包规范上传；当前 Runner 不调用 `on_fill`，不安装包声明的第三方依赖。镜像只有 Python 标准库和 Atlas SDK。
2. 在“版本包”选择自己的 Python 包和已登记行情，填写参数覆盖。参数由服务端按 manifest 类型、范围和选项校验。
3. 用户必须确认“平台主机能读取策略”。现有包是平台可解密的静态加密，并非端到端机密上传。
4. Runner 只收到历史已闭合 K 线；返回目标仓位，不返回可信资金/收益。独立账本在下一根开盘成交并扣费。
5. 可选 AI 只能按授权否决或缩小仓位；不可绕过最终硬风控。失败将目标设为零，仍受成交量参与率限制，**不保证瞬时清仓**。
6. 结果只作为开发者私密研究响应，不自动保存公开报告或提升证明等级。

界面默认最多最近 256 根；API 上限 1024 根，资金 100,000、手续费 10 bps、滑点 5 bps、最大仓位 95%、回撤熔断 25%、前一根成交量参与率 1%。API 支持请求模型中列出的其他合法值。逐根供数不能排除策略预埋未来答案或人为选择回测区间。

### 隔离主机准备

仅在隔离的 Linux 研究主机启用，不把 Docker socket 挂到公网 Web 容器。当前是本机 Runner 适配器，不是已完成的跨主机队列服务；正常 Compose 默认关闭执行能力。

```bash
# 先安装并验证 gVisor runsc；可参考 CI 中固定版本和 SHA256 的安装过程。
docker build -f deploy/runner.Dockerfile -t atlas-runner-local .
export ATLAS_RUNNER_ENABLED=1
export ATLAS_RUNNER_IMAGE=$(docker image inspect atlas-runner-local --format '{{.Id}}')
export ATLAS_RUNNER_SOCKET=/var/run/docker.sock
backend/.venv/bin/python deploy/runner_smoke.py
```

API 进程必须拥有明确授权的本地 Docker 权限；这本身属于高权限信任边界。执行器不接受远端 Docker endpoint、可变镜像 tag 或降级到 runc/宿主 Python。限制包括 512 MiB、1 CPU、32 PID、32 MiB tmpfs、单步 10 秒、总运行预算 180 秒和 64 KiB 响应。部署方仍需任务隔离、主机补丁、清理告警、全局并发/租户配额和监控；不得因此宣称已完成多租户生产安全审计。

### 本地 AI

```bash
export ATLAS_AI_MODEL='<本机已安装并验收的模型名>'
export ATLAS_AI_URL='http://127.0.0.1:11434/api/chat'
```

只允许数值回环 HTTP 地址，禁用代理继承和重定向。执行期风险审查发送风险摘要和目标仓位；策略代码助手会把用户指令和编辑器中的当前源码发送给同一本地服务，并只生成代码、不执行代码。两类内容都可能泄露策略信息。不能仅凭设置环境变量声称模型已经通过实际推理验收。现有测试验证协议、权限和失败分支，没有实际模型验收结果。

## TEE 路径：目前止于通道验证

管理员配置 `ATLAS_NITRO_ROOT_CERT` 为 AWS Nitro 官方根证书文件、`ATLAS_NITRO_PCRS` 为审核后的 PCR 0/1/2 SHA384 JSON 映射。根指纹固定在验证器内；不能信任用户随请求上传的根或 PCR，拒绝 debug 的零 PCR。

包所有者调用 `POST /api/v1/quantjudge/agents/{agent}/packages/{package}/tee/challenge`，随后提交 Nitro 的 Base64 COSE 文档到同路径 `/tee/verify`，均需 `X-Developer-Token`。挑战有效期 300 秒，一次消费，绑定 Agent、包哈希和随机 nonce。返回公钥必须是 X25519。

成功仅说明通道公钥与批准测量值、挑战相绑定；`performance_verified` 始终为 false。还需真实 Enclave 镜像、独立审核测量值、客户端证明验证及密钥释放、机密数据/模型执行和结果绑定，才能实现对运营方保密。当前合成证书测试不是 AWS 真实硬件证明。

参考：[AWS Nitro 证明验证规范](https://docs.aws.amazon.com/enclaves/latest/user/verify-root.html)。

## 程序 ZKP v2

新 profile：`atlas_program_backtest_risc0_v2`，注册 image ID：

```text
02b08452a95d405b82b52dd475fc448639da4465123324711b369d7e18c27cd4
```

策略程序作为私密 witness 输入，不作为每个策略单独编译的公开 guest。最多 256 条 RPN 指令、64 个栈元素、16 个状态寄存器；支持整数运算、比较、逻辑、选择、历史收盘价与 SMA。输出为 0–9500 bps 的多头目标仓位。无外部网络、无限循环或 AI 调用，非法程序直接失败，不能产生成功 receipt。

例如：至少 3 根闭合数据且最新收盘价高于 SMA3 时持有 90%，否则空仓：

```json
["index", {"const": 2}, "gt", {"close": 0}, {"sma": 3}, "gt", "and", {"const": 9000}, {"const": 0}, "select"]
```

`select` 栈顺序为“条件、真值、假值”。价格以 micro 为单位，整数除法向零截断，SMA 历史不足返回零；开发者必须显式处理预热期。程序、成本参数与随机 salt 共同进入策略承诺。寄存器初值为零，每次闭合数据更新后保留。

```bash
# 参照 StrategyWitness / ProgramStrategy 类型在本机准备 witness；不得上传 witness。
strategy/zkvm/target/release/atlas-zkvm inspect --profile atlas_program_backtest_risc0_v2 --witness /private/witness.json
strategy/zkvm/target/release/atlas-zkvm prove --profile atlas_program_backtest_risc0_v2 --witness /private/witness.json --receipt /private/proof.r0
```

使用 `inspect` 输出的策略承诺注册 Agent，将真实 Agent ID 写入同一 witness（保持程序、成本和 salt 不变）再证明。平台上传入口只接收 receipt。详情及 journal 字段见 [ZKP 协议](ZKP.md)。资金、交易数量为整数定点；风险统计沿用 guest 内确定性浮点再量化，年化外推存在上限，不等同所有专业系统的指标口径。

也可使用本地助手准备 witness：`strategy.json` 包含上例 `program` 数组以及 `commission_bps: 10`、`slippage_bps: 5`。这不是 Python 包 manifest，而是 v2 私密程序输入。

```bash
python3 strategy/zkvm/scripts/program_witness.py --market downloaded-market.json --strategy private-program.json --output private-draft.json
# inspect private-draft.json 后，使用其承诺注册 Agent，再绑定返回的真实 ID。
python3 strategy/zkvm/scripts/program_witness.py --bind-existing private-draft.json --agent-id qja_REPLACE_WITH_REAL_ID --output private-bound.json
# 对 private-bound.json 执行上方 prove 命令；不能上传两个私密 JSON。
```

助手用系统随机数生成盐和 nonce，输出权限 0600、拒绝覆盖已有文件；绑定 ID 不改变程序和盐。它不是 Python 自动编译器，也不替代 guest 的完整语义校验。公开仓库不要存放开发者的私密程序文件。

**旧 profile 不重写。** 本机重新编译旧 SMA guest 得到的 image ID 与历史注册 ID 不同，因此禁止用该重编译产物生成旧 profile 新证明；保留旧注册 ID 用于验证历史 receipt。需要重现旧构建环境或发布新版本，不能通过覆盖 image ID “修复”。本轮并未拿历史真实 receipt 做回归，不能把兼容设计说成已完成历史样本验收。

## 数据保管与泄露面

- 数据库：包元数据/平台可解密包、公开数据集清单、receipt、公开 journal、固定 profile、一次性 nullifier；TEE 挑战只保存公有 nonce、绑定及消费状态。
- 本地证明者：私密程序、salt、完整 witness 和逐笔决策。避免同步盘、公共日志和源码仓库。证明不能消除公开收益曲线的推断风险。
- Runner：宿主机暂存解密包、运行结束清理，无私密异常/容器输出日志；运营方仍可能读取内存和文件，不能承诺对其保密。
- Supervisor：本轮未修改或写入；未来链上应只锚定公开承诺/证明引用，不上传源码、提示词、原始交易或 witness。

## 验收记录

- 本地后端新增 witness 工具测试，合计 85 项；含不可信输出、权限、配置失败、AI 协议和 Nitro 合成 PKI 攻击用例。前端 12 文件 / 39 项测试及 lint、生产构建通过。
- 新程序 guest 的 4 项 Rust 测试通过；原 guest 1 项通过。
- 本机已生成真实、非 dev-mode RISC Zero receipt，并实际验证、在临时数据库注册和发布报告、重新验证；拒绝重放、字节篡改及错误 image ID，检查公共输出不含私密程序/盐。
- Linux gVisor 集成验收已通过：[Actions #34102419565](https://github.com/ashcinder/atlas-quant-lab/actions/runs/34102419565)，对应 `7a6bee3`。`isolated-runner` 涵盖真实 SDK 策略、无网络/宿主文件/只读挂载与超时、内存、输出上限；frontend、backend、containers 也均成功。
- 尚无真实模型推理、Nitro 硬件、机密端到端流程或通用 Python ZKP 验收。需要提供可用主机和模型信息后继续。

### 多语言代码编辑（2026-09-08）
代码模块支持 Python、JavaScript、TypeScript、C、C++、Java、C#、Go、Rust、R、Julia、Pine Script、MQL4/MQL5 的编辑、模板、导入下载和 AI 编写。请求可携带 language，省略时为 python。只有 Python 提供静态检查；其他语言的 validate 返回422，不表示可编译或可运行。所有语言均未在此模块接入隔离回测。
Pine 模板参照 [TradingView 策略文档](https://www.tradingview.com/pine-script-docs/concepts/strategies/)，MQL5 数据顺序参照 [CopyClose 文档](https://www.mql5.com/en/docs/series/copyclose)。平台模板仍需在目标平台验证。
