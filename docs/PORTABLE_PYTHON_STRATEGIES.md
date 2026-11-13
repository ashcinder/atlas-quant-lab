# 一份 Python 策略在三个框架回测

行情页面选择宁德时代、Hugging Face及所需周期，进入“策略实验室 → 代码策略 → 文件”，点击“载入通用Python（三框架）”，或导入自己的UTF-8 `.py` 文件。空白代码也可以直接从编辑区载入示例。在右侧“回测设置”选择标的、周期、Atlas/vn.py/RQAlpha和日期，然后点击“运行回测”（⌘/Ctrl + Enter）。资金和费率在“资金与交易成本”中修改。HF日期留空时使用清单全部历史；切换框架保留源码，返回编辑后也保留代码及设置。

```python
def initialize(context):
    context.state['signals'] = 0

def target(context):
    if len(context.close) < 20:
        return 0.0
    if context.sma(5) > context.sma(20):
        context.state['signals'] += 1
        return 0.8
    return 0.0
```

每根已完成K线调用一次 `target(context)`，返回0至1的目标仓位（0清仓，0.8为80%）；返回 `None` 沿用上次目标，也支持 `{'target': 0.8}`。`initialize` 可选，每次回测只调用一次。普通循环、函数、类、状态及计算库均可使用；代码上限60,000字符、数据上限100万根，单次Python执行最长10分钟，可主动停止。

| context属性 | 含义 |
|---|---|
| `index` | 从0开始的当前K线序号 |
| `bar` | 当前已完成bar，含Unix秒time及open/high/low/close/volume |
| `history` | 当前及以前的bar列表 |
| `close` | 当前及以前的收盘价列表 |
| `sma(n)` | 最近n根均价，历史不足返回None |
| `state` | 当前回测跨bar保留的字典 |
| `params` | 调用请求的自定义参数字典；网页可直接在源码中定义参数 |
| `last_target` | 上一根信号目标；不代表实际成交后的账户仓位 |

源码示例：[`stateful_rsi.py`](../strategy/examples/portable_python/stateful_rsi.py)、[`pandas_momentum.py`](../strategy/examples/portable_python/pandas_momentum.py)。上下文按时间追加历史；策略作者仍需自行避免从外部数据引入未来信息。信号阶段不读取框架账户现金、成交回报或订单簿，依赖这些接口的原生策略需要显式改写，不能将原生SDK脚本直接原样跨框架运行。

## 执行口径

HF默认使用统一研究口径：同一份Python产生同一目标仓位，三个框架按同一费用、下一根开盘、流动性约束回放，实际仓位受现金和风险设置约束。实际调用vn.py的CtaTemplate回调和RQAlpha的handle_bar；两个外部回放共享研究账本。它允许零股，不模拟T+1、印花税、涨跌停或公司行动，因此这种一致性不等于三个原生股票撮合器等价。

选择“框架默认口径”会保留各框架撮合、账户与费用差异，收益可以不同。统一策略接口不会强制修改原生收益。普通Python回测不生成Proof，也没有接入订阅持续运行；原有整数 `target_bps(index, close, sma)` 接口仍保留。

## 运行环境

Python在浏览器WebAssembly CPython Worker中运行。独立的无同源权限iframe和CSP限制可访问资源，运行库不获取主页面DOM或登录凭据；退出、页面关闭、用户取消会终止Worker。API和原生引擎进程只接收已验证的目标向量，不对请求源码使用exec/import。目标绑定不可变dataset_id、源码SHA256、起止时间与bar数量；所有值须为有限的0至1数字。

NumPy、pandas及依赖随项目静态资产打包。首次安装/构建需要下载经过锁文件SHA256校验的官方Pyodide包，运行时仅读取本地公开包文件。依赖宿主文件、网络服务、操作系统子进程或未打包原生扩展的Python代码需改写。增加Pyodide支持的包可执行 `cd frontend && npm run python:sync -- scipy`，部署时一起携带 `dist/python-runtime/`。静态运行库通过 `/api/v1/python-runtime/{filename}` 提供，禁止路径穿越和符号链接。

```bash
cd frontend
npm install
npm run python:sync
npm run build
```

官方环境说明：[Pyodide运行包](https://pyodide.org/en/stable/usage/loading-packages.html)。回放和报告验收见[实测结果](PORTABLE_STRATEGY_ACCEPTANCE.md)。

本地启动API和Vite后，可访问 `/tests/fixtures/portable-runtime.html` 复验浏览器有状态Python、NumPy/pandas和死循环取消；成功显示PASS。

## 导入多文件 Python 项目

在「策略实验室 → 项目文件」打开 ZIP，也可以从「文件 → 导入 Python 项目」进入。左侧文件树可展开目录，中间可打开多个标签、编辑 UTF-8 Python 源码或新建 .py 文件。选中入口脚本后点击「运行当前文件」，也可用 ⌘/Ctrl + Enter。运行会使用工作区的当前代码，右侧显示结果和运行日志。项目保留 ZIP 内的目录结构，可以导入项目中的模块和包、读取包内 CSV 或 JSON，并使用项目自己的行情、资金设置及撮合逻辑。程序以 `__main__` 运行，工作目录为项目根目录，项目从包内数据运行。单文件编辑器仍可使用 AI 助手生成代码，并按网页所选标的回测。

运行发生在浏览器的独立 Python Worker 中。支持 Python 标准库以及已随平台提供的 NumPy、pandas、SciPy、scikit-learn、joblib、threadpoolctl 和 tzdata。请将需要的离线数据和可直接导入的 Python 源码一并放入 ZIP。依赖自动识别源码中的静态导入，运行环境不执行 `pip install`，也无法运行宿主程序。ZIP 最大 64 MiB，解压内容最大 256 MiB，单次运行最长 10 分钟。切换回单文件编辑器会保留当前页面里的项目和报告。刷新或离开页面前，请用「导出项目」保存修改后的 ZIP，并下载需要保留的回测报告。

脚本可将报告写入 `os.environ["ATLAS_OUTPUT_DIR"]` 指向的目录。网页展示 `summary.json` 中的 `return`（小数累计收益）、`max_drawdown`（小数最大回撤）、`equity`（期末净值）和 `sells`（平仓笔数）。也接受将指标放在 `result` 字段下。下载的报告 ZIP 包含该目录下的文件及运行日志，最多收集 500 个文件、16 MiB 输出。现有四行业包可直接选择 `tools/limit_up_study/strategy_*.py` 运行，其默认回测产物也会被收集。
