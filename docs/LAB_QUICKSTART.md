# 策略实验室使用说明

1. 登录后进入「策略实验室 → 我的策略」。选择「新建策略」打开空白编辑器，或「导入代码」读取 UTF-8 源码文件。
2. 编写受限 Python，定义 `target_bps(index, close, sma)` 并返回 0 到 9500 之间的整数仓位，5000 表示 50%。编辑器支持其他语言的源码保存与下载。
3. 在「回测设置」选择标的、周期、行情源和资金。日期留空时使用已发布的行情范围。费用、复权和仓位约束位于「高级设置」。准备行情的方法见[浏览器计算说明](BROWSER_COMPUTE.md)。
4. 点击「保存策略」，将源码和设置保存到当前账号。点击「检查代码」查看兼容性诊断，再点击「运行回测」。结果显示在编辑页内。已创建策略可以测试未保存的编辑。
5. 打开「历史回测」查看最近 50 次成功运行及对应的参数和源码摘要。历史结果标明「未经 ZKP 验证」。正式验真从现有报告流程进入。

编辑器可打开 AI 助手。配置模型并授权发送后，助手会收到当前代码与问题。查看建议后手动应用修改。账户密钥应通过独立的账号和服务设置管理。

已有模板、图形化工作流和项目记录仍保留。现行实验室提供代码工作台，其他回测及交易入口见[当前工作流](CURRENT_WORKSPACE_WALKTHROUGH.md)。

## 四行业多股回测

打开「策略实验室 → 我的策略 → 打开多股回测」，选择半导体、军工、商业航天或机器人，再点「运行多股回测」。每次按该行业预设股票池读取 15 分钟行情，从同一个 100 万元模拟账户逐笔成交。结果可查看扣费后收益、最大回撤、日权益及逐笔记录，也可下载含配置和行情 SHA-256 摘要的 JSON。

首次使用需在后端机器解压已经交付的 `atlas-sector-joint-strategies-20261113.zip`，并使用 Python 3.12 安装固定依赖。默认从项目的 `.artifacts/user-strategies/atlas-sector-joint-strategies-20261113/` 读取。若安装在其他位置，在启动后端时设置 `ATLAS_SECTOR_REPLAY_ROOT` 为解压后的绝对目录。容器环境需在与后端同系统和架构的环境创建该目录的虚拟环境，并将目录以只读方式挂载给 API。

```sh
python3.12 -m zipfile -e /path/to/atlas-sector-joint-strategies-20261113.zip .artifacts/user-strategies
sector_dir="$PWD/.artifacts/user-strategies/atlas-sector-joint-strategies-20261113"
python3.12 -m venv "$sector_dir/.venv-sector"
"$sector_dir/.venv-sector/bin/python" -m pip install -r "$sector_dir/tools/limit_up_study/requirements-sector-strategies.txt"
```

目前多股入口执行服务端安装的四个预设，使用 2025-01-02 至 2026-11-12 的冻结行情和同区间已选参数。佣金 0.10%、滑点 0.05%，卖出另计 0.05% 印花税。组合收益属于历史回放，未生成零知识证明。
