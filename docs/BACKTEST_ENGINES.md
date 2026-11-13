# 可选回测框架

单标的回测侧栏提供“回测框架”。默认 atlas 使用现有浏览器 Worker；vnpy 和 rqalpha 调用独立 Python 进程中的真实框架，结果统一到现有图表、成交、风险指标和历史记录，并保存 backtest_engine、engine_version。外部框架不生成 atlas Proof，不作为保密策略执行器。

| 实现 | 适用范围 | 当前适配范围 |
| --- | --- | --- |
| atlas | 网页研究、内置/自定义/通用Python、统一工作流 | 保留现有功能 |
| vn.py 4.4.0 + CTA 1.5.0 | 事件驱动策略、交易应用与交易接口 | BTC-USD 已发布周期；A股日线或Hugging Face全周期；内置/自定义/通用Python |
| RQAlpha 6.5.0 | 中国股票和期货的原生账户/交易规则 | A股 .SS/.SZ：自动来源bundle日线，或Hugging Face全周期；内置/自定义/通用Python |

三框架共用策略定义：单标的内置模板、图形条件、受限整数Python以及通用Python的 `target(context)` 接口。支持循环、状态、函数、类、标准库与已打包NumPy/pandas。平台原生 CtaTemplate / RQAlpha 下单API脚本仍需要改写目标仓位接口；外部引擎参数搜索、订阅和逐步AI审核尚未适配，请求会明确报错。详见[通用Python策略](PORTABLE_PYTHON_STRATEGIES.md)。直接API必须指定起止日期；网页Hugging Face空日期会使用清单完整范围。Hugging Face接受自动或不复权，其他来源使用自动复权；结果均记录实际行情口径。外部框架单次最多100万根，进程最长600秒，API按账号限1任务、全局限2任务。

## 本地环境

API 保持原有 Python 3.14 环境；原生框架使用独立 Python 3.13，避免依赖相互覆盖。

```bash
python3.13 -m venv backend/.engine-venv
backend/.engine-venv/bin/pip install -r backend/requirements-engines.lock
backend/.engine-venv/bin/rqalpha download-bundle -d backend/.data/rqalpha
```

默认路径是 backend/.engine-venv/bin/python 和 backend/.data/rqalpha/bundle；可通过 ATLAS_ENGINE_PYTHON、ATLAS_RQALPHA_BUNDLE 修改。环境与数据都被 Git 忽略。本机安装占用约1.6GB，RQAlpha bundle约3.3GB。vn.py 使用用户指定 fork 的固定提交，CTA 是官方独立模块，固定版本来源见 requirements-engines.lock。

接口：GET /api/v1/backtest-engines 返回就绪状态；POST /api/v1/backtests/native 接收普通 BacktestRequest 加 backtest_engine=vnpy/rqalpha。接口受原有登录、同源校验与计算并发限制约束。执行器只运行仓库内的可信目标仓位适配代码，不执行请求中的 Python；通用Python由浏览器隔离的WebAssembly CPython运行，生成绑定源码哈希、行情版本、区间和数量的有限仓位向量。

## 统一研究口径（2026-11-13）

单标的选择Hugging Face后，网页默认选择“统一研究口径（三框架对账）”，也可切回“框架默认口径（保留原生规则）”。请求字段 `execution_model=unified/native`；老请求/老结果默认native，结果保存 `execution_model` 与 `execution_contract`，历史记录不会把两种口径混为一谈。统一口径支持内置策略及过滤参数、自定义条件、受限Python和通用Python；仍拒绝未解析的订阅策略和逐步AI审核。

**统一模式是共享成交与账户层，不是三个独立原生撮合器的等价性证明。** Atlas使用生产TypeScript实现；vn.py通过实际CtaTemplate回调回放，RQAlpha通过实际run_func/handle_bar回放，两个Python适配器共用 `app/backtest/unified.py`。统一模型 `research-next-open/v1` 采用所选策略的收盘信号、下一根开盘执行；统一滑点/半价差进入价格、成交额佣金、参与率、现金上限、目标改变时调仓与剩余未成交处理。零成交bar不成交，无杠杆、仅做多、允许零股。统一模式不使用原生股票撮合，不模拟T+1、涨跌停、最低佣金/印花税和公司行动；原生模式继续保留这些实现差异。

宁德时代完整历史的7周期×3框架，共21组逐根、逐笔对账通过。1分钟每个框架均为475,251根，不再截取10万根；其余周期同样使用全部可用历史。逐根净值、持仓比例及每笔时间、方向、价格、数量、手续费、现金、持仓和已实现损益均核对（允许1e-6元/1e-10相对数值误差）。全量报告：`backend/.data/cn-tech/huggingface/catl-unified-20261113/audit.json`。这属于软件一致性验收，不是策略有效性或真实股票执行准确性的证明。

长历史仍保留每根K线、账户观察和全部成交。技术指标使用全部历史计算，但仅序列化最后3000个点，避免几十万个bar生成数百万指标对象；没有截短交易/收益计算。原生请求上限100万根、进程600秒、前端等待660秒，账号与全局并发限制保持有效。

## 框架默认口径（native）

- atlas：信号在收盘后生成，下一根开盘执行。
- vn.py：调用 BacktestingEngine、CtaTemplate 和原生限价撮合。适配器收盘提交激进限价单，下一根最早成交。已发布 OHLCV 直接传入，5m 等周期作为完整 bar 回放，不重采样。LOCAL 是 vn.py 内部回放交易所标识，实际数据源以结果标注为准。适配器增加无杠杆仅做多现金、最大仓位、参与率和收盘确认止损止盈约束。手续费、滑点率与半价差按成交额扣除，其中滑点/价差计入成本，不修改原生撮合价；报告使用原生成交和适配现金账本。
- vn.py 的 A 股各周期仅作跨框架研究：沿用通用现金模型，尚不模拟 T+1、整手、涨跌停、印花税或公司行动，不能作为完整 A 股交易规则回测。
- RQAlpha：使用其独立原生中国股票 bundle 和日历，包含整手、T+1、最低佣金和卖出印花税。输入手续费率转换为原生股票佣金倍率；最低佣金仍保留。使用 PriceRatioSlippage，滑点率与半价差合并。日线和聚合周期采用原生 current_bar 收盘撮合；先将bundle未复权日线读为输入，策略仅使用所选区间的已完成bar，bar/成交价格均为未复权。报告账户净值取自 sys_analyser 原生 portfolio。

因此即使 SMA 参数一致，也不能把不同数据、预热、交易日历、费用和撮合口径下的收益差异当作引擎错误。每次结果警告记录这些差异。对严格引擎对照实验，请选择上面的统一研究口径。

## Hugging Face统一行情接入（2026-11-12）

35只项目沪深股票×7周期（1m/5m/15m/1h/4h/1d/1wk）×3框架，共735组真实运行通过；每组使用最近128根相同OHLCV、SMA5/20，保存输入哈希、dataset_id、框架版本及收益。全部245份行情的全部分块均重读并通过SHA256、OHLCV、时间顺序和数量检查。验收脚本：`backend/app/data/verify_huggingface_engines.py`；结果是本机忽略文件 `backend/.data/cn-tech/huggingface/metadata/three-engine-acceptance.json`。这是接入验收窗口，不代表穷尽历史区间和策略。

RQAlpha通过独立的 `hf_rqalpha` Mod注册数据源和事件源，使用实际输入周期的完成时点触发原生回放；不将5分钟bar伪造成1分钟bar。均线仅使用区间内已关闭的输入K线，采用原生current_bar收盘成交。周线另从同一HF日线驱动逐日账户结算，不生成额外周线信号；现金与持仓直接从原生账户取值，避免分红送转后手工账本失真。股票属性、公司行动及涨跌停参考价来自本地bundle，缺少涨跌停参考字段时明确拒绝；数据本身不含逐笔和订单簿。

Atlas/vn.py仍是既有通用研究账户，RQAlpha使用其原生股票规则，结果不承诺相同。所有来源保持独立，不用新浪补HF、不补造缺失分钟；旧版 `hf-unverified` 仍不能直接回测，须由导入命令发布为 `hf-ohlcv`。更多数据语义与复跑命令见[分钟数据说明](CN_TECH_MINUTE_DATA.md)。

## 同一标的实测（2026-11-12）

本机将宁德时代 300750.SZ 的 RQAlpha bundle 原始日线发布到本地供三个引擎使用。区间 2025-01-01 00:00 至 2025-06-30 23:59（上海时间），SMA 5/20，初始资金 100000，手续费 0.1%、滑点 0.05%、价差 0.05%、最大仓位 95%、参与率 1%，无止损止盈。三者使用 117 根相同 OHLCV，时间范围 2025-01-02 至 2025-06-30，序列 SHA256 `f37fab1672b04b80ea8d5d4551ba4e72b026691eaed24721c7555ebe9249eae4`（按 Python JSON sorted keys 格式编码）。

| 引擎 | 总收益 | 最大回撤 | 成交笔数 |
| --- | ---: | ---: | ---: |
| Atlas 浏览器 | 7.2165% | -8.4136% | 5 |
| vn.py | 7.2289% | 约 -8.34% | 19 |
| RQAlpha | 7.1256% | -8.5994% | 5 |

以上为研究对照，行情一致不代表策略执行语义一致。Atlas 与 vn.py 使用下一根开盘，RQAlpha 使用当根收盘，且存在区间前预热、复权、手续费、印花税、整手和仓位调节等差异。vn.py 和 Atlas 的通用账户不能完整模拟 A 股，公司行动期间的比较尤其有限。2026-10-30 后的数据不在这个日线快照中。原始价格以数据来源说明标明，不能把该发布误认为复权行情。

## 来源与许可

- [RQAlpha](https://github.com/ricequant/rqalpha)：其 [LICENSE](https://github.com/ricequant/rqalpha/blob/master/LICENSE) 对商业使用有额外授权要求；本机安装不代表已经获得商业部署授权。
- [用户指定 vn.py fork](https://github.com/ashcinder/vnpy)（MIT）及 [官方 CTA 模块](https://github.com/vnpy/vnpy_ctastrategy)（MIT）。

## 验证

backend/tests/test_native_backtest.py 覆盖不兼容请求拒绝、真实 vn.py 买卖/预热/现金守恒，以及可选真实 RQAlpha A股整手成交。本机已下载 bundle，两个原生引擎均执行实际回测。未安装可选环境时原生集成测试跳过，输入验证仍执行。

## 通用策略实测（2026-11-13）

宁德时代全部可用历史：19种独立策略×3框架的57组日线回放通过，包含有状态Python RSI、NumPy/pandas动量、受限整数Python、图形条件、过滤SMA和全部14种内置单标的模板。另对同一份有状态Python RSI完成6个其他周期×3框架的18组全量回放，1分钟475,251根，无历史截取。统一口径共75组，逐根资金/持仓及每笔成交数值一致；另外两份通用Python在两个原生框架的4组回放均完成，收益保留原生差异。复跑：`cd backend && .venv/bin/python -m app.data.audit_strategy_engines`，分钟周期追加 `--interval 1m --portable-only`，原生追加 `--portable-only --native`。可读报告见[通用策略验收](PORTABLE_STRATEGY_ACCEPTANCE.md)。

长历史单标的保存请求不重复上传不可变OHLCV，通过dataset_id恢复；保留全部净值和成交。浏览器报告上传上限256MiB，外部框架仓位计划32MiB，其他接口原4MB限制不变。Python运行库由npm同步到本地公共静态资产，浏览器运行时不从第三方下载包。
