from __future__ import annotations

import hashlib
import math
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yfinance as yf

from app.catalog import find_asset
from app.config import CACHE_DIR
from app.models import Asset, FundamentalMetric, FundamentalSection, FundamentalsResponse


class FundamentalsProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderSnapshot:
    data: dict[str, Any]
    source: str
    note: str


@dataclass(frozen=True)
class MetricSpec:
    key: str
    label: str
    section: str
    source_keys: tuple[str, ...]
    unit: str
    period: str
    description: str
    asset_classes: frozenset[str]
    scale: float = 1.0
    derived: bool = False
    currency_kind: str | None = None


CORPORATE = frozenset({"equity"})
FUND = frozenset({"etf"})
COMPANY_OR_FUND = CORPORATE | FUND
CRYPTO = frozenset({"crypto"})
MARKET = frozenset({"equity", "etf", "index", "crypto", "commodity", "forex", "unknown"})

SECTION_LABELS = {
    "valuation": "估值",
    "profitability": "盈利能力",
    "growth": "成长",
    "financial_health": "财务健康",
    "cashflow": "现金流",
    "distribution": "分红与回报",
    "fund": "基金指标",
    "market": "市场数据",
    "supply": "供给与流动性",
}

METRICS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "trailing_pe",
        "市盈率 PE (TTM)",
        "valuation",
        ("trailingPE",),
        "ratio",
        "TTM",
        "当前价格除以过去十二个月每股收益；亏损时通常无意义。",
        CORPORATE,
    ),
    MetricSpec(
        "dynamic_pe",
        "动态市盈率",
        "valuation",
        ("dynamicPE",),
        "ratio",
        "当前",
        "交易所行情源提供的动态市盈率，口径可能不同于 TTM。",
        CORPORATE,
    ),
    MetricSpec(
        "forward_pe",
        "预期市盈率",
        "valuation",
        ("forwardPE",),
        "ratio",
        "NTM",
        "当前价格除以市场一致预期的未来十二个月每股收益。",
        CORPORATE,
    ),
    MetricSpec(
        "price_to_book",
        "市净率 PB",
        "valuation",
        ("priceToBook",),
        "ratio",
        "MRQ",
        "当前价格除以最近一期每股净资产。",
        CORPORATE,
    ),
    MetricSpec(
        "price_to_sales",
        "市销率 PS",
        "valuation",
        ("priceToSalesTrailing12Months",),
        "ratio",
        "TTM",
        "市值除以过去十二个月营业收入。",
        CORPORATE,
    ),
    MetricSpec(
        "ev_to_revenue",
        "EV / 营收",
        "valuation",
        ("enterpriseToRevenue",),
        "ratio",
        "TTM",
        "企业价值除以过去十二个月营业收入。",
        CORPORATE,
    ),
    MetricSpec(
        "ev_to_ebitda",
        "EV / EBITDA",
        "valuation",
        ("enterpriseToEbitda",),
        "ratio",
        "TTM",
        "企业价值除以过去十二个月 EBITDA。",
        CORPORATE,
    ),
    MetricSpec(
        "peg_ratio",
        "PEG",
        "valuation",
        ("trailingPegRatio", "pegRatio"),
        "ratio",
        "预期",
        "市盈率相对预期盈利增长的比率；对增长假设非常敏感。",
        CORPORATE,
    ),
    MetricSpec(
        "earnings_yield",
        "盈利收益率",
        "valuation",
        ("_earningsYield",),
        "percent",
        "TTM",
        "市盈率的倒数，仅在盈利为正时计算。",
        CORPORATE,
        derived=True,
    ),
    MetricSpec(
        "book_to_market",
        "账面市值比",
        "valuation",
        ("_bookToMarket",),
        "percent",
        "MRQ",
        "市净率的倒数，用于价值因子研究。",
        CORPORATE,
        derived=True,
    ),
    MetricSpec(
        "price_to_fcf",
        "市值 / 自由现金流",
        "valuation",
        ("_priceToFreeCashflow",),
        "ratio",
        "TTM",
        "市值除以自由现金流，仅在自由现金流为正时计算。",
        CORPORATE,
        derived=True,
    ),
    MetricSpec(
        "fcf_yield",
        "自由现金流收益率",
        "valuation",
        ("_fcfYield",),
        "percent",
        "TTM",
        "自由现金流除以市值。",
        CORPORATE,
        derived=True,
    ),
    MetricSpec(
        "roe",
        "净资产收益率 ROE",
        "profitability",
        ("returnOnEquity",),
        "percent",
        "TTM",
        "净利润相对股东权益的收益率；高杠杆会放大该指标。",
        CORPORATE,
    ),
    MetricSpec(
        "roa",
        "总资产收益率 ROA",
        "profitability",
        ("returnOnAssets",),
        "percent",
        "TTM",
        "净利润相对总资产的收益率。",
        CORPORATE,
    ),
    MetricSpec(
        "gross_margin",
        "毛利率",
        "profitability",
        ("grossMargins",),
        "percent",
        "TTM",
        "毛利润占营业收入的比例。",
        CORPORATE,
    ),
    MetricSpec(
        "operating_margin",
        "营业利润率",
        "profitability",
        ("operatingMargins",),
        "percent",
        "TTM",
        "营业利润占营业收入的比例。",
        CORPORATE,
    ),
    MetricSpec(
        "net_margin",
        "净利率",
        "profitability",
        ("profitMargins",),
        "percent",
        "TTM",
        "归属净利润占营业收入的比例。",
        CORPORATE,
    ),
    MetricSpec(
        "ebitda_margin",
        "EBITDA 利润率",
        "profitability",
        ("ebitdaMargins",),
        "percent",
        "TTM",
        "EBITDA 占营业收入的比例。",
        CORPORATE,
    ),
    MetricSpec(
        "revenue_growth",
        "营收增长",
        "growth",
        ("revenueGrowth",),
        "percent",
        "同比",
        "最近报告期营业收入同比增长率。",
        CORPORATE,
    ),
    MetricSpec(
        "earnings_growth",
        "盈利增长",
        "growth",
        ("earningsGrowth",),
        "percent",
        "同比",
        "最近报告期盈利同比增长率。",
        CORPORATE,
    ),
    MetricSpec(
        "quarterly_earnings_growth",
        "季度盈利增长",
        "growth",
        ("earningsQuarterlyGrowth",),
        "percent",
        "同比",
        "最近季度盈利相对上年同期的增长率。",
        CORPORATE,
    ),
    MetricSpec(
        "revenue_per_share",
        "每股营收",
        "growth",
        ("revenuePerShare",),
        "currency",
        "TTM",
        "过去十二个月营业收入除以流通股数。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "trailing_eps",
        "每股收益 EPS",
        "growth",
        ("trailingEps",),
        "currency",
        "TTM",
        "过去十二个月归属普通股股东的每股收益。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "forward_eps",
        "预期每股收益",
        "growth",
        ("forwardEps",),
        "currency",
        "NTM",
        "市场一致预期的未来十二个月每股收益。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "book_value_per_share",
        "每股净资产",
        "financial_health",
        ("bookValue",),
        "currency",
        "MRQ",
        "最近一期普通股账面价值除以流通股数。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "current_ratio",
        "流动比率",
        "financial_health",
        ("currentRatio",),
        "ratio",
        "MRQ",
        "流动资产除以流动负债。",
        CORPORATE,
    ),
    MetricSpec(
        "quick_ratio",
        "速动比率",
        "financial_health",
        ("quickRatio",),
        "ratio",
        "MRQ",
        "剔除存货后的短期偿债能力。",
        CORPORATE,
    ),
    MetricSpec(
        "debt_to_equity",
        "负债权益比",
        "financial_health",
        ("debtToEquity",),
        "percent",
        "MRQ",
        "总债务相对股东权益的比例。",
        CORPORATE,
        scale=0.01,
    ),
    MetricSpec(
        "debt_to_assets",
        "债务 / 总资产",
        "financial_health",
        ("_debtToAssets",),
        "percent",
        "MRQ",
        "总债务除以总资产。",
        CORPORATE,
        derived=True,
    ),
    MetricSpec(
        "net_cash",
        "净现金",
        "financial_health",
        ("_netCash",),
        "currency",
        "MRQ",
        "现金及等价物减去总债务。",
        CORPORATE,
        derived=True,
        currency_kind="financial",
    ),
    MetricSpec(
        "net_debt_to_ebitda",
        "净债务 / EBITDA",
        "financial_health",
        ("_netDebtToEbitda",),
        "ratio",
        "TTM/MRQ",
        "净债务除以 EBITDA；负值代表净现金。",
        CORPORATE,
        derived=True,
    ),
    MetricSpec(
        "total_cash",
        "现金及等价物",
        "financial_health",
        ("totalCash",),
        "currency",
        "MRQ",
        "最近一期现金、现金等价物及数据源归并的短期投资。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "total_debt",
        "总债务",
        "financial_health",
        ("totalDebt",),
        "currency",
        "MRQ",
        "最近一期短期与长期有息债务。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "cash_per_share",
        "每股现金",
        "financial_health",
        ("totalCashPerShare",),
        "currency",
        "MRQ",
        "现金及等价物除以流通股数。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "operating_cashflow",
        "经营现金流",
        "cashflow",
        ("operatingCashflow",),
        "currency",
        "TTM",
        "经营活动产生的现金流量净额。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "free_cashflow",
        "自由现金流",
        "cashflow",
        ("freeCashflow",),
        "currency",
        "TTM",
        "经营现金流扣除资本性支出后的现金流。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "operating_cashflow_per_share",
        "每股经营现金流",
        "cashflow",
        ("_operatingCashflowPerShare",),
        "currency",
        "TTM",
        "经营现金流除以流通股数。",
        CORPORATE,
        derived=True,
        currency_kind="financial",
    ),
    MetricSpec(
        "free_cashflow_per_share",
        "每股自由现金流",
        "cashflow",
        ("_freeCashflowPerShare",),
        "currency",
        "TTM",
        "自由现金流除以流通股数。",
        CORPORATE,
        derived=True,
        currency_kind="financial",
    ),
    MetricSpec(
        "dividend_yield",
        "股息率",
        "distribution",
        ("dividendYield", "trailingAnnualDividendYield"),
        "percent",
        "TTM",
        "过去十二个月现金分红相对当前价格的比例。",
        CORPORATE,
    ),
    MetricSpec(
        "payout_ratio",
        "股利支付率",
        "distribution",
        ("payoutRatio",),
        "percent",
        "TTM",
        "现金分红相对净利润的比例。",
        CORPORATE,
    ),
    MetricSpec(
        "dividend_rate",
        "每股年度股息",
        "distribution",
        ("dividendRate", "trailingAnnualDividendRate"),
        "currency",
        "TTM",
        "数据源汇总的年度每股现金股息。",
        CORPORATE,
        currency_kind="quote",
    ),
    MetricSpec(
        "five_year_dividend_yield",
        "五年平均股息率",
        "distribution",
        ("fiveYearAvgDividendYield",),
        "percent",
        "5Y",
        "过去五年平均股息率。",
        CORPORATE,
        scale=0.01,
    ),
    MetricSpec(
        "fund_yield",
        "基金分配收益率",
        "fund",
        ("yield",),
        "percent",
        "TTM",
        "基金或 ETF 的过去十二个月分配收益率。",
        FUND,
    ),
    MetricSpec(
        "expense_ratio",
        "基金费率",
        "fund",
        ("annualReportExpenseRatio", "netExpenseRatio"),
        "percent",
        "年度",
        "年度报告或净管理费率。",
        FUND,
    ),
    MetricSpec(
        "nav_price",
        "基金净值",
        "fund",
        ("navPrice",),
        "currency",
        "当前",
        "最近可用的每份基金净值。",
        FUND,
        currency_kind="quote",
    ),
    MetricSpec(
        "three_year_return",
        "三年平均回报",
        "fund",
        ("threeYearAverageReturn",),
        "percent",
        "3Y",
        "基金过去三年的年化平均回报。",
        FUND,
    ),
    MetricSpec(
        "five_year_return",
        "五年平均回报",
        "fund",
        ("fiveYearAverageReturn",),
        "percent",
        "5Y",
        "基金过去五年的年化平均回报。",
        FUND,
    ),
    MetricSpec(
        "beta_3y",
        "三年 Beta",
        "fund",
        ("beta3Year",),
        "ratio",
        "3Y",
        "基金相对基准的三年 Beta。",
        FUND,
    ),
    MetricSpec(
        "market_cap",
        "总市值",
        "market",
        ("marketCap",),
        "currency",
        "当前",
        "当前价格乘以已发行股份或代币数量。",
        MARKET,
        currency_kind="quote",
    ),
    MetricSpec(
        "float_market_cap",
        "流通市值",
        "market",
        ("floatMarketCap",),
        "currency",
        "当前",
        "可流通股份对应的市场价值。",
        CORPORATE,
        currency_kind="quote",
    ),
    MetricSpec(
        "enterprise_value",
        "企业价值 EV",
        "market",
        ("enterpriseValue",),
        "currency",
        "当前/MRQ",
        "市值加净债务及其他调整后的企业价值。",
        CORPORATE,
        currency_kind="financial",
    ),
    MetricSpec(
        "shares_outstanding",
        "总股本",
        "market",
        ("sharesOutstanding",),
        "count",
        "当前",
        "当前已发行普通股数量。",
        COMPANY_OR_FUND,
    ),
    MetricSpec(
        "float_shares",
        "流通股本",
        "market",
        ("floatShares",),
        "count",
        "当前",
        "可公开交易的股份数量。",
        CORPORATE,
    ),
    MetricSpec(
        "institutional_ownership",
        "机构持股",
        "market",
        ("heldPercentInstitutions",),
        "percent",
        "最近披露",
        "机构投资者持股比例。",
        CORPORATE,
    ),
    MetricSpec(
        "insider_ownership",
        "内部人持股",
        "market",
        ("heldPercentInsiders",),
        "percent",
        "最近披露",
        "管理层及内部人持股比例。",
        CORPORATE,
    ),
    MetricSpec(
        "beta",
        "Beta",
        "market",
        ("beta",),
        "ratio",
        "5Y/月度",
        "相对市场基准的历史系统性风险暴露。",
        COMPANY_OR_FUND,
    ),
    MetricSpec(
        "current_price",
        "最新价格",
        "market",
        ("currentPrice", "regularMarketPrice"),
        "currency",
        "当前",
        "数据源最近可用成交或收盘价格。",
        MARKET,
        currency_kind="quote",
    ),
    MetricSpec(
        "fifty_two_week_high",
        "52 周最高",
        "market",
        ("fiftyTwoWeekHigh",),
        "currency",
        "52W",
        "过去 52 周最高价格。",
        MARKET,
        currency_kind="quote",
    ),
    MetricSpec(
        "fifty_two_week_low",
        "52 周最低",
        "market",
        ("fiftyTwoWeekLow",),
        "currency",
        "52W",
        "过去 52 周最低价格。",
        MARKET,
        currency_kind="quote",
    ),
    MetricSpec(
        "fifty_two_week_change",
        "52 周涨跌",
        "market",
        ("52WeekChange",),
        "percent",
        "52W",
        "当前价格相对约一年前价格的变化。",
        MARKET,
    ),
    MetricSpec(
        "fifty_day_average",
        "50 日均价",
        "market",
        ("fiftyDayAverage",),
        "currency",
        "50D",
        "最近 50 个交易日的平均价格。",
        MARKET,
        currency_kind="quote",
    ),
    MetricSpec(
        "two_hundred_day_average",
        "200 日均价",
        "market",
        ("twoHundredDayAverage",),
        "currency",
        "200D",
        "最近 200 个交易日的平均价格。",
        MARKET,
        currency_kind="quote",
    ),
    MetricSpec(
        "average_volume",
        "三月平均成交量",
        "market",
        ("averageVolume",),
        "count",
        "3M",
        "最近三个月平均成交量。",
        MARKET,
    ),
    MetricSpec(
        "average_volume_10d",
        "十日平均成交量",
        "market",
        ("averageVolume10days",),
        "count",
        "10D",
        "最近十个交易日平均成交量。",
        MARKET,
    ),
    MetricSpec(
        "circulating_supply",
        "流通供应量",
        "supply",
        ("circulatingSupply",),
        "count",
        "当前",
        "当前可流通的代币数量。",
        CRYPTO,
    ),
    MetricSpec(
        "total_supply",
        "总供应量",
        "supply",
        ("totalSupply",),
        "count",
        "当前",
        "数据源报告的代币总供应量。",
        CRYPTO,
    ),
    MetricSpec(
        "max_supply",
        "最大供应量",
        "supply",
        ("maxSupply",),
        "count",
        "当前",
        "协议定义的最大供应量；没有上限时为空。",
        CRYPTO,
    ),
    MetricSpec(
        "volume_24h",
        "24 小时成交额",
        "supply",
        ("volume24Hr", "volumeAllCurrencies"),
        "currency",
        "24H",
        "最近 24 小时的成交金额。",
        CRYPTO,
        currency_kind="quote",
    ),
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _first_number(data: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = _number(data.get(key))
        if value is not None:
            return value
    return None


def _positive_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _friendly_provider_error(error: Exception) -> str:
    message = str(error)
    if "Too Many Requests" in message or "Rate limited" in message:
        return "请求频率受限，请稍后刷新"
    return message[:180]


class YahooFundamentalsProvider:
    source = "Yahoo Finance"

    def supports(self, _asset: Asset) -> bool:
        return True

    def fetch(self, asset: Asset) -> ProviderSnapshot:
        ticker = yf.Ticker(asset.provider_symbol or asset.symbol)
        data: dict[str, Any] = {}
        errors: list[str] = []
        try:
            info = ticker.get_info()
            if isinstance(info, dict):
                data.update(info)
        except Exception as exc:
            errors.append(_friendly_provider_error(exc))

        fast_keys = {
            "currency": "currency",
            "marketCap": "marketCap",
            "sharesOutstanding": "shares",
            "currentPrice": "lastPrice",
            "fiftyTwoWeekHigh": "yearHigh",
            "fiftyTwoWeekLow": "yearLow",
            "52WeekChange": "yearChange",
            "fiftyDayAverage": "fiftyDayAverage",
            "twoHundredDayAverage": "twoHundredDayAverage",
            "averageVolume": "threeMonthAverageVolume",
            "averageVolume10days": "tenDayAverageVolume",
            "regularMarketVolume": "lastVolume",
        }
        try:
            fast = ticker.get_fast_info()
            for target, source in fast_keys.items():
                if data.get(target) is not None:
                    continue
                try:
                    value = fast.get(source)
                except Exception:
                    continue
                if value is not None:
                    data[target] = value
        except Exception as exc:
            errors.append(_friendly_provider_error(exc))

        if not any(_number(value) is not None for value in data.values()):
            detail = errors[0] if errors else "数据源没有返回数值字段"
            raise FundamentalsProviderError(f"Yahoo 基本面请求失败: {detail}")
        return ProviderSnapshot(
            data=data,
            source=self.source,
            note="公司、基金与市场快照字段由 Yahoo Finance 标准化。",
        )


class EastmoneyFundamentalsProvider:
    source = "Eastmoney"
    url = "https://push2.eastmoney.com/api/qt/stock/get"

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=8,
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 AtlasQuant/1.0"},
        )

    def supports(self, asset: Asset) -> bool:
        return asset.exchange in {"SSE", "SZSE", "HKEX"} and asset.asset_class == "equity"

    @staticmethod
    def _security_id(asset: Asset) -> tuple[str, float]:
        code = asset.symbol.split(".")[0]
        if asset.exchange == "SSE":
            return f"1.{code}", 100.0
        if asset.exchange == "SZSE":
            return f"0.{code}", 100.0
        return f"116.{code.zfill(5)}", 1000.0

    def fetch(self, asset: Asset) -> ProviderSnapshot:
        security_id, price_scale = self._security_id(asset)
        try:
            response = self.client.get(
                self.url,
                params={
                    "secid": security_id,
                    "fields": "f43,f57,f58,f60,f116,f117,f162,f167",
                },
            )
            response.raise_for_status()
            payload = response.json().get("data") or {}
        except Exception as exc:
            raise FundamentalsProviderError(f"东方财富估值快照请求失败: {exc}") from exc
        if not payload:
            raise FundamentalsProviderError("东方财富估值快照没有返回数据")

        data: dict[str, Any] = {}
        mappings = {
            "dynamicPE": ("f162", 100.0),
            "priceToBook": ("f167", 100.0),
            "marketCap": ("f116", 1.0),
            "floatMarketCap": ("f117", 1.0),
            "currentPrice": ("f43", price_scale),
        }
        for target, (field, scale) in mappings.items():
            value = _number(payload.get(field))
            if target in {"dynamicPE", "priceToBook"} and value is not None and value <= 0:
                continue
            if value is not None and value > -1e10:
                data[target] = value / scale
        if not data:
            raise FundamentalsProviderError("东方财富估值字段当前不可用")
        data["currency"] = asset.currency
        return ProviderSnapshot(
            data=data,
            source=self.source,
            note="A/H 股动态 PE、PB、市值与价格来自东方财富实时估值快照。",
        )


class FundamentalsService:
    CACHE_TTL_SECONDS = 6 * 60 * 60

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR / "fundamentals",
        providers: list[Any] | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.providers = providers or [EastmoneyFundamentalsProvider(), YahooFundamentalsProvider()]
        self._lock = threading.Lock()

    def _cache_path(self, asset: Asset) -> Path:
        digest = hashlib.sha256(f"{asset.symbol}|{asset.asset_class}".encode()).hexdigest()[
            :16
        ]
        return self.cache_dir / f"{digest}.json"

    @staticmethod
    def _read_cache(path: Path) -> FundamentalsResponse | None:
        if not path.is_file():
            return None
        try:
            return FundamentalsResponse.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    @staticmethod
    def _is_fresh(path: Path) -> bool:
        age = datetime.now(UTC).timestamp() - path.stat().st_mtime
        return age <= FundamentalsService.CACHE_TTL_SECONDS

    @staticmethod
    def _write_cache(path: Path, response: FundamentalsResponse) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(response.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(path)

    @staticmethod
    def _derive(data: dict[str, Any]) -> dict[str, Any]:
        result = dict(data)
        trailing_pe = _first_number(result, ("trailingPE",))
        price_to_book = _first_number(result, ("priceToBook",))
        market_cap = _first_number(result, ("marketCap",))
        free_cashflow = _first_number(result, ("freeCashflow",))
        operating_cashflow = _first_number(result, ("operatingCashflow",))
        total_cash = _first_number(result, ("totalCash",))
        total_debt = _first_number(result, ("totalDebt",))
        total_assets = _first_number(result, ("totalAssets",))
        ebitda = _first_number(result, ("ebitda",))
        shares = _first_number(result, ("sharesOutstanding",))

        result["_earningsYield"] = _positive_ratio(1.0, trailing_pe)
        result["_bookToMarket"] = _positive_ratio(1.0, price_to_book)
        result["_fcfYield"] = _positive_ratio(free_cashflow, market_cap)
        result["_priceToFreeCashflow"] = _positive_ratio(market_cap, free_cashflow)
        if total_cash is not None and total_debt is not None:
            result["_netCash"] = total_cash - total_debt
            if ebitda is not None and ebitda > 0:
                result["_netDebtToEbitda"] = (total_debt - total_cash) / ebitda
        result["_debtToAssets"] = _positive_ratio(total_debt, total_assets)
        result["_operatingCashflowPerShare"] = _positive_ratio(operating_cashflow, shares)
        result["_freeCashflowPerShare"] = _positive_ratio(free_cashflow, shares)
        return result

    def _build(
        self,
        asset: Asset,
        data: dict[str, Any],
        sources: list[str],
        notes: list[str],
        errors: list[str],
    ) -> FundamentalsResponse:
        now = int(datetime.now(UTC).timestamp())
        enriched = self._derive(data)
        quote_currency = str(data.get("currency") or asset.currency).upper()
        financial_currency = str(data.get("financialCurrency") or quote_currency).upper()
        specs = [spec for spec in METRICS if asset.asset_class in spec.asset_classes]
        grouped: dict[str, list[FundamentalMetric]] = {}
        available = 0
        for spec in specs:
            value = _first_number(enriched, spec.source_keys)
            if (
                spec.key
                in {
                    "trailing_pe",
                    "dynamic_pe",
                    "forward_pe",
                    "price_to_book",
                    "price_to_sales",
                    "peg_ratio",
                }
                and value is not None
                and value <= 0
            ):
                value = None
            if value is not None:
                value *= spec.scale
                available += 1
            currency = None
            if spec.currency_kind == "quote":
                currency = quote_currency
            elif spec.currency_kind == "financial":
                currency = financial_currency
            grouped.setdefault(spec.section, []).append(
                FundamentalMetric(
                    key=spec.key,
                    label=spec.label,
                    value=value,
                    unit=spec.unit,
                    period=spec.period,
                    description=spec.description,
                    derived=spec.derived,
                    currency=currency,
                )
            )
        total = len(specs)
        coverage = available / total if total else 0.0
        status = (
            "not_applicable"
            if not total
            else "unavailable"
            if available == 0
            else "available"
            if coverage >= 0.65
            else "partial"
        )
        warnings = [
            "这是当前基本面快照，不是 point-in-time 历史财报；不得直接用于历史回测。",
            "不同市场和数据源的会计口径可能不同；缺失字段保持为空，不进行推测填充。",
        ]
        if errors:
            warnings.append("部分数据源不可用：" + "；".join(errors[:2]))
        if asset.asset_class in {"crypto", "commodity", "forex", "index"}:
            warnings.append("该资产没有公司层面的 PE、PB、ROE 等指标，仅展示适用的市场或供给数据。")
        sections = [
            FundamentalSection(id=section, label=SECTION_LABELS[section], metrics=metrics)
            for section, metrics in grouped.items()
        ]
        as_of = _first_number(data, ("regularMarketTime",))
        return FundamentalsResponse(
            asset=asset,
            status=status,
            source=" + ".join(dict.fromkeys(sources)) if sources else "unavailable",
            source_note=" ".join(notes) if notes else "当前数据源未返回可验证的金融指标。",
            fetched_at=now,
            as_of=int(as_of) if as_of is not None else now if available else None,
            currency=quote_currency,
            financial_currency=financial_currency,
            available_metric_count=available,
            total_metric_count=total,
            coverage=coverage,
            sections=sections,
            warnings=warnings,
        )

    def fetch(
        self,
        symbol: str,
        asset_class: str,
        refresh: bool = False,
    ) -> FundamentalsResponse:
        asset = find_asset(symbol, asset_class)
        if asset.asset_class == "unknown":
            asset.asset_class = asset_class
        cache_path = self._cache_path(asset)
        with self._lock:
            cached = self._read_cache(cache_path)
            if cached and not refresh and self._is_fresh(cache_path):
                return cached.model_copy(update={"cache_hit": True})

            merged: dict[str, Any] = {}
            sources: list[str] = []
            notes: list[str] = []
            errors: list[str] = []
            for provider in self.providers:
                if not provider.supports(asset):
                    continue
                try:
                    snapshot = provider.fetch(asset)
                except FundamentalsProviderError as exc:
                    errors.append(str(exc))
                    continue
                sources.append(snapshot.source)
                notes.append(snapshot.note)
                for key, value in snapshot.data.items():
                    if merged.get(key) is None and value is not None:
                        merged[key] = value

            if not merged and cached:
                return cached.model_copy(
                    update={
                        "cache_hit": True,
                        "is_stale": True,
                        "warnings": [*cached.warnings, "实时刷新失败，当前显示上次可用快照。"],
                    }
                )
            response = self._build(asset, merged, sources, notes, errors)
            if response.available_metric_count:
                self._write_cache(cache_path, response)
            return response
