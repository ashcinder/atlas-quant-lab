import copy
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import rqalpha_reports as reports
from app.lab_strategies import LabMultiSettings
from app.sandbox import RunnerFailure

DAYS = ["2024-12-30", "2024-12-31", "2025-01-02", "2025-01-03"]


def stamp(day):
    return int(
        datetime.fromisoformat(day + "T15:00:00")
        .replace(tzinfo=ZoneInfo("Asia/Shanghai"))
        .timestamp()
    )


@pytest.fixture
def sample():
    nav = [1.0, 1.1, 1.045, 1.254]
    pnl = [0.0, 100.0, -55.0, 209.0]
    equity = [
        {
            **dict.fromkeys(reports.EQUITY_FIELDS, 0.0),
            "time": stamp(day),
            "equity": 1000 * value,
            "cash": 1000 * value,
            "market_value": 0.0,
            "net_value": value,
            "daily_pnl": profit,
        }
        for day, value, profit in zip(DAYS, nav, pnl, strict=True)
    ]
    native = {
        "total_returns": 0.254,
        "annualized_returns": 0.25,
        "unit_net_value": 1.254,
        "win_rate": 0.5,
        "sharpe": 0.4,
        "sortino": 0.5,
        "max_drawdown": 0.05,
        "volatility": 0.2,
        "downside_risk": 0.1,
        "alpha": 0.1,
        "beta": 0.7,
        "information_ratio": 0.2,
        "tracking_error": 0.1,
        "excess_max_drawdown": 0.1,
    }
    result = {
        "equity": equity,
        "trades": [],
        "positions": [],
        "rejections": [],
        "corporate_actions": [],
        "native_metrics": native,
    }
    raw = {
        "schema_version": reports.RAW_SCHEMA,
        "positions": [],
        "benchmark": [],
        "accounts": [
            {
                **dict.fromkeys(reports.EQUITY_FIELDS, 0.0),
                "time": point["time"],
                "account_type": "stock",
                "cash": point["cash"],
                "equity": point["equity"],
                "market_value": 0,
                "margin": None,
                "fee": 0,
                "daily_pnl": point["daily_pnl"],
            }
            for point in equity
        ],
        "logs": [],
        "logs_truncated": False,
        "risk_free_rate": 0.02,
    }
    settings = LabMultiSettings(
        engine_id="rqalpha",
        symbols=["600519.SS", "000001.SZ"],
        initial_capital=1000,
    )
    market = {"sessions": DAYS, "full_years": []}
    return result, raw, settings, market


def build(sample):
    result, raw, settings, market = sample
    return reports.build_report(result, settings, market, raw)


def metrics(report):
    return {row["key"]: row for row in report["metrics"]}


def test_nineteen_metrics_use_native_values_and_explain_missing_benchmark(sample):
    value = build(sample)
    report = value["report"]
    mapped = metrics(report)
    assert len(mapped) == 19
    assert mapped["sharpe"]["value"] == 0.4
    assert mapped["alpha"]["value"] is None
    assert "基准" in mapped["alpha"]["reason"]
    assert mapped["win_rate"]["value"] == 0.5
    assert mapped["year_win_rate"]["value"] == 1
    assert mapped["month_win_rate"]["value"] == 1
    assert all(point["benchmark_return"] is None for point in report["series"])
    assert report["performance"] == {"enabled": False}
    assert report["conventions"]["risk_free_rate"] == 0.02
    assert report["tables"]["positions"] == {"count": 0, "recorded": True}
    assert value["report_rows"]["logs"] == []


def test_years_compound_without_resetting_the_january_start_to_first_close(sample):
    report = build(sample)["report"]
    rows = report["annual_returns"]
    assert [row["year"] for row in rows] == [2024, 2025]
    assert rows[0]["strategy"] == pytest.approx(0.1)
    assert rows[1]["strategy"] == pytest.approx(0.14)
    assert (1 + rows[0]["strategy"]) * (1 + rows[1]["strategy"]) - 1 == pytest.approx(0.254)
    assert all(row["partial"] for row in rows)
    assert all(row["benchmark"] is None for row in rows)
    sample[3]["full_years"] = [2024]
    assert not build(sample)["report"]["annual_returns"][0]["partial"]


def test_benchmark_curve_is_arithmetic_but_drawdown_definition_is_geometric(sample):
    result, raw, settings, _ = sample
    settings.benchmark = "000300.SS"
    values = [1.0, 1.05, 1.08, 1.1]
    raw["benchmark"] = [
        {"time": point["time"], "net_value": value}
        for point, value in zip(result["equity"], values, strict=True)
    ]
    result["native_metrics"]["benchmark_total_returns"] = 0.1
    result["native_metrics"]["benchmark_annualized_returns"] = 0.2
    report = build(sample)["report"]
    assert report["benchmark"]["name"] == "沪深300"
    assert report["series"][-1]["excess_return"] == pytest.approx(0.154)
    assert metrics(report)["excess_max_drawdown"]["value"] == 0.1
    assert "净值/基准净值" in metrics(report)["excess_max_drawdown"]["definition"]
    assert report["annual_returns"][1]["benchmark"] == pytest.approx(1.1 / 1.05 - 1)


def test_nav_not_equity_drives_returns_with_external_cash_flows(sample):
    result, raw, _, _ = sample
    for point, account in zip(result["equity"], raw["accounts"], strict=True):
        point["equity"] *= 2
        point["cash"] *= 2
        account["equity"] *= 2
        account["cash"] *= 2
    report = build(sample)["report"]
    assert report["series"][-1]["strategy_return"] == pytest.approx(0.254)
    assert report["series"][-1]["daily_pnl"] == 209
    assert report["drawdown"] == {
        "start": stamp(DAYS[1]),
        "end": stamp(DAYS[2]),
        "value": pytest.approx(0.05),
    }


def test_host_headline_returns_and_drawdown_match_the_native_nav_with_cash_flows(sample):
    from app.rqalpha_backtests import ENGINE_VERSION, validate_result

    result, raw, settings, market = sample
    for point, account in zip(result["equity"], raw["accounts"], strict=True):
        point["equity"] *= 2
        point["cash"] *= 2
        account["equity"] *= 2
        account["cash"] *= 2
    result.update(engine_version=ENGINE_VERSION, matching_type="current_bar", report_data=raw)
    market["window"] = {"start": DAYS[0], "end": DAYS[-1]}
    validated = validate_result(result, settings, market)
    assert validated["total_return"] == pytest.approx(0.254)
    assert validated["max_drawdown"] == pytest.approx(0.05)
    assert validated["final_equity"] == pytest.approx(2508)


def test_summary_nav_checks_the_native_six_decimal_precision(sample):
    result, raw, settings, market = sample
    point, account = result["equity"][-1], raw["accounts"][-1]
    point.update(net_value=1.123456, equity=1123.4564, cash=1123.4564)
    account.update(equity=1123.4564, cash=1123.4564)
    result["native_metrics"].update(unit_net_value=1.1234564, total_returns=0.1234564)
    report = build(sample)["report"]
    assert metrics(report)["total_returns"]["value"] == 0.1234564
    assert report["series"][-1]["strategy_return"] == pytest.approx(0.123456)
    result["native_metrics"]["unit_net_value"] = 1.1234584
    with pytest.raises(RunnerFailure, match="原生汇总"):
        reports.build_report(result, settings, market, raw)


def test_receivable_only_zero_quantity_position_and_account_equity_are_not_dropped(sample):
    result, raw, settings, market = sample
    point, account = result["equity"][-1], raw["accounts"][-1]
    for row in (point, account):
        row.update(cash=point["equity"] - 5, dividend_receivable=5)
    raw["positions"] = [
        {
            "time": point["time"],
            "symbol": "600519.SS",
            "name": "应收证券",
            "direction": "long",
            "quantity": 0,
            "last_price": 10,
            "avg_price": 9,
            "market_value": 0,
            "dividend_receivable": 5,
            "pnl": 0,
            "fee": 0,
            "sellable": 0,
        }
    ]
    result["positions"] = [
        {
            "symbol": "600519.SS",
            "quantity": 0,
            "mark_price": 10,
            "market_value": 0,
            "sellable": 0,
            "dividend_receivable": 5,
        }
    ]
    value = build(sample)
    assert value["report_rows"]["positions"][0]["quantity"] == 0
    assert value["report_rows"]["accounts"][-1]["dividend_receivable"] == 5
    from app.rqalpha_backtests import ENGINE_VERSION, validate_result

    market["window"] = {"start": DAYS[0], "end": DAYS[-1]}
    result.update(engine_version=ENGINE_VERSION, matching_type="current_bar", report_data=raw)
    assert validate_result(result, settings, market)["positions"][0]["quantity"] == 0
    raw["positions"][0]["dividend_receivable"] = 4
    with pytest.raises(RunnerFailure, match="原生权益"):
        build(sample)


def test_equity_components_are_explicit_not_a_residual_balancing_entry(sample):
    result, raw, _, _ = sample
    for point, account in zip(result["equity"], raw["accounts"], strict=True):
        for row in (point, account):
            row.update(
                cash=row["equity"] - 17,
                frozen_cash=30,
                cash_liabilities=10,
                cash_liabilities_interest=1,
                pending_cash_flow=-2,
            )
    assert build(sample)["report_rows"]["accounts"][0]["pending_cash_flow"] == -2
    raw["accounts"][0]["frozen_cash"] = 29
    with pytest.raises(RunnerFailure, match="资金组成"):
        build(sample)


def test_native_four_decimal_price_rounding_does_not_reject_a_large_position(sample):
    result, raw, _, _ = sample
    point, account = result["equity"][-1], raw["accounts"][-1]
    market_value = 1000.49
    for row in (point, account):
        row.update(cash=point["equity"] - market_value, market_value=market_value)
    raw["positions"] = [
        {
            "time": point["time"],
            "symbol": "600519.SS",
            "name": None,
            "direction": "long",
            "quantity": 10000,
            "last_price": 0.1,
            "avg_price": 0.09,
            "market_value": market_value,
            "dividend_receivable": 0,
            "pnl": None,
            "fee": None,
            "sellable": None,
        }
    ]
    assert build(sample)["report_rows"]["positions"][0]["market_value"] == market_value
    raw["positions"][0]["market_value"] += 1
    with pytest.raises(RunnerFailure, match="持仓估值"):
        build(sample)


def test_trade_notional_fees_and_native_daily_positions_are_preserved(sample):
    result, raw, _, _ = sample
    point, account = result["equity"][-1], raw["accounts"][-1]
    point["cash"] -= 100
    point["market_value"] = 100
    account.update(cash=point["cash"], market_value=100, fee=5)
    result["trades"] = [
        {
            "time": point["time"],
            "symbol": "600519.SS",
            "side": "buy",
            "quantity": 10,
            "price": 10,
            "fee": 5,
        }
    ]
    raw["positions"] = [
        {
            "time": point["time"],
            "symbol": "600519.SS",
            "name": "测试证券",
            "direction": "long",
            "quantity": 10,
            "last_price": 10,
            "avg_price": 9,
            "market_value": 100,
            "dividend_receivable": 0.0,
            "pnl": 10,
            "fee": 5,
            "sellable": 0,
        }
    ]
    value = build(sample)
    assert value["report"]["series"][-1]["buy_amount"] == 100
    assert value["report_rows"]["positions"][0]["sellable"] == 0
    assert value["report_rows"]["positions"][0]["pnl"] == 10


@pytest.mark.parametrize(
    "change",
    [
        "version",
        "missing_account",
        "cash",
        "missing_position",
        "margin",
        "fee",
        "nav",
        "daily_pnl",
        "wrong_pnl",
        "unknown_benchmark",
        "position_time",
        "duplicates",
        "sellable",
        "summary",
        "nonfinite",
    ],
)
def test_malformed_reports_fail_closed(sample, change):
    result, raw, _, _ = sample
    if change == "version":
        raw["schema_version"] = "bad"
    if change == "missing_account":
        raw["accounts"].pop()
    if change == "cash":
        raw["accounts"][0]["cash"] += 1
    if change == "margin":
        raw["accounts"][0]["margin"] = 0
    if change == "fee":
        raw["accounts"][0]["fee"] = 1
    if change == "missing_position":
        result["equity"][0]["market_value"] = 1
    if change == "nav":
        del result["equity"][0]["net_value"]
    if change == "daily_pnl":
        result["equity"][0]["daily_pnl"] = None
        raw["accounts"][0]["daily_pnl"] = None
    if change == "wrong_pnl":
        raw["accounts"][0]["daily_pnl"] = 100
    if change == "unknown_benchmark":
        raw["benchmark"] = [{"time": stamp(DAYS[0]), "net_value": 1}]
    if change in {"position_time", "duplicates", "sellable"}:
        row = {
            "time": stamp(DAYS[0]),
            "symbol": "600519.SS",
            "name": None,
            "direction": "long",
            "quantity": 10,
            "last_price": 0,
            "avg_price": None,
            "market_value": 0,
            "pnl": None,
            "fee": None,
            "sellable": None,
        }
        raw["positions"] = [row]
        if change == "position_time":
            row["time"] = []
        if change == "duplicates":
            raw["positions"].append(copy.deepcopy(row))
        if change == "sellable":
            row["sellable"] = 11
    if change == "summary":
        result["native_metrics"]["total_returns"] = 99
    if change == "nonfinite":
        raw["risk_free_rate"] = float("inf")
    with pytest.raises(RunnerFailure):
        build(sample)


def test_missing_benchmark_days_and_nonpositive_benchmark_are_rejected(sample):
    result, raw, settings, _ = sample
    settings.benchmark = "000300.SS"
    with pytest.raises(RunnerFailure, match="基准"):
        build(sample)
    raw["benchmark"] = [{"time": point["time"], "net_value": 0} for point in result["equity"]]
    with pytest.raises(RunnerFailure):
        build(sample)


def test_zero_volatility_ratios_are_unavailable_not_fabricated(sample):
    result, raw, _, _ = sample
    for point, account in zip(result["equity"], raw["accounts"], strict=True):
        point.update(net_value=1.0, equity=1000.0, cash=1000.0, daily_pnl=0.0)
        account.update(equity=1000.0, cash=1000.0, daily_pnl=0.0)
    result["native_metrics"].update(unit_net_value=1.0, total_returns=0.0, sharpe=0.0, sortino=0.0)
    report = build(sample)["report"]
    assert metrics(report)["sharpe"]["value"] is None
    assert "零" in metrics(report)["sharpe"]["reason"]
    assert metrics(report)["year_win_rate"]["value"] == 0
    assert report["drawdown"] is None


def test_bankruptcy_does_not_divide_by_zero_in_following_year(sample):
    result, raw, _, _ = sample
    for point, account in zip(result["equity"], raw["accounts"], strict=True):
        point.update(net_value=0.0, equity=0.0, cash=0.0, daily_pnl=0.0)
        account.update(equity=0.0, cash=0.0, daily_pnl=0.0)
    result["native_metrics"].update(unit_net_value=0.0, total_returns=-1.0)
    report = build(sample)["report"]
    assert report["annual_returns"][1]["strategy"] is None
    assert metrics(report)["year_win_rate"]["value"] is None


def test_logs_are_bounded_ordered_and_plain_text():
    row = {
        "sequence": 0,
        "time": None,
        "level": "WARN",
        "source": "strategy",
        "message": "<script>not executed</script>\x00\nline",
        "line": 12,
    }
    assert "\x00" not in reports.validate_logs([row])[0]["message"]
    for update in (
        {"sequence": 1},
        {"level": "TRACE"},
        {"source": "host"},
        {"line": -1},
        {"message": "x" * 4097},
        {"time": float("nan")},
    ):
        with pytest.raises(RunnerFailure):
            reports.validate_logs([{**row, **update}])
    with pytest.raises(RunnerFailure):
        reports.validate_logs([row] * 2001)
    with pytest.raises(RunnerFailure):
        reports.validate_logs(
            [{**row, "sequence": index, "message": "中" * 4096} for index in range(100)]
        )


def test_report_budget_counts_all_history_and_not_just_final_positions(sample, monkeypatch):
    monkeypatch.setattr(reports, "MAX_RECORDS", 7)
    with pytest.raises(RunnerFailure, match="250,000"):
        build(sample)
