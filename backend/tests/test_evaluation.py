from app.evaluation import build_evaluation


def test_evaluation_scores_only_supported_dimensions_and_never_imputes_total():
    regimes = {
        "牛市": {"periods": 30, "annualized_return": 0.2, "benchmark_annualized_return": 0.3, "annualized_excess_return": -0.1},
        "熊市": {"periods": 35, "annualized_return": -0.1, "benchmark_annualized_return": -0.1, "annualized_excess_return": 0.0},
        "震荡": {"periods": 40, "annualized_return": 0.15, "benchmark_annualized_return": 0.05, "annualized_excess_return": 0.1},
    }
    evaluation = build_evaluation(
        {"cagr": 0.1, "sharpe": 1.0, "max_drawdown": -0.1},
        period={"start": 1, "end": 2, "observation_count": 105},
        regime_metrics=regimes,
    )
    by_id = {item["id"]: item for item in evaluation["dimensions"]}

    assert by_id["return_capacity"]["score"] == 50.0
    assert by_id["risk_adjusted_efficiency"]["score"] == 50.0
    assert by_id["risk_control_stability"]["score"] == 80.0
    assert by_id["market_adaptability"]["score"] == 50.0
    assert by_id["backtest_live_consistency"]["status"] == "not_evaluable"
    assert by_id["strategy_purity"]["status"] == "not_evaluable"
    assert evaluation["complete"] is False
    assert evaluation["total_score"] is None


def test_market_adaptability_requires_thirty_observations_in_every_regime():
    evaluation = build_evaluation(
        {"annualized_return": 0.1, "sharpe": 1, "max_drawdown": -0.1},
        period={"start": 1, "end": 2, "observation_count": 89},
        regime_metrics={
            "牛市": {"periods": 29, "annualized_excess_return": 0.2},
            "熊市": {"periods": 30, "annualized_excess_return": 0.2},
            "震荡": {"periods": 30, "annualized_excess_return": 0.2},
        },
    )
    adaptability = next(item for item in evaluation["dimensions"] if item["id"] == "market_adaptability")
    assert adaptability["score"] is None
    assert adaptability["status"] == "not_evaluable"
    assert "29" in adaptability["reason"]


def test_report_without_raw_market_data_does_not_guess_adaptability():
    evaluation = build_evaluation(
        {"annualized_return": 0.1, "sharpe": 1, "max_drawdown": -0.1},
        period={"start": "2025-01-01", "end": "2026-01-01", "observation_count": 365},
    )
    adaptability = next(item for item in evaluation["dimensions"] if item["id"] == "market_adaptability")
    assert adaptability["score"] is None
    assert "未关联" in adaptability["reason"]
