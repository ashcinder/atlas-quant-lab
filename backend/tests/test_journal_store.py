from app.journal.store import JournalStore
from app.models import AlertRuleCreate
from app.workspace import WorkspaceStore


def test_journal_store_isolated_cas(tmp_path):
    store = JournalStore(tmp_path / "journal.sqlite")
    first = store.create_user("first@example.com", "password-1")
    second = store.create_user("second@example.com", "password-2")
    state = {"version": 1}

    first_read = store.read_ledger(first.id, state)
    second_read = store.read_ledger(second.id, state)
    assert store.save_ledger(first.id, {"version": 2}, first_read["revision"])
    assert store.read_ledger(second.id, state)["state"] == state
    assert store.save_ledger(first.id, {"version": 3}, first_read["revision"]) is None
    assert second_read["revision"] == 0


def test_workspace_rows_are_owned(tmp_path):
    store = WorkspaceStore(tmp_path / "workspace.sqlite")
    rule = AlertRuleCreate(
        name="private", symbol="BTC-USD", asset_class="crypto", kind="price_above", threshold=1
    )
    store.create_alert(rule, "first")
    store.create_alert(rule, "second")
    assert len(store.list_alerts("first")) == 1
    assert len(store.list_alerts("second")) == 1
