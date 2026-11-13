"""Export readable research evidence; results are never hardcoded."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd


def write_report(output,p,results,curves,benchmark,provenance):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.style.use('default')
    plt.rcParams.update({'axes.spines.top':False,'axes.spines.right':False,'font.size':10,'font.family':'DejaVu Sans'})
    fig,axes=plt.subplots(2,1,figsize=(12,7),sharex=True,gridspec_kw={'height_ratios':[2,1]},layout='constrained')
    names={'leader_peer':'Predicted leader -> peers','momentum_peer_control':'Momentum peers control','double_impact':'Double execution impact'}
    colors={'leader_peer':'#176b91','momentum_peer_control':'#c28e45','double_impact':'#73828c'}
    all_curves={**curves,'hs300':benchmark.unit_net_value}
    for key,series in all_curves.items():
        color=colors.get(key,'#9a526e');label=names.get(key,'CSI 300 (100% price index)')
        axes[0].plot(series.index,series,label=label,color=color,lw=1.7)
        peaks=np.maximum.accumulate(np.r_[1,series.to_numpy()])[1:]
        axes[1].plot(series.index,100*(series.to_numpy()/peaks-1),color=color,lw=1)
    axes[0].set_title('A-share leader / peer walk-forward experiment | 2023-01-03 to '+p.test_end,loc='left',weight='bold')
    axes[0].set_ylabel('Net asset value (start = 1)');axes[1].set_ylabel('Drawdown (%)')
    axes[0].legend(loc='upper left',fontsize=9)
    for ax in axes:ax.grid(alpha=.15)
    fig.savefig(output/'equity_drawdown.png',dpi=160);plt.close(fig)
    signal=json.loads((output/'prediction_metrics.json').read_text())
    pct=lambda x:f'{x:.2%}'
    labels={'leader_peer':'预测龙头→同行','momentum_peer_control':'动量同行对照','double_impact':'双倍冲击成本','hs300':'沪深300价格指数（100%仓位）'}
    rows=['| 方案 | 总收益 | 年化收益 | 最大回撤 | 夏普（无风险0） | 买入笔数 |',
          '|---|---:|---:|---:|---:|---:|']
    for key,data in results.items():
        rows.append(f"| {labels[key]} | {pct(data['total_return'])} | {pct(data['annual_return'])} | {pct(data['max_drawdown'])} | {data['sharpe_zero_rf']:.2f} | {data.get('buy_fills','—')} |")
    main=results['leader_peer'];control=results['momentum_peer_control']
    interpretation=('本次扣费后收益为负，当前版本不能作为盈利策略部署。' if main['total_return']<0 else
        '本次样本扣费后收益为正，但行业分类不是历史时点数据，收益仍需要独立数据复核。')
    comparison=('预测筛选的收益高于动量对照。' if main['total_return']>control['total_return'] else
        '预测筛选没有超过动量对照，涨停预测命中率没有转化为更好的组合收益。')
    annual=['| 年份 | 预测龙头→同行 | 动量对照 | 沪深300 |','|---|---:|---:|---:|']
    for year,value in main['yearly_returns'].items():
        annual.append(f"| {year} | {pct(value)} | {pct(control['yearly_returns'][year])} | {pct(results['hs300']['yearly_returns'][year])} |")
    ci=main['confidence'].get('annual_return_95',[0,0])
    report=f'''# A 股龙头涨停预测与同行补涨策略：可复现研究

{interpretation}{comparison}

## 数据与检验范围

- 实际回测区间：2023-01-03 至 {p.test_end}，{main['sessions']} 个交易日；初始资金 100 万元。
- 数据：本机 RQAlpha 原生真实 A 股日线 bundle，{provenance['universe']} 只可识别沪深股票、{provenance['industries']} 个证监会行业。每日按历史上市年龄、ST 状态、成交额筛选；不是每天都交易所有股票。包含 bundle 提供的历史退市记录，但不保证已覆盖全部历史退市公司。
- 数据截止 2026-10-30。当前日期更晚，不能把最新导出的历史信号当成明日荐股。
- 行业分类来自 bundle 当前快照，**没有历史时点行业变迁**；行业和证券覆盖仍有选择偏差。下述“样本外”只指模型训练时间隔离，不表示数据完全没有偏差。
- 使用原始成交价和历史涨跌停价；回报特征用原生除权参考价 prev_close，持仓公司行动由 RQAlpha 账户处理。未使用后复权绝对价格选股。

## 策略规则（本轮固定，未按测试收益调参）

1. T 日收盘识别行业内价格/流动性龙头：20日涨幅排名55% + 20日均成交额排名30% + 5日涨幅排名15%；至少5个合格行业成员。龙头定义不是基本面市占率龙头。
2. 12个价量及行业特征进入正则逻辑回归。每月仅使用之前3年数据训练；训练标签对应的次日也必须早于预测月份。预测的是**次日盘中触及涨停**，另外统计收盘封板。
3. 阈值为训练集预测分数的80%分位数与8%的较大值；每日按分数排序。预测后立即按 T 日信息选择同行最多2只非龙头，要求20日涨幅非负、收于20日均线上、未充分大涨；不等待观察次日龙头是否真的涨停。
4. T+1 开盘集合竞价模拟买入。竞价前按公开的除权参考价、涨停价和既有仓位确定全部限价与数量，买入限价最高为参考价+3%且低于涨停1分钱。每股目标10%、每行业20%、最多6股、总目标仓位60%。单笔不超过T日20日均成交额的0.5%。按限价预留预算；不使用最终开盘价、当天全天成交量、同一竞价卖出资金或成交结果决定新订单；未成交不临时换股，余单不延至收盘撮合。
5. 入场跳空高于3%或开盘涨停不买；停牌/无开盘价不成交。持有3个交易日后在下一开盘退出；收盘触发5%止损或8%止盈，次日开盘退出，禁止买入当日卖出。停牌或跌停无法卖出时顺延，**最多3日是计划期限，不是无法成交时的保证**。
6. 原生RQAlpha处理T+1、证券最小申报数量、公司行动和账户资金。集合竞价使用日线开盘价；日线数据没有真实竞价盘口/排队，无法证明这些订单实盘都能成交。

## 费用

双边佣金万3（含交易规费）、每单最低5元；按历史日期计卖方印花税（2023-08-28前千1，之后万5）；双边过户费十万1；开启原生持股期限差异化红利税。额外每边10bp冲击成本，通过原生交易成本的other_fees实际扣款。原生集合竞价不应用价格滑点，故不能仅配置slippage并假称已扣费。压力测试将冲击成本提高到每边20bp。风险指标年化因子252，夏普无风险利率设为0。[印花税减半公告](https://shanghai.chinatax.gov.cn/zcfw/zcfgk/yhs/202308/t468451.html)。

## 实际扣费回测

{chr(10).join(rows)}

主策略累计成交费用与模拟冲击成本：{main['fees_and_impact']:,.2f} 元；平均收盘仓位 {pct(main['average_exposure'])}；期末仍有 {len(main['end_positions'])} 个持仓，按市值计入收益，没有免费强平。沪深300为不扣交易费的价格指数，仓位100%，风险暴露与本策略不同；动量对照使用相同股票池、同行筛选、仓位和费用，但不按涨停概率筛选，而按龙头20日动量排序。

{chr(10).join(annual)}

## 预测命中率与交易收益是两回事

全体合格候选龙头的次日触板率为 {pct(signal['touch_base_rate'])}；预测筛选得到 {signal['selected_leader_days']} 个“股票-日期”信号，触板率 {pct(signal['touch_precision'])}，收盘封板率 {pct(signal['sealed_precision'])}。这些不是独立交易、不是盈利胜率，也不是每次一定涨停的概率保证。

真正引发同行买入的独立龙头-日期共 {main.get('executed_leader_days',0)} 个；这些龙头次日触板率 {pct(main.get('executed_leader_touch_precision',0))}，封板率 {pct(main.get('executed_leader_sealed_precision',0))}。即使龙头触板，同行买入仍可能亏损。

按交易日分组并以20日连续块重抽样，预测触板率区间为 {signal.get('precision_date_block_95')}。组合日收益20日移动块bootstrap（1000次）的年化收益95%区间为 [{pct(ci[0])}, {pct(ci[1])}]。此区间仅描述样本内重抽样不确定性，不包含行业分类错误、未来市场变化及真实成交误差。

## 证据文件

- `parameters.json`、`models.json`、`walk_forward.json`：参数、逐月模型、严格训练截止日。
- `forecasts.csv.gz`：预测与评估标签（**标签仅评估，传入交易回调前移除**）。
- 各方案目录 `fills.csv`、`equity.csv`、`execution_audit.csv`、`metrics.json`、`engine.log`：成交、净值和执行记录。日线引擎的原生时间字段为00:00，执行阶段另标记OPEN_AUCTION，不伪造真实分钟成交时间。
- `provenance.json`：数据快照、源码SHA256；`latest_signal_plan.json`：历史末日模拟信号，非当前实盘订单。
- `equity_drawdown.png`：净值和回撤。

尚需独立的历史行业成分、完整退市/ST数据、竞价或分钟数据复核及模拟盘验证。本程序没有券商登录、没有实盘下单接口。
'''
    (output/'REPORT.md').write_text(report)
