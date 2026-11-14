# RQAlpha 策略实验室

## 唯一的新策略入口

「新建策略」直接打开 RQAlpha Python 代码页，普通 `.py` 导入同样不再选择策略类别；页面没有引擎或语言切换控件。新策略统一使用原生 `init` / `handle_bar` 协议，支持一只或多只沪深 A 股。保存、检查、历史回测、取消、六标签报告和下载沿用账号私有工作流。

旧单标的受限 Python、Atlas 多标的 SDK、其他语言和策略包仍按原始来源保存，只读查看源码、下载及历史，不自动转换到 RQAlpha，也不允许从实验室创建旧引擎任务或新运行版本。已有运行版本/模拟实例不因入口整改而删除；它们不等于支持运行新 RQAlpha 策略。

## 四行业与分钟数据状态

回测设置提供半导体、军工、商业航天、机器人四个行业目录。行业成员来自已核验的月度研究池及其公开时点，含 ETF 披露代理或历史指数名单，不宣称是完整行业成分。目录按所选开始日期刷新，不会自动删除已选证券；不匹配时由用户核对。日线自选池固定于开始时点成员，分钟新增买入还需符合各日已公开生效的成员名单，移出后仍可退出原持仓；成员版本随任务保存。

分钟基础源固定为 [neigezhu/china-a-share-1min-ohlcv](https://huggingface.co/datasets/neigezhu/china-a-share-1min-ohlcv)，revision `ba589a11534825044fe5a6b84838f50ba8d8d188`。用户已确认首批按实际完整覆盖接入，不再以未齐至今天为前置阻塞；优先从2025-01-02开始，更早原始历史保留。该版本最后完整日最多为2026-08-06，2026-08-07只有部分记录，此后未覆盖。页面列出逐股日期边界和缺口数量；行业日期是外边界，不表示所有成员或区间连续完整，运行前仍逐日检查。缺根、未确认缺日、缺少配套原生日线或名单时明确拒绝，不静默缩短区间或回退日线。

可用快照及可信适配器配置后开放 **1/5/15/30/60 分钟**。五周期共用真实1分钟基础，5/15/30/60按上午、下午分别向上聚合，不跨午休、跨日或读未闭合根。接入采用明确的结束标签规则，源09:30/13:00额外观察原值保留、只进入已经可见的当日累计快照，不作为连续分钟或已认证的竞价行情，不平移全日时间、不反向细分15分钟。没有可核验竞价数据，竞价报价/下单和算法订单明确不可用。`history_bars(..., '1m')`仍返回真实连续1分钟，所选周期的BarMap、PriceBoard和原生撮合共享同一价量；历史预热跨已知采集缺口会失败，不将缺口当休市。日线能力保留。

分钟首批按至少两个完整交易日运行，开始时间不晚于首日09:30，结束不早于末日15:00；盘中边界不满足时明确拒绝，不声称支持任意盘中截窗。买卖和日志保留分钟时刻，净值、账户、持仓和252交易日风险统计继续按原生日结，不把分钟根数当交易日年化，也不补造分钟净值曲线。

本轮本机冻结四行业历史成员并集114只，2025-01-02至2026-08-06共386个交易日，保存10,551,462条原始时间观察、2269个月块。112只完整覆盖386日，601718另有1个来源明确确认的停牌日；601989只完整到2025-09-04，其后221日未覆盖，不能把它加入更晚区间运行。上述是本次冻结审计，不代表后续版本、全部市场或每个标的的实盘行情质量。

本轮另在gVisor核对43,782个完整证券日的HF累计OHLCV与配套原生日线，全部有对应日线；6只股票的13日存在开盘价或最高价差异，未强行改平。分钟撮合和当前可见累计快照按HF原值，历史日线读取、前收盘、涨跌停及公司行动使用冻结原生包；两种来源不能被描述为同源逐字段完全一致。原始差异和逐股示例保留在本机兼容审计证据中。

行业目录由运营侧配置 `ATLAS_RQALPHA_SECTOR_MEMBERSHIP` 指向独立、已核验且带摘要的 `atlas.rqalpha.sectors/v1` 清单；清单包含四行业的时点版本（`as_of`、`published`、`effective`、来源和平台证券代码），不能仅将全期并集作为每期交易池。未配置或校验失败时明确提示，不用演示名单替代。该清单只是成员身份，不包含或证明分钟行情覆盖。

以下 Atlas SDK 与发布器章节仅供原有历史运行实例及运维参考，不再作为新建入口。

## 历史 Atlas 策略约定

- 实现 `generate_targets(context)` 返回 `TargetPosition`，或实现 `generate_orders(context)` 返回市价 `OrderIntent`。未声明目标的持仓保持原状，明确返回零仓位可提出卖出。策略进程读取已收盘行情、现金、持仓、当日可卖股数和已发生的模拟成交。平台校验并撮合建议。
- 需要跨事件保留状态时成对实现 `export_state()` 与 `import_state(state)`。检查点使用不超过 4 MiB 的 JSON。连续运行只在隔离环境中还原策略状态，账户现金与持仓由平台另行保存。
- 通用 Runner 固定 Python 和科学计算库版本。使用新镜像前，将镜像构建在独立 Linux gVisor 环境，用本地镜像 ID 配置 `ATLAS_PORTFOLIO_RUNNER_IMAGE`。配置 `ATLAS_LAB_MULTI_ENABLED=1`、`ATLAS_RUNNER_ENABLED=1` 和独立 Runner 的 `ATLAS_RUNNER_SOCKET`。使用 [gVisor Docker 配置文档](https://gvisor.dev/docs/user_guide/quick_start/docker/) 和仓库的 `deploy/portfolio-runner.Dockerfile`。
- 发布候选环境用临时 `ATLAS_DATA_DIR` 执行 `python deploy/portfolio_runner_smoke.py`。实际 Runner 验收包含依赖加载、状态恢复、隔离、超时、内存和输出上限。

## 行情发布与旧基准

运营侧将带交易日历的清单和逐事件 JSONL 交给发布器。API 进程读取已发布版本。执行规则字段应按证券和交易日期取得，经交易所或行情提供方校核。参见[上交所交易规则](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)和[深交所交易规则](https://www.szse.cn/lawrules/rule/trade/current/t20260424_620190.html)。

```sh
cd backend
ATLAS_DATA_DIR=/path/to/isolated-data python -m app.publish_portfolio_market /path/to/manifest.json /path/to/events.jsonl
```

持续发布可使用 `python -m app.publish_portfolio_market --watch /path/to/batches --interval 30`。供应方使用唯一批次名，先写完 `<批次>.events.jsonl`，再原子放入同名 `<批次>.manifest.json`。清单须记录事件文件的 `events_sha256`。摘要错误、文件尚未写完或规则校验失败时保留旧版本，下个周期重试。行情采集和证券规则由上游提供。

清单使用 `atlas.cn.market/v1`。指定 `profile`（`historical` 或 `live`）、`interval`（`1d` 或 `15m`）、`symbols`、`sessions`（北京时间交易日期）和 `source`。持续模拟清单还需声明 `calendar_through`，滚动更新应覆盖实例上次处理的时点。事件包含 UTC 秒级收盘时间 `time`、分股 `bars`，或逐股显式标记 `suspended`。每根 K 线记录 `open_time`、OHLCV、申报数量及上下限。没有价格限制时上下限均填 `null`。可增加按日期取得的 `lot_step`、`sell_tax_rate` 和公司行动。缺少已核实结算条款的公司行动用 `unresolved_actions` 标记，涉及持仓或待成交时停止该次计算。

通过本地研究目录的 `tools/limit_up_study/build_portfolio_sector_examples.py` 可重现历史四行业 Atlas 样例包和行情身份；这些旧包不是原生 RQAlpha 源码，不再从新建入口创建或导入。原基准、旧引擎结果与新结果分别保存，历史快照曾用于选参，不能称作样本外业绩或分钟接入验收。

如持有证券遇到公司行动，可以为本地生成器提供 `--cash-dividends /path/to/verified-terms.json`。该输入仅接收登记日为上一交易日、除息日与发放日相同的纯现金分红。模拟在发放日开盘前按持股数计入税前现金，股份数量保持原值。公告来源表的摘要随新行情版本保留。按持股期限补扣的股息税当前未建模。

## RQAlpha 学术非商用日线

此入口使用公开版 RQAlpha 6.5.0，不是 RQAlpha Plus，不需要 RQData 账号或个人 Key。使用必须符合[官方 LICENSE](https://github.com/ricequant/rqalpha/blob/master/LICENSE)规定的个人非商业、非营利教学科研范围；本机研究接入不代表获得商业服务或原始数据再分发许可。

### 用户操作与策略协议

1. 点击新建或导入原生 `.py`，直接进入 Python 工作台，无需选择类别和引擎。支持1–150只沪深A股静态股票池日线；配置配套HF快照后，四行业实际成员可使用1/5/15/30/60分钟。北交所和Atlas策略包不属于原生入口。
2. 配置时间、共享资金、费用与股票池，保存草稿，检查源码和行情覆盖，再运行。源码检查只做静态语法与入口检查，不能代替真实回测。
3. 从历史重新打开或下载快照，核对该次引擎版本、撮合规则、源码与行情摘要。打开历史不会重新运行或更新旧结果。

原生入口为 `init(context)` 和 `handle_bar(context, bar_dict)`。`context.symbols` 是平台所选股票对应的原生代码，例如 `600519.XSHG`、`000001.XSHE`；`context.parameters` 为保存的 JSON 参数。可使用原生 API 和可选 `before_trading`、`after_trading`、`open_auction` 回调。平台在隔离进程内只执行一次策略顶层；源码不应声明 `__config__`，回测配置由平台控制。

```python
from rqalpha.api import order_target_percent, update_universe


def init(context):
    context.placed = False
    update_universe(context.symbols)


def handle_bar(context, bar_dict):
    if context.placed:
        return
    for symbol in context.symbols:
        order_target_percent(symbol, 0.8 / len(context.symbols))
    context.placed = True
```

本例只用于接口演示，不是策略收益或投资建议。RQAlpha 使用 `current_bar` 收盘价撮合，并非 Atlas 的下一根开盘模型；不支持把日线 `next_bar` 静默改成其他规则。最低佣金为 5 元，佣金按配置费率映射为原生倍率，卖出印花税启用历史日期口径；滑点与成交量参与率交给原生撮合。股票池和单股仓位上限使用原生订单前校验，不以第二套引擎重复撮合，也不代表实盘风控保证。

回测保存原生净值、现金、成交、逐日与期末持仓、账户资金组成、拒单和公司/资金事件，以及原生指标和有界运行日志。持仓浮盈亏不是累计已实现盈亏；股票总权益还可能包括应收分红、冻结资金、待到账申赎和负债，不能只用可用现金加市值代替。结算后、账户重置前采集每日盈亏和资金组成；可卖数量另取结算前快照，无法可靠对应时为 `null`。原生没有提供的明细不会补造。回测结果、下载与页面均标为 `unverified`；同进程任意 Python 可以影响引擎对象并读取所挂载数据，因此文件摘要、重复执行和容器隔离不等同于防篡改、任意策略无未来数据保证、ZKP、zkTLS 或实盘业绩证明。

RQAlpha 不能创建旧 Atlas 运行版本、发布订阅、持续模拟或申请现有 Proof。旧策略也不再从实验室新建运行版本；既有历史版本和模拟实例保留，未迁移或删除。

### 运营侧准备

已验收环境为 Linux ARM64、Python 3.12、独立 Docker + gVisor。`deploy/rqalpha-runner.Dockerfile` 的基础镜像固定为该架构摘要，依赖和构建约束分别见同目录的 `rqalpha-runner.requirements.lock`、`rqalpha-runner.build-constraints.txt`；其他架构需选定对应固定基础镜像并重新验收，不能自动降级为宿主执行。

先在新空目录通过 HTTPS 获取官方免费日线包。不要直接使用会清空目标目录并裸解包的旧下载器。由主应用目录运行安全准备工具，原始包、解包目录与清单相互分离：

```bash
python3 -I tools/prepare_rqalpha_bundle.py /path/to/rqbundle_YYYYMM.tar.bz2 /path/to/new-empty-directory /path/to/preparation.json --source-url https://bundle.assets.ricequant.com/bundles_v4/rqbundle_YYYYMM.tar.bz2
```

将 `YYYYMM` 替换为实际官方月份；如已有可信预期摘要，可增加 `--expected-sha256`。本地计算的摘要只用于固定已下载字节，不能据此声称数据来源已获密码学证明。工具拒绝链接、穿越、重复路径、大小写冲突和超出预算的归档，不在宿主加载包内 pickle。

在专用 Linux 执行主机构建并记录本地镜像 ID：

```bash
docker build -f deploy/rqalpha-runner.Dockerfile -t atlas-rqalpha:6.5.0 .
```

仅在隔离数据目录启动候选环境，配置：

| 环境变量 | 用途 |
| --- | --- |
| `ATLAS_DATA_DIR` | 独立应用数据目录，验收时不指向个人账本 |
| `ATLAS_RUNNER_ENABLED=1` | 显式允许受控隔离执行 |
| `ATLAS_LAB_MULTI_ENABLED=1` | 启用现有多股任务调度 |
| `ATLAS_RQALPHA_RUNNER_SOCKET` | 专用 Docker 的本地 Unix socket，不复用不明确的远程 context |
| `ATLAS_RQALPHA_RUNNER_IMAGE` | 经审核的本地 `sha256:...` 镜像 ID，不使用可变标签执行 |
| `ATLAS_RQALPHA_BUNDLE_DIR` | 安全解包的根目录 |
| `ATLAS_RQALPHA_DATASET` | 发布完成的覆盖与摘要清单 JSON |
| `ATLAS_RQALPHA_SECTOR_MEMBERSHIP` | 已核验四行业时点成员清单 |
| `ATLAS_RQALPHA_MINUTE_DIR` | 只读分钟发布目录，包含 `index.json` 和月块 |
| `ATLAS_RQALPHA_MINUTE_DATASET` | 上述目录中的 `index.json`，绑定配套日线与成员摘要 |

API 主机和隔离 Docker 必须能访问相应的只读包路径。容器内会再次验证完整文件集合和逐文件 SHA-256，不能仅以宿主副本的摘要声称容器实际输入一致。不要挂载个人家目录、Docker socket、API 数据库或任何 Key 到策略容器。

在 `backend/` 目录、已配置专用 socket/镜像和独立 `ATLAS_DATA_DIR` 的环境中发布覆盖清单：

```bash
python -m app.publish_rqalpha_dataset /path/to/preparation.json /path/to/extracted-root /path/to/new-dataset.json
```

将 `ATLAS_RQALPHA_DATASET` 指向生成文件。该命令在固定 gVisor 内读取原生日历和股票日线首末日期，并检查 `indexes.h5` 内三种支持指数的有效价格交易日；API 只接受数据快照，不在点击预检或运行时下载、订购行情。选择基准时必须覆盖全部回测交易日及前一交易日，旧清单缺指数覆盖就明确拒绝，需在隔离环境发布新清单。新数据或镜像应使用新版本验收，排队任务发现冻结身份改变会失败，不静默切换。

执行默认限定 1 CPU、1 GiB、600 秒、32 个进程、32 MiB 临时盘，禁网、非 root、只读根且无额外 capabilities。运行结果和 JSON 有体积/条数限制。取消会终止并核对容器；无法确认清理时保留错误并记录告警，不能把「已取消」当作清理成功。停止该专用执行器会拒绝新 RQAlpha 任务，但不删除任何历史或切回 Atlas 代跑。

已配置上述变量后，可在主应用目录用仓库内的真实 Runner 冒烟入口执行两次固定日线回测：

```bash
backend/.venv/bin/python -I deploy/rqalpha_runner_smoke.py --symbols 600519.SS 000001.SZ --start '2025-01-02T00:00:00+08:00' --end '2025-12-31T23:59:59+08:00' --output /path/to/new-smoke-report.json
```

日期必须在实际快照覆盖内，例中标的仅用于测试。该脚本比较净值、成交、期末持仓和已记录事件，排除每次生成的订单/成交编号；无 SDK/快照/隔离环境时明确失败，不以替身测试或宿主运行冒充通过。

### HF 分钟数据准备

只在独立准备环境安装受控的 Parquet 读取依赖（本机验收为 PyArrow 26.0.1）；主API和策略镜像无需加载Arrow或数据集仓库代码。原始文件、下载凭据、发布数据和脚本分别保存。不要使用默认 `load_dataset`：它只加载每股最早最多64条的浏览样本。

从项目根调用固定源下载器，目标必须是新建空目录；默认只取四行业历史成员并集，可用 `--symbols 600584.SS 603986.SS`限定技术验收范围，不下载全市场43GB：

```bash
/path/to/preparation-python -I tools/prepare_rqalpha_minutes.py download /path/to/new-empty-raw /path/to/new-receipt.json --membership /path/to/verified-sectors.json
```

然后离线规范化，`--daily-digest`取已发布原生日线清单的实际digest，不能用文件路径或随意摘要：

```bash
/path/to/preparation-python -I tools/prepare_rqalpha_minutes.py prepare /path/to/new-empty-raw /path/to/new-receipt.json /path/to/new-empty-minutes --membership /path/to/verified-sectors.json --daily-digest ACTUAL_DAILY_DATASET_SHA256 --start 2025-01-02 --end 2026-08-06
```

准备工具逐文件核对下载摘要、Parquet字段/单位/时间排序/有限OHLCV/整数股数和日历，逐证券日记录完整240根、缺分钟、确认停牌或零成交；重复/非法行不发布。月块采用固定gzip与CSV，只读索引为 `atlas.rqalpha.minutes/v1`，绑定源版本、许可声明、原始摘要、日线规则和名单。执行时宿主及容器再次检查，选中证券按月有界读取，不把全部行情塞入单个JSON请求。每个快照使用新目录，不覆盖旧行情或历史结果。

源价格不复权、成交量为股、成交额为元，naive时间按UTC+8解释；历史调整复用原生冻结因子。发布者声明Apache-2.0但未披露上游提供方，不将其等同为独立授权审计、来源签名、zkTLS或ZKP。数据不随源码公开上传或自动实时补齐。

### 米筐式回测报告

成功回测可通过「查看完整报告」展开为六个标签；历史打开、标签切换和下载不触发重新回测。

- **收益概览**：19项中文指标及缺值原因，策略/基准/算术超额曲线、最大回撤区间、每日盈亏和买卖金额。共享日期提示、键盘选日、时间范围、线性/对数轴及数据表可读。年度弹窗同时显示策略、基准及实际覆盖；部分年度不冒充全年或年化。
- **交易详情**：原生成交及开平、证券名、佣金/税费/标识，可按日期、证券、买卖筛选和分页。
- **持仓详情**：逐日数量、均价、估值、浮盈亏、应收分红与可卖量。零股数但仍有应收分红的原生记录保留；名称来自冻结数据包，不保证是历史时点名称。
- **账户详情**：逐日可用资金、权益、市值、费用、盈亏；可展开冻结资金、应收分红、现金负债、负债利息及待到账申赎。保证金在当前股票范围标为不适用。
- **输出日志**：INFO/WARN/DEBUG/ERROR筛选、倒序、文本下载。失败和实际取消任务保留已采集私有日志与可定位的策略行号，不公开宿主路径/环境/内部堆栈。超采集限额有明确标识，不把丢弃的日志当作完整记录。
- **性能分析**：首版仅诚实显示未开启，不在打开报告时采样或重跑；总耗时不等于函数性能分析。

基准可选沪深300、中证500、上证指数或无基准；缺基准时相对指标显示不可计算。年/季/月胜率采用平台正收益期间比例（含首尾部分期间），日胜率采用原生正收益交易日比例，均不是逐笔或超额胜率。算术超额曲线为净值差，而超额最大回撤采用原生策略/基准净值比，定义不能混用。日单位净值按原生6位小数记录，曲线及年度复利据此计算；原生风险指标保留原始精度，并列出来源和口径。

明细以每块最多1000行保存到账号私有对象，默认每页50行，可选25/100，API最高500行。完整筛选导出不受当前页限制，支持成交/持仓/账户/年度CSV、日志文本和完整JSON快照；CSV含中文表头、北京时间及公式注入保护。超过1000条成交不再内联，响应显式 `trades_complete=false`，通过明细与完整导出读取，不能把空内联数组误作无成交。旧历史缺逐日数据或日志时明确未记录，不补造、不覆盖或自动重跑。

报告协议为 `atlas.rqalpha.report/v1`；原生Worker扩展数据为 `atlas.rqalpha.raw-report/v1`，运行通过现有 `atlas.rqalpha/v1` 帧通道，带请求标识、批次偏移和最终计数。单帧仍限16MiB、整次通道64MiB、经济明细合计250,000条；日志限2000条/1MiB/单条4096字符。私有存储每对象仍限16MiB，不取消输入摘要、禁网/只读或清理确认。

相关私有接口统一位于 `/api/v1/lab-multi/jobs/{id}`：`/source` 读取本次固定源码，`/report/{trades|positions|accounts|logs}` 分页，`/export?table=...` 完整导出。均以登录会话和任务所有者校验；内部对象摘要不是下载凭据，没有新匿名公开链接。
