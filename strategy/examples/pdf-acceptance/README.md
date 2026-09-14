# PDF 验收策略

三个 JSON 是创建私有运行版本的请求体，对应模板、图形和受限 Python 三个入口。测试规则用于快速覆盖成交链路，不是收益策略。

在策略实验室选择对应模块编辑，保存并订阅运行版本，然后进入策略交易配置运行。Python 示例只接受 `target_bps(index, close, sma)` 的受限整数语言，不能导入模块或访问网络/文件。也可将 JSON 作为已登录会话的 `POST /api/v1/strategy-releases` 请求体；之后仍需订阅和显式配置运行。

本轮测试配置：Binance Spot Testnet、BTC-USDT / ETH-USDT / SOL-USDT、15分钟、每项100 USDT、最大仓位20%。资金为测试币。三项运行已经暂停，持仓未卖出。实际运行记录位于本机隔离验收数据目录，不包含在这些可分享的定义里。
