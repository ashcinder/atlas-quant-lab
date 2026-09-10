# 交易账户接入

2026-09-09：新增 `#/trading`。支持币安及欧易 **USDT 现货限价单**的人工预览、确认、查询与撤单。AI、策略画布、回测和代码执行均没有连接到交易接口。未实测真实账户，不代表交易所或券商已连接。

## 服务端配置

在启动后端的环境中设置变量；不要写入前端 `VITE_` 变量、Git、聊天或策略源码。现阶段只支持一位明确绑定的交易账户所有者，不支持多租户凭据托管。其他应用用户不能读取余额或提交订单。

1. 登录平台，打开「交易账户」，在本机配置说明中取得当前用户 ID；设置 `ATLAS_TRADING_OWNER_ID`。
2. 设置下表中所需交易所的密钥。测试密钥与实盘密钥不可混用。币安当前支持 HMAC 密钥；欧易还需 Passphrase。密钥应仅有账户查询与现货交易权限，不需要提现权限。
3. 设置 `ATLAS_TRADING_ENABLED=1`，重启后端，刷新连接状态并查询余额。此查询成功才说明账户实际连通；“凭据已配置”不代表连通。
4. 输入自选交易对、方向、数量和价格，预览后输入对应确认文字。默认单笔上限 100 USDT，可用 `ATLAS_TRADING_MAX_ORDER_USDT` 设置正数限额。

| 环境变量 | 默认／说明 |
|---|---|
| ATLAS_TRADING_OWNER_ID | 必填，应用用户 ID |
| ATLAS_TRADING_ENABLED | 默认关闭；1 允许提交订单 |
| ATLAS_TRADING_LIVE_ENABLED | 默认关闭；1 才允许实盘提交 |
| ATLAS_TRADING_MAX_ORDER_USDT | 100，按数量 × 限价计，不含手续费 |
| ATLAS_BINANCE_MODE | demo；仅 demo 或 live |
| ATLAS_BINANCE_API_KEY / ATLAS_BINANCE_API_SECRET | 服务端 HMAC API 凭据 |
| ATLAS_OKX_MODE | demo；仅 demo 或 live |
| ATLAS_OKX_API_KEY / ATLAS_OKX_API_SECRET / ATLAS_OKX_PASSPHRASE | 服务端欧易凭据 |

币安 demo 使用 `https://testnet.binance.vision`；欧易 demo 使用正式 API 域名及 `x-simulated-trading: 1`。实盘需要该交易所 `MODE=live`、对应实盘凭据、两个交易开关同时开启，且用户逐笔输入“确认实盘下单”。不提供提现、杠杆、合约、市价单或自动策略下单。

## 订单与异常处理

- 预览不调用下单 API，两分钟有效。服务端固定预览中的交易所、环境、账户指纹及参数，确认时再检查单笔限额和开关。
- 在 SQLite 先持久化提交意图，再访问交易所。重复确认同一预览不会再下单，重启后仍有效。每个预览都有唯一客户端订单号；新建预览是新的独立订单。
- 已识别的明确业务拒单标记为 rejected；超时／不完整回执及未识别错误标记为未知，不自动重试。使用「查询状态」按客户端订单号核实；订单未查到也不能立即断言没有提交成功，应到交易所核实。
- 撤单先持久化意图，失败标记为撤单结果未知；并发返回通过条件更新避免覆盖更新后的状态。“受理”不是“成交”；“撤单已请求”不是“已撤销”。查询结果才反映交易所最新状态。关闭新订单开关仍可撤销原订单。下单处理中需先查询确认受理；已成交/撤销等终态不可再撤单。活动撤单有60秒租约，期间查询返回处理中，过期后可查询恢复；失败保留已有成交数量。
- 最近订单只展示平台创建的最近 100 条。余额与订单只向绑定用户返回；签名、密钥、上游错误原文不回传。订单明细在本机 SQLite 留存，应保护数据目录。
- 当前交易所负责余额、可交易状态、最小下单金额和步长校验；平台没有实现全账户资金预算、全量订单同步、自动对账、成交回报推送或投资组合风控。上线前必须先在官方测试环境联调。不要将研究模块的风控配置视为实盘风控。
- 修改 API key 或环境后，旧订单必须切回原账户／环境才能查询；不会误发到新账户。

## A 股：miniQMT 路线

首个适配参考选择国联证券官方 QMT 文档入口。依据是公开的账号申请和 miniQMT 接入资料，不是收益、佣金或开户推荐。可用性及具体准入以券商确认为准；未开户或替用户申请权限。

当前提供**只读环境探测脚本**，尚未实现远程桥接或 A 股下单。Mac 无本机 QMT 客户端，需使用安装了券商授权 MiniQMT 的 Windows 主机。先向券商确认账户具有原生 Python/函数下单权限，安装其支持的 Python/xtquant 并登录极简模式。不能仅用普通证券账号和密码代替接口开通。

在该 Windows 主机的 PowerShell 中配置（占位值需在本机替换）：

```powershell
$env:ATLAS_QMT_USERDATA_PATH = 'C:\券商QMT\userdata_mini'
$env:ATLAS_QMT_ACCOUNT_ID = '本机填写的证券账户ID'
python scripts/brokers/qmt_probe.py
```

脚本只连接、订阅并查询资产／持仓是否成功，不输出金额、持仓、账户 ID 或路径，不提交任何委托。`connected=true` 只证明本地查询成功，不证明下单权限。下一步需要这台 Windows 主机及券商权限确认，才能实现账户绑定的桥接、人工确认委托、可卖量/T+1/交易时段与手数校验，以及回报和撤单联调。

## 官方依据

- [Binance 现货 API](https://developers.binance.com/en/docs/products/spot/rest-api)
- [Binance 官方签名示例与测试域名](https://github.com/binance/binance-signature-examples/blob/master/python/spot/spot.py)
- [OKX API v5：认证、模拟盘、现货交易](https://www.okx.com/docs-v5)
- [迅投 XtQuant 快速开始](https://dict.thinktrader.net/nativeApi/start_now.html)
- [迅投 XtTrader API](https://dict.thinktrader.net/nativeApi/xttrader.html)
- [迅投常见问题](https://dict.thinktrader.net/nativeApi/question_function.html)
- [国联证券官方 QMT 文档与账号申请](https://www.glsc.com.cn/qmt/document.html)
