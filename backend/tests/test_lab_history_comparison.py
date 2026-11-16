import pytest

from app.storage import DeletedLabComparison, RunStore


def test_comparison_history_deletes_a_batch_without_removing_other_runs(tmp_path):
    runs = RunStore(tmp_path / "runs.db")
    batch = "a" * 32

    def save(run_id, engine="atlas", owner="owner", strategy="strategy", comparison=batch):
        runs.save(owner, "single", {
            "strategy_id": "sma_cross",
            "symbol": "300750.SZ",
            "lab_snapshot": {
                "comparison_id": comparison,
                "engine": engine,
                "source_sha256": "fixture",
                "settings": {},
            },
        }, {"run_id": run_id, "created_at": "2026-11-16T00:00:00Z"}, lab_strategy_id=strategy)

    save("atlas")
    save("vnpy", "vnpy")
    save("rqalpha", "rqalpha")
    save("other-owner", owner="other")
    save("other-strategy", strategy="second")
    save("legacy", comparison=None)

    assert {row["id"] for row in runs.list_lab("owner", "strategy")} == {"atlas", "vnpy", "rqalpha", "legacy"}
    assert not runs.delete_lab_run("other", "strategy", "atlas")
    assert runs.delete_lab_run("owner", "strategy", "vnpy")
    assert [row["id"] for row in runs.list_lab("owner", "strategy")] == ["legacy"]
    assert runs.get("other", "other-owner")
    assert runs.get("owner", "other-strategy")
    with pytest.raises(DeletedLabComparison):
        save("late-report", "rqalpha")
    assert runs.delete_lab_run("owner", "strategy", "legacy")
