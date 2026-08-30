import json
import sqlite3

import pytest

from app.models import CustomStrategySpec, IndicatorSpec, RuleNode
from app.strategy_projects import (
    ProjectArtifactLink,
    ProjectConflictError,
    ProjectFreezeRequest,
    StrategyProjectCreate,
    StrategyProjectStore,
    StrategyProjectUpdate,
)
from app.workspace import WorkspaceStore


def custom_strategy() -> CustomStrategySpec:
    return CustomStrategySpec(
        id="project_momentum",
        name="Project Momentum",
        description="Causal visual rule used by a strategy project.",
        entry=RuleNode(
            kind="condition",
            left=IndicatorSpec(field="close"),
            operator="crosses_above",
            right_indicator=IndicatorSpec(field="sma", period=20),
        ),
        exit=RuleNode(
            kind="condition",
            left=IndicatorSpec(field="close"),
            operator="crosses_below",
            right_indicator=IndicatorSpec(field="sma", period=20),
        ),
        target_position=0.8,
    )


def seed_private_artifacts(path, strategy: CustomStrategySpec) -> None:
    validation = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "graph_hash": "a" * 64,
        "topological_order": ["market", "strategy", "risk", "execution", "audit", "output"],
        "summary": {"nodes": 6, "edges": 5, "ai_nodes": 1, "hard_risk_gates": 1},
    }
    request = {
        "symbol": "BTC-USD",
        "asset_class": "crypto",
        "interval": "1d",
        "objective": "sharpe",
        "commission_rate": 0.001,
        "slippage_rate": 0.0005,
        "spread_rate": 0.0005,
        "experiments": [
            {
                "strategy_id": strategy.id,
                "base_params": {},
                "parameter_grid": {},
                "custom_strategy": strategy.model_dump(mode="json"),
            }
        ],
    }
    result = {
        "job_id": "research_1",
        "summary": {"is_robust": True, "average_oos_sharpe": 1.12},
        "walk_forward": [
            {
                "strategy_id": strategy.id,
                "test_sharpe": 1.1,
                "test_return": 0.08,
                "trades": 12,
            },
            {
                "strategy_id": strategy.id,
                "test_sharpe": 0.9,
                "test_return": 0.05,
                "trades": 11,
            },
            {
                "strategy_id": strategy.id,
                "test_sharpe": 0.7,
                "test_return": 0.03,
                "trades": 13,
            },
            {
                "strategy_id": "unrelated_strategy",
                "test_sharpe": 4.0,
                "test_return": 0.5,
                "trades": 500,
            },
        ],
        "candidates": [
            {"strategy_id": strategy.id},
            {"strategy_id": "unrelated_strategy"},
        ],
    }
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS qj_workflows (
                id TEXT PRIMARY KEY, revision INTEGER NOT NULL, graph_hash TEXT NOT NULL,
                validation_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS qj_strategy_packages (
                id TEXT PRIMARY KEY, content_hash TEXT NOT NULL, manifest_hash TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS research_jobs (
                id TEXT PRIMARY KEY, request_json TEXT NOT NULL, result_json TEXT,
                status TEXT NOT NULL
            );
            """
        )
        connection.execute(
            "INSERT INTO qj_workflows VALUES (?, ?, ?, ?)",
            ("workflow_1", 3, "a" * 64, json.dumps(validation)),
        )
        connection.execute(
            "INSERT INTO qj_strategy_packages VALUES (?, ?, ?, ?)",
            ("package_1", "b" * 64, "c" * 64, "validated"),
        )
        connection.execute(
            "INSERT INTO research_jobs VALUES (?, ?, ?, ?)",
            ("research_1", json.dumps(request), json.dumps(result), "completed"),
        )
        assert strategy.id


def test_project_binds_artifacts_enforces_revision_and_freezes(tmp_path):
    path = tmp_path / "atlas.sqlite3"
    workspace = WorkspaceStore(path)
    strategy_spec = custom_strategy()
    strategy = workspace.save_custom_strategy(strategy_spec)
    seed_private_artifacts(path, strategy_spec)
    store = StrategyProjectStore(path)
    project = store.create(
        StrategyProjectCreate(
            name="BTC momentum research",
            thesis=(
                "A causal momentum rule should retain positive risk-adjusted returns "
                "after costs."
            ),
            asset_symbol="BTC-USD",
            asset_class="crypto",
            interval="1d",
            benchmark="BTC-USD",
            objective="sharpe",
        )
    )

    project = store.link_artifact(
        project["id"],
        ProjectArtifactLink(expected_revision=1, kind="strategy", artifact_id=strategy.id),
    )
    with pytest.raises(ProjectConflictError):
        store.update(
            project["id"],
            StrategyProjectUpdate(expected_revision=1, name="Stale concurrent update"),
        )
    project = store.link_artifact(
        project["id"],
        ProjectArtifactLink(
            expected_revision=project["revision"], kind="workflow", artifact_id="workflow_1"
        ),
    )
    project = store.link_artifact(
        project["id"],
        ProjectArtifactLink(
            expected_revision=project["revision"], kind="research", artifact_id="research_1"
        ),
    )

    assert project["stage"] == "validated"
    assert project["walk_forward_windows"] == 3
    assert project["oos_trade_count"] == 36
    assert project["next_gate"]["id"] == "version"

    frozen = store.freeze(
        project["id"], ProjectFreezeRequest(expected_revision=project["revision"], version="1.0.0")
    )
    assert frozen["stage"] == "versioned"
    assert frozen["version"] == "1.0.0"
    assert len(frozen["commitment"]) == 64
    assert frozen["completion"] == 1

    revised = store.update(
        frozen["id"],
        StrategyProjectUpdate(
            expected_revision=frozen["revision"],
            thesis="A revised hypothesis must invalidate frozen and research artifacts.",
        ),
    )
    assert revised["commitment"] is None
    assert revised["research_job_id"] is None
    assert revised["stage"] == "composed"


def test_project_research_binding_requires_matching_asset_and_costs(tmp_path):
    path = tmp_path / "atlas.sqlite3"
    WorkspaceStore(path)
    seed_private_artifacts(path, custom_strategy())
    store = StrategyProjectStore(path)
    project = store.create(
        StrategyProjectCreate(
            name="ETH project",
            thesis="ETH results must not reuse a BTC research receipt.",
            asset_symbol="ETH-USD",
            asset_class="crypto",
            interval="1d",
        )
    )
    with pytest.raises(ValueError, match="标的或周期"):
        store.link_artifact(
            project["id"],
            ProjectArtifactLink(
                expected_revision=project["revision"], kind="research", artifact_id="research_1"
            ),
        )
