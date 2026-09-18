# 手动完成：Python 策略 → 真实 Proof → 本地策略市场

## 当前执行位置

浏览器负责编辑代码、选择公开历史行情和展示验证结果。普通回测由 Atlas 后端执行。真实 Proof 由运行下面命令的机器上的 Rust / RISC Zero 原生程序生成：在 Mac 终端执行就是在 Mac 上，在云服务器执行就是在云服务器上；不是浏览器 WebAssembly 证明。

当前支持有界整数 Python 子集，不是任意 Python、第三方库或 BaseStrategy SDK。Python 编译器运行在 zkVM 外，Proof 绑定并证明编译后程序的执行。私有源码不公开时，验证者看到的是程序承诺，不能单凭这个承诺断言某段另行展示的源码就是该程序。

## 1. 输入策略代码

打开策略实验室 → 代码，选择 Python，名称填写 `strategy`。点击「载入可证明 Python 模板」，或粘贴：

```python
def target_bps(index, close, sma):
    fast = sma(5)
    slow = sma(20)
    return (5000 if fast > slow else 0) if index >= 20 else 0
```

含义：前 20 根 K 线空仓；5 周期均线高于 20 周期均线时，目标仓位 50%，否则空仓。`10000 bps = 100%`，支持上限为 9500 bps。信号收盘确认，下一根开盘执行，最后一根不会凭空产生下一根成交。

点击「检查代码」和「下载保存」，将文件保存为 `~/Downloads/strategy.py`。语法检查和「回测受限 Python」都不生成 Proof。

## 2. 下载已登记的历史数据

在实验室选择 BTC-USD、日 K、真实数据源。打开「工具 → ZKP 证明」，使用 `atlas_program_backtest_risc0_v2`，设置：

- 开始日期：2025-08-01（UTC）
- 结束日期：2025-09-02（UTC，不含）

点击「生成数据集」，再点击「下载 market.json」，保存为 `~/Downloads/market.json`。首次建议约 32 根 K 线。数据集必须由当前本地 Atlas 登记；其他实例下载的数据不能直接在本地数据库发布。

## 3. 本地生成、验证并发布

在终端执行：

```sh
cd '/Users/tangyucinder/开发/加密货币投资'
backend/.venv/bin/python scripts/prepare-zk-witness.py \
  --dataset "$HOME/Downloads/market.json" \
  --python-source "$HOME/Downloads/strategy.py" \
  --capital-micros 10000000000 \
  --commission-bps 10 --slippage-bps 5 \
  --output "$HOME/Downloads/atlas-first-proof/witness.private.json" \
  --proof-output "$HOME/Downloads/atlas-first-proof/result" \
  --name '我的5/20均线证明策略' \
  --publish-local
```

初始资金 10000，手续费 0.1%，滑点 0.05%。输出文件和 result 目录必须尚不存在；重复实验换一个 `atlas-first-proof` 目录名。该命令自动预检、创建策略身份、生成真实 receipt、验证、执行篡改/错误 image ID 反例检查，再发布公开收益报告。发布的是当前仓库配置指向的数据库；应与正在运行的本地后端使用同一配置。

前次本机 32 根 K 线真实证明记录约 229–277 秒，仅供估计；机器、程序和 K 线数量影响时间。退出或报错都不等于成功，以 `verification.public.json` 的 `cryptographically_verified: true` 为准。

## 4. 市场中核验

打开或刷新「策略市场 → 策略排行」，搜索「我的5/20均线证明策略」，点击「验证 Proof」。应看到密码学验证通过，公开收益与证明输出一致，并绑定标的、K 线数据根、实际首末 K 线时间、程序承诺、初始资金与成本模型。

收益是指定执行与成本规则下的历史模拟结果；行情来源真实性仍依赖平台登记的数据，不是 zkTLS 交易所来源证明，也不是实盘盈利保证。普通回测引擎和整数证明引擎的结果不应被无条件当作相同。

## 输出文件

- `result/proof.r0`：二进制 RISC Zero receipt。
- `result/verification.public.json`：公开核验结果、journal、策略/Proof/报告 ID。
- `result/author.private.json`：策略开发者凭证；私密保存，不上传公开仓库。
- `witness.private.json` 及 result 中的私有 witness/draft：策略程序、salt 等证明输入；留在开发者设备。

`--publish-local` 不会发布到远端云服务。远端发布需在目标实例登记相同数据、以相同程序承诺创建身份，在生成证明前绑定该身份，然后使用目标实例的开发者凭证上传 receipt 并发布报告。
