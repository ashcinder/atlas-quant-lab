# Python、AI、实盘来源与链上证明：评估和本次交付

## 结论

可以构建一个有限运行环境内的可验证策略平台；不能承诺把任意现有 Python、联网 AI 和交易所 JSON 直接转换成端到端零知识证明。当前条件下不能把整个需求标记为完成。

| 要求 | 技术条件 | 本次状态 |
|---|---|---|
| Python 策略执行证明 | 固定可重现语义、资源限制、zkVM 中执行 | 增加严格 Python 子集到已有 v2 guest 的作者端编译入口，运行真实证明。证明对象是编译后的程序；编译器正确性仍需信任，并非 CPython 证明。 |
| 任意 Python / NumPy / 网络调用 | 将相应解释器、依赖和受约束输入纳入 guest 或另行适配 | 未完成。当前不支持的语法直接拒绝。不能保证无限循环或任意依赖在可接受资源内完成。 |
| AI 推理本身的证明 | 固定模型、权重、量化算法及输入；可验证推理运行时 | 未完成。AI 生成一个受支持策略可以沿同一流程证明执行，但不证明生成模型或外部 API 推理。 |
| 交易所真实成交来源 | 提供者签名，或对请求/响应建立 zkTLS / MPC-TLS 等证据 | 尚缺可用验证服务和真实接口验收。账户用户自己的 HMAC 请求签名不能证明交易所签署了响应。 |
| 实盘收益证明 | 认证且完整的账户期间数据、成交/策略绑定、出入金调整、手续费及估值 | 未完成。不应把提供的 JSON 的算术正确性标成真实实盘收益证明。 |
| Supervisor 锚定 | 外部钱包签名、手续费余额、匹配交易内容与成功回执 | 已提供真实验证后导出锚定内容与提交签名交易的工具。尚未取得钱包或新链上成功回执。 |
| 链上验证 ZKP | 适配该链的 verifier 合约与证明格式并部署验收 | 未完成。现有 ATLASZK2 只锚定摘要。 |

## Python 子集入口

新增 `backend/app/zk_python.py`，以 AST 解析，绝不 exec/eval 作者代码。仅接收单个 `target_bps(index, close, sma)` 函数，支持局部赋值、整数加减乘、受限非负整除/取模、比较、条件表达式，以及静态窗口 `close(lag)` / `sma(window)`。

所有允许表达式都有数值和指令数量边界；目标仓位必须可静态保证处于 0–9500 bps。负数除法/取模因 Python 与 guest 的语义差异被拒绝。禁止导入、循环、装饰器、文件、网络、外部 AI 与动态函数调用。条件表达式的两个分支都必须是无副作用且总能求值的表达式。

例子在 `strategy/examples/zk-python/strategy.py`：

```python
def target_bps(index, close, sma):
    return (index % 2) * 1000
```

作者端运行：

```bash
backend/.venv/bin/python scripts/prove-private-program.py \
  --witness /absolute/author/input.private.json \
  --python-source strategy/examples/zk-python/strategy.py \
  --output /absolute/author/new-directory \
  --publish-local --name 'Python子集 · 真实ZKP验收'
```

witness 内的行情须已登记。源码和编译后的私有 witness 留在作者机器，只发布 receipt 与公开报告。这个入口不提供作者关机后的平台保密执行；把它搬到普通平台主机也不会获得 TEE 保密性。

每份新报告使用作者端新生成的32字节 `nullifier_nonce`。沿用已发布报告的 nonce 会被拒绝；工具会在耗时证明前预检查，最终登记仍执行原子的防重放校验。nonce 不是盈利证据，也不能替代完整期间的数据验证。

## 链上验收工具

```bash
backend/.venv/bin/python scripts/anchor-zk-report.py --report REPORT_ID
```

工具先重新验证真实 receipt 及报告绑定，才输出 chainId=1051、value=0 和精确 ATLASZK2 内容。由钱包补全交易字段并签名后，可传入 `--signed-transaction /path/raw.txt --author-file /path/author.private.json` 提交。链回执未确认时返回非零退出码；不生成假交易哈希、不修改链数据库来制造余额或确认。外部钱包必须核对报告 ID 与 data。

本次读取到本地 RPC 链 ID 1051、区块号 140465。`eth_accounts` 不可用，未取得可用的钱包配置。区块号不变本身不足以证明网络停止：此 Supervisor 代码的交易路径也会生成区块。未进行未经配置的代签或转账。

## 真正完成实盘与 AI 证明还需要什么

1. 选择实际可用的交易数据证明协议和 verifier，固定交易所域名、账户绑定、请求参数、时间范围和分页完整性。只证明一笔盈利成交来自交易所不足以证明整个账户的收益。
2. 把认证数据验证与完整的资金账本计算放进证明程序，绑定策略版本、信号、订单、成交、期初期末资产、出入金和手续费。测试网必须始终标记为测试网。
3. 对外部 AI 选择模型权重可固定的可验证推理，或明确采用 TEE 推理证明；普通 API 文本响应不能冒充 zkML。
4. 在作者不可见于平台管理员的要求下，将执行与证明放进真实保密环境，落实远程证明后释放密钥。
5. 若要求链上直接验证，另行部署与当前链能力兼容的验证器并执行有效/篡改证明的链上测试。只写入摘要不能替代这一项。

参考：

- [RISC Zero 证明系统](https://dev.risczero.com/proof-system-in-detail.pdf)：证明固定虚拟机计算完整性。
- [Binance Spot API](https://developers.binance.com/en/docs/products/spot/rest-api)：SIGNED 指客户端请求认证。
- [TLSNotary 验证流程](https://tlsnotary.org/docs/protocol/verification/)：服务端身份与会话证据验证。
- [TLSNotary FAQ](https://tlsnotary.org/docs/faq/)：普通 TLS 与可向第三方证明的数据来源之间的区别。
