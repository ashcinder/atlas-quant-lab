import pytest

from app.backtest.engine import run_backtest
from app.models import BacktestRequest
from tests.test_backtest import make_bundle


def request(**pipeline):
    return BacktestRequest(strategy_id="sma_cross", params={"fast": 10, "slow": 40},
                           execution_pipeline=pipeline, persist=False)


def test_pipeline_costs_apply_to_actual_fills():
    result = run_backtest(request(max_position=.2, commission_rate=.003), make_bundle())
    assert result.trades
    assert all(trade.fee == pytest.approx(trade.notional * .003) for trade in result.trades)
    assert any("仓位上限 20%" in warning for warning in result.warnings)


def test_missing_model_is_explicit_error(monkeypatch):
    monkeypatch.delenv("ATLAS_AI_MODEL", raising=False)
    with pytest.raises(ValueError, match="AI 流程未就绪"):
        run_backtest(request(ai_stages=[{"stage": "entry", "enabled": True}]), make_bundle())


def test_ai_veto_prevents_buys_and_only_sees_closed_bars(monkeypatch):
    import app.ai_runtime
    evidence_seen = []
    class Guard:
        def review(self, evidence, weight, authority, **kwargs):
            evidence_seen.append(evidence)
            return 0, {"status": "inference_completed"}
    monkeypatch.setattr(app.ai_runtime, "LocalAIGuard", Guard)
    bundle = make_bundle()
    bundle.frame = bundle.frame.iloc[:150]
    result = run_backtest(request(ai_stages=[{"stage": "entry", "enabled": True, "authority": "veto"}]), bundle)
    assert evidence_seen
    assert not result.trades
    assert all(len(item["closed_bars"]) <= 20 for item in evidence_seen)


def test_failed_ai_does_not_publish_a_successful_backtest(monkeypatch):
    import app.ai_runtime
    class Guard:
        def review(self, *args, **kwargs):
            return 0, {"status": "failed_closed"}
    monkeypatch.setattr(app.ai_runtime, "LocalAIGuard", Guard)
    with pytest.raises(ValueError, match="调用失败"):
        run_backtest(request(ai_stages=[{"stage": "risk", "enabled": True}]), make_bundle())


def test_reduce_only_cannot_turn_zero_reduction_budget_into_veto(monkeypatch):
    import app.ai_runtime
    class Guard:
        def review(self, *args, **kwargs):
            return 0, {"status": "inference_completed"}
    monkeypatch.setattr(app.ai_runtime, "LocalAIGuard", Guard)
    bundle = make_bundle()
    bundle.frame = bundle.frame.iloc[:150]
    baseline = run_backtest(request(), bundle)
    actual = run_backtest(request(ai_stages=[{
        "stage": "entry", "enabled": True, "authority": "reduce_only", "max_reduction": 0,
    }]), bundle)
    assert actual.trades
    assert [trade.notional for trade in actual.trades] == pytest.approx([
        trade.notional for trade in baseline.trades
    ])


def test_bulk_research_rejects_enabled_ai():
    from app.models import ResearchRequest
    with pytest.raises(ValueError, match="批量研究请关闭 AI"):
        ResearchRequest(symbol="BTC-USD", asset_class="crypto", experiments=[{"strategy_id": "sma_cross"}],
                        execution_pipeline={"ai_stages": [{"stage": "risk", "enabled": True}]})
