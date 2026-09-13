export const STRATEGY_LANGUAGES = [
  { id: 'python', label: 'Python', extensions: ['.py'], environment: 'Atlas Python SDK', template: `from atlas_strategy_sdk import BaseStrategy, StrategyContext, TargetPosition


class MyStrategy(BaseStrategy):
    """收盘价高于 20 日均线时持有 20% 仓位。"""

    def generate_targets(self, ctx: StrategyContext):
        symbol = "BTC-USD"
        bars = ctx.history(symbol, 20)
        if len(bars) < 20:
            return []
        average = sum(bar.close for bar in bars) / 20
        weight = 0.2 if bars[-1].close > average else 0.0
        return [TargetPosition(symbol, weight, 0.8, "SMA_20")]
` },
  { id: 'javascript', label: 'JavaScript', extensions: ['.js', '.mjs'], environment: '独立信号函数 · 需接入行情', template: `// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
export function targetWeight(closes) {
  if (closes.length < 20) return 0;
  const average = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  return closes.at(-1) > average ? 0.2 : 0;
}
` },
  { id: 'typescript', label: 'TypeScript', extensions: ['.ts'], environment: '独立信号函数 · 需接入行情', template: `// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
export function targetWeight(closes: number[]): number {
  if (closes.length < 20) return 0;
  const average = closes.slice(-20).reduce((a, b) => a + b, 0) / 20;
  return closes[closes.length - 1] > average ? 0.2 : 0;
}
` },
  { id: 'cpp', label: 'C++', extensions: ['.cpp', '.cc', '.cxx'], environment: '独立信号函数 · C++17', template: `#include <vector>
#include <numeric>

// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
double target_weight(const std::vector<double>& closes) {
    if (closes.size() < 20) return 0.0;
    const double average = std::accumulate(closes.end() - 20, closes.end(), 0.0) / 20;
    return closes.back() > average ? 0.2 : 0.0;
}
` },
  { id: 'c', label: 'C', extensions: ['.c'], environment: '独立信号函数 · C11', template: `#include <stddef.h>

// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
double target_weight(const double *closes, size_t count) {
    if (closes == NULL || count < 20) return 0.0;
    double sum = 0.0;
    for (size_t i = count - 20; i < count; ++i) sum += closes[i];
    return closes[count - 1] > sum / 20.0 ? 0.2 : 0.0;
}
` },
  { id: 'java', label: 'Java', extensions: ['.java'], environment: '独立信号函数 · JVM', template: `// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
class Strategy {
    public static double targetWeight(double[] closes) {
        if (closes.length < 20) return 0.0;
        double sum = 0.0;
        for (int i = closes.length - 20; i < closes.length; i++) sum += closes[i];
        return closes[closes.length - 1] > sum / 20.0 ? 0.2 : 0.0;
    }
}
` },
  { id: 'csharp', label: 'C#', extensions: ['.cs'], environment: '独立信号函数 · .NET', template: `// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
public static class Strategy {
    public static double TargetWeight(double[] closes) {
        if (closes.Length < 20) return 0.0;
        double sum = 0.0;
        for (int i = closes.Length - 20; i < closes.Length; i++) sum += closes[i];
        return closes[closes.Length - 1] > sum / 20.0 ? 0.2 : 0.0;
    }
}
` },
  { id: 'go', label: 'Go', extensions: ['.go'], environment: '独立信号函数 · Go', template: `package strategy

// TargetWeight 返回目标仓位；输入收盘价按时间升序排列，不下单。
func TargetWeight(closes []float64) float64 {
    if len(closes) < 20 { return 0 }
    sum := 0.0
    for _, price := range closes[len(closes)-20:] { sum += price }
    if closes[len(closes)-1] > sum/20 { return 0.2 }
    return 0
}
` },
  { id: 'rust', label: 'Rust', extensions: ['.rs'], environment: '独立信号函数 · Rust', template: `// 输入按时间升序排列的收盘价，返回目标仓位；不下单。
pub fn target_weight(closes: &[f64]) -> f64 {
    if closes.len() < 20 { return 0.0; }
    let average = closes[closes.len()-20..].iter().sum::<f64>() / 20.0;
    if closes[closes.len()-1] > average { 0.2 } else { 0.0 }
}
` },
  { id: 'r', label: 'R', extensions: ['.r'], environment: '独立信号函数 · R', template: `# 输入按时间升序排列的收盘价，返回目标仓位；不下单。
target_weight <- function(closes) {
  if (length(closes) < 20) return(0)
  average <- mean(tail(closes, 20))
  if (tail(closes, 1) > average) 0.2 else 0
}
` },
  { id: 'julia', label: 'Julia', extensions: ['.jl'], environment: '独立信号函数 · Julia', template: `using Statistics

# 输入按时间升序排列的收盘价，返回目标仓位；不下单。
function target_weight(closes::AbstractVector{<:Real})
    length(closes) < 20 && return 0.0
    average = mean(closes[end-19:end])
    return closes[end] > average ? 0.2 : 0.0
end
` },
  { id: 'pine', label: 'Pine Script', extensions: ['.pine'], environment: 'TradingView · 需在目标平台验证', template: `//@version=6
strategy("SMA 20", overlay=true, default_qty_type=strategy.percent_of_equity, default_qty_value=20)
average = ta.sma(close, 20)
if barstate.isconfirmed and not na(average)
    if close > average
        strategy.entry("Long", strategy.long)
    else
        strategy.close("Long")
plot(average, "SMA 20")
` },
  { id: 'mql4', label: 'MQL4', extensions: ['.mq4'], environment: 'MetaTrader 4 · 需在目标平台验证', template: `#property strict

// 只计算已收盘 K 线的目标仓位，不发送订单。
double TargetWeight() {
    if (iBars(NULL, 0) < 21) return 0.0;
    double sum = 0.0;
    for (int i = 1; i <= 20; i++) sum += iClose(NULL, 0, i);
    return iClose(NULL, 0, 1) > sum / 20.0 ? 0.2 : 0.0;
}
void OnTick() {
    Comment("Target weight: ", TargetWeight());
}
` },
  { id: 'mql5', label: 'MQL5', extensions: ['.mq5'], environment: 'MetaTrader 5 · 需在目标平台验证', template: `#property strict

// 只计算已收盘 K 线的目标仓位，不发送订单。
double TargetWeight() {
    double closes[];
    if (CopyClose(_Symbol, _Period, 1, 20, closes) != 20) return 0.0;
    double sum = 0.0;
    for (int i = 0; i < 20; i++) sum += closes[i];
    return closes[19] > sum / 20.0 ? 0.2 : 0.0;
}
void OnTick() {
    Comment("Target weight: ", TargetWeight());
}
` },
] as const
export type StrategyLanguage = typeof STRATEGY_LANGUAGES[number]['id']
export const languageForFile = (name: string) => STRATEGY_LANGUAGES.find((language) => language.extensions.some((extension) => name.toLowerCase().endsWith(extension)))
