# A 股龙头涨停预测 → 同行补涨研究

本示例是项目内独立的 Python 多股票研究程序，通过原生 RQAlpha 执行真实 A 股日线历史回测，并导出模拟交易信号。它没有券商实盘下单接口。网页的单标的 `target_bps` 受限解释器不能直接运行此多股票模型，请按下面的脚本命令运行。

当前固定版本的完整回测结果、限制与图表见 [results/REPORT.md](results/REPORT.md)。当前版本的同行买入策略亏损，预测龙头触板命中率没有转化为正收益。

## 运行

在仓库根目录，使用已经安装好的隔离引擎环境：

```bash
backend/.engine-venv/bin/python strategy/examples/a_share_leader_follow/research.py
```

程序默认读取 `backend/.data/rqalpha/bundle`，输出至 `.artifacts/a-share-leader-follow/`。这是一次完整的真实数据研究运行，没有随机生成行情，也没有调用云端模型。数据和本地特征缓存不上传 Git；请只使用可信的 RQAlpha bundle，因为官方元数据及本程序缓存采用 pickle。

新机器需要 Python 3.13 和隔离环境，安装参考 [回测引擎文档](../../../docs/BACKTEST_ENGINES.md)，精确依赖在 [requirements-engines.lock](../../../backend/requirements-engines.lock)。运行所用关键版本：RQAlpha 6.5.0、pandas 3.1.1、NumPy 2.5.4、SciPy 1.18.1、h5py 3.16.0、matplotlib 3.11.2。

```bash
# 仅生成特征、滚动训练模型、预测和历史末日模拟信号
backend/.engine-venv/bin/python strategy/examples/a_share_leader_follow/research.py --prepare-only

# 指定已有的真实日线数据与输出目录
backend/.engine-venv/bin/python strategy/examples/a_share_leader_follow/research.py --bundle /path/to/bundle --output /path/to/output

# 强制重建股票和行业特征缓存
backend/.engine-venv/bin/python strategy/examples/a_share_leader_follow/research.py --refresh

# 时序因果与开盘订单计划测试
backend/.engine-venv/bin/python -m unittest discover -s strategy/examples/a_share_leader_follow -p 'test_*.py' -v

# 独立核验全部成交价、T+1、行业、限价、手数与费用
backend/.engine-venv/bin/python strategy/examples/a_share_leader_follow/verify_execution.py
```

`research.Parameters` 固定测试期2023-01-01～2026-10-30、初始100万元、持有最多3个交易日。每月使用之前3年的已知数据训练逻辑回归；预测月份之前尚未知的下一日标签不进训练。行业龙头按历史价量定义，同行不包含该龙头，预测信号在T收盘确定，次日才参与买入。

开盘订单在撮合前整批冻结：按除权参考价制定最高+3%的买入限价，按限价预留预算；不先观察最终开盘价或同一次竞价成交结果，再调整数量、换股或花掉卖出所得。停牌、涨停买不到、跌停卖不出会影响实际成交，3日是计划持有期限。公司行动、T+1和红利税由RQAlpha处理；额外交易费用与冲击成本通过账户真实扣除。

## 文件

- `research.py`：实际数据读取、因果价量特征、历史龙头/同行筛选、月度滚动预测、历史信号导出。负向shift只用于评估标签，交易回调接收前会去掉标签列。
- `rq_backtest.py`：冻结竞价订单计划与原生引擎执行、交易成本、对照/压力实验、风险指标和20日块bootstrap。
- `reporting.py`：根据实际结果生成中文报告与净值/回撤图。
- `test_research.py`、`verify_execution.py`：未来数据扰动、训练截止、订单预算及真实成交核验。
- `results/`：本次已验证结果的轻量快照；完整模型和逐笔CSV保留在本地`.artifacts/`目录。

特征缓存按特征代码、相关参数与bundle文件时间/大小校验失效。`latest_signal_plan.json` 只是本地历史末日（2026-10-30）的研究信号，不是当前日期的交易指令。行业分类使用bundle的当前快照，不能替代历史时点行业成分；日线开盘价撮合也不能证明真实竞价流动性。这些限制与费用假设全部写入报告。
