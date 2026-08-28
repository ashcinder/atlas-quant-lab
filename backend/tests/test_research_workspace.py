from datetime import UTC, datetime
from threading import Event

import pandas as pd

from app.catalog import find_asset
from app.data.providers import DemoProvider
from app.data.service import DataBundle
from app.models import (
    AlertRuleCreate,
    CustomStrategySpec,
    IndicatorSpec,
    ResearchExperiment,
    ResearchRequest,
    RuleNode,
    WalkForwardConfig,
)
from app.research import run_research
from app.strategies.custom import evaluate_rule
from app.workspace import WorkspaceStore


def demo_bundle(limit: int = 360) -> DataBundle:
    asset = find_asset("BTC-USD", "crypto")
    frame = DemoProvider().fetch_bars(
        asset,
        "1d",
        datetime(2018, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
        "auto",
    ).iloc[-limit:]
    return DataBundle(asset=asset, frame=frame, source="demo", source_note="test")


def condition(
    left: IndicatorSpec,
    operator: str,
    *,
    right_indicator: IndicatorSpec | None = None,
    right_value: float | None = None,
) -> RuleNode:
    return RuleNode(
        kind="condition",
        left=left,
        operator=operator,
        right_indicator=right_indicator,
        right_value=right_value,
    )


def custom_spec() -> CustomStrategySpec:
    return CustomStrategySpec(
        id="price_sma",
        name="价格均线策略",
        entry=condition(
            IndicatorSpec(field="close"),
            "crosses_above",
            right_indicator=IndicatorSpec(field="sma", period=3),
        ),
        exit=condition(
            IndicatorSpec(field="close"),
            "crosses_below",
            right_indicator=IndicatorSpec(field="sma", period=3),
        ),
    )


def test_custom_cross_signal_uses_only_current_and_previous_bars():
    index = pd.date_range("2026-01-01", periods=6, tz="UTC")
    frame = pd.DataFrame(
        {
            "open": [3, 2, 1, 4, 5, 6],
            "high": [3, 2, 1, 4, 5, 6],
            "low": [3, 2, 1, 4, 5, 6],
            "close": [3, 2, 1, 4, 5, 6],
            "volume": [1] * 6,
        },
        index=index,
    )
    rule = custom_spec().entry
    original = evaluate_rule(frame, rule)
    mutated = frame.copy()
    mutated.loc[index[-1], "close"] = 10_000
    recalculated = evaluate_rule(mutated, rule)

    assert original.loc[index[3]]
    pd.testing.assert_series_equal(original.iloc[:-1], recalculated.iloc[:-1])


def test_research_keeps_holdout_for_training_winner_and_runs_walk_forward():
    request = ResearchRequest(
        symbol="BTC-USD",
        asset_class="crypto",
        interval="1d",
        data_source="demo",
        experiments=[
            ResearchExperiment(
                strategy_id="sma_cross",
                parameter_grid={"fast": [8, 12], "slow": [30]},
            )
        ],
        holdout_ratio=0.2,
        walk_forward=WalkForwardConfig(
            enabled=True,
            train_bars=160,
            test_bars=40,
            step_bars=40,
            max_windows=2,
        ),
    )
    progress: list[float] = []
    result = run_research(
        "test-job",
        request,
        demo_bundle(),
        Event(),
        lambda value, _message: progress.append(value),
    )

    holdout_candidates = [candidate for candidate in result.candidates if candidate.test_metrics]
    assert result.tested_combinations == 2
    assert len(holdout_candidates) == 1
    assert len(result.walk_forward) == 2
    assert all(window.test_start > window.train_start for window in result.walk_forward)
    assert result.warnings[0].startswith("参数只在训练窗口中选择")
    assert progress[-1] == 1.0


def test_workspace_persists_templates_alerts_and_read_state(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite3")
    saved = store.save_custom_strategy(custom_spec())
    assert store.list_custom_strategies()[0].id == saved.id

    created = store.create_alert(
        AlertRuleCreate(
            name="BTC突破提醒",
            symbol="BTC-USD",
            asset_class="crypto",
            data_source="demo",
            kind="price_crosses_above",
            threshold=100_000,
        )
    )
    store.update_alert_state(created.id, 99_000, datetime.now(UTC))
    refreshed = store.list_alerts()[0]
    notification = store.add_notification(refreshed, "BTC-USD 已上穿 100000", 100_001)

    assert store.list_notifications()[0].id == notification.id
    assert not store.list_notifications()[0].read
    store.mark_notifications_read()
    assert store.list_notifications()[0].read
    assert store.delete_alert(created.id)
    assert store.delete_custom_strategy(saved.id)
