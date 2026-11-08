from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from app.compute_objects import ComputeObjects
from app.data.publish_market import PublicationQuery, cached_bundle, main, publish_query
from app.data.service import DataBundle, MarketDataService
from app.market_publication import MarketPublication
from app.models import Asset


@pytest.fixture
def sample():
    frame = pd.DataFrame({"open": 100., "high": 102., "low": 99., "close": 101., "volume": 1000.},
                         index=pd.date_range("2025-01-01", periods=40, tz="UTC"))
    return DataBundle(Asset(symbol="BTC-USD", name="Bitcoin", asset_class="crypto", exchange="CRYPTO", currency="USD"),
                      frame, "binance", fetched_at=datetime(2025, 3, 1, tzinfo=UTC))


def test_publishes_real_immutable_objects_and_conversion_references(tmp_path, sample, monkeypatch):
    service = MarketDataService(tmp_path / "cache")
    publications = MarketPublication(tmp_path / "publications.db", ComputeObjects(tmp_path / "objects"))
    query = PublicationQuery(symbol="BTC-USD", adjustment="raw", data_source="binance", base_currencies=["USDT"])
    monkeypatch.setattr(service, "fetch", lambda *args, **kwargs: sample)
    output = publish_query(service, publications, query)
    base = publications.manifest(output["dataset_id"])
    converted = publications.manifest(base["conversions"]["USDT"])
    assert base["asset"]["currency"] == "USD"
    assert converted["asset"]["currency"] == "USDT"
    assert publications.lookup(query.model_dump())["dataset_id"] == base["dataset_id"]
    pd.testing.assert_frame_equal(publications.bundle(base["dataset_id"]).frame.sort_index(axis=1), sample.frame.sort_index(axis=1), check_names=False, check_freq=False)
    pd.testing.assert_frame_equal(publications.bundle(converted["dataset_id"]).frame.sort_index(axis=1), sample.frame.sort_index(axis=1), check_names=False, check_freq=False)


@pytest.mark.parametrize("column,value", [("high", 100.), ("low", 101.), ("volume", -1.),
                                         ("volume", float("nan")), ("volume", float("inf"))])
def test_publisher_discards_invalid_bars_explicitly_without_changing_cache(tmp_path, sample, monkeypatch, column, value):
    service = MarketDataService(tmp_path / "cache")
    publications = MarketPublication(tmp_path / "publications.db", ComputeObjects(tmp_path / "objects"))
    sample.frame.loc[sample.frame.index[0], column] = value
    original = sample.frame.copy()
    monkeypatch.setattr(service, "fetch", lambda *args, **kwargs: sample)
    result = publish_query(service, publications, PublicationQuery(symbol="BTC-USD", base_currencies=["USDT"]))
    manifest = publications.manifest(result["dataset_id"])
    assert manifest["count"] == 39
    assert "剔除1根" in manifest["source_note"]
    assert publications.bundle(manifest["dataset_id"]).frame.index[0] == original.index[1]
    assert publications.manifest(manifest["conversions"]["USDT"])["count"] == 39
    pd.testing.assert_frame_equal(sample.frame, original)


@pytest.mark.parametrize("column,value", [("high", 100.), ("low", 101.)])
def test_publication_rejects_contradictory_ohlc_and_retains_previous_version(tmp_path, sample, column, value):
    publications = MarketPublication(tmp_path / "publications.db", ComputeObjects(tmp_path / "objects"))
    query = {"symbol": "BTC-USD"}
    previous = publications.publish(query, sample)
    sample.frame.loc[sample.frame.index[0], column] = value
    with pytest.raises(ValueError, match="无效价格"):
        publications.publish(query, sample)
    assert publications.lookup(query)["dataset_id"] == previous["dataset_id"]


def test_too_few_valid_bars_preserve_previous_publication(tmp_path, sample, monkeypatch):
    service = MarketDataService(tmp_path / "cache")
    publications = MarketPublication(tmp_path / "publications.db", ComputeObjects(tmp_path / "objects"))
    query = PublicationQuery(symbol="BTC-USD")
    previous = publications.publish(query.model_dump(), sample)
    sample.frame.loc[sample.frame.index[2]:, "volume"] = -1
    monkeypatch.setattr(service, "fetch", lambda *args, **kwargs: sample)
    with pytest.raises(ValueError, match="有效行情少于3根"):
        publish_query(service, publications, query)
    assert publications.lookup(query.model_dump())["dataset_id"] == previous["dataset_id"]


def test_cached_only_exact_identity_no_provider_calls(tmp_path, sample, monkeypatch):
    service = MarketDataService(tmp_path / "cache")
    query = PublicationQuery(symbol="BTC-USD", adjustment="raw", data_source="binance")
    key = service._cache_path("binance", "BTC-USD", "1d", None, None, "raw")
    service.store.write(key.name, sample.frame, sample.fetched_at)
    monkeypatch.setattr(service, "fetch", lambda *args, **kwargs: pytest.fail("unexpected upstream fetch"))
    for provider in service.providers.values():
        monkeypatch.setattr(provider, "fetch_bars", lambda *args, **kwargs: pytest.fail("unexpected provider fetch"))
    bundle = cached_bundle(service, query)
    assert bundle.source == "binance:cache"
    assert bundle.frame.equals(sample.frame)
    publications = MarketPublication(tmp_path / "publications.db", ComputeObjects(tmp_path / "objects"))
    assert publish_query(service, publications, query, cached_only=True)["count"] == 40
    with pytest.raises(ValueError):
        cached_bundle(service, query.model_copy(update={"adjustment": "auto"}))
    with pytest.raises(ValueError):
        cached_bundle(service, query.model_copy(update={"start": datetime(2025, 1, 1, tzinfo=UTC)}))


def test_cached_only_rejects_ambiguous_provider_and_fx(tmp_path, sample, monkeypatch):
    service = MarketDataService(tmp_path / "cache")
    for provider in ("binance", "yahoo"):
        key = service._cache_path(provider, "BTC-USD", "1d", None, None, "raw")
        service.store.write(key.name, sample.frame, sample.fetched_at)
    with pytest.raises(ValueError, match="多个来源"):
        cached_bundle(service, PublicationQuery(symbol="BTC-USD", adjustment="raw"))
    monkeypatch.setattr(service, "convert_to_base_currency", lambda *args, **kwargs: pytest.fail("must reject before FX fetch"))
    with pytest.raises(ValueError, match="历史汇率"):
        publish_query(service, None, PublicationQuery(symbol="BTC-USD", adjustment="raw", data_source="binance", base_currencies=["CNY"]), True)


def test_publisher_help_has_no_network():
    output = subprocess.run([sys.executable, "-m", "app.data.publish_market", "--help"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert output.returncode == 0
    assert "--cached-only" in output.stdout


@pytest.mark.parametrize("arguments", [["--config", "missing.json"], ["--config", "unused.json", "--interval", "1"]])
def test_invalid_config_rejected(arguments):
    with pytest.raises(SystemExit) as error:
        main(arguments)
    assert error.value.code == 2


def test_author_wrapper_help_and_install_check(tmp_path, monkeypatch, capsys):
    script = Path(__file__).resolve().parents[2] / "scripts/author-proof.py"
    specification = importlib.util.spec_from_file_location("author_proof", script)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    assert module.main(["check-install"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["cryptographic_verification_performed"] is False
    assert output["profile_changed"] is False
    help_result = subprocess.run([sys.executable, str(script), "--help"], cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert help_result.returncode == 0
    assert "check-install" in help_result.stdout


def test_author_wrapper_argument_arrays_never_upload(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / "scripts/author-proof.py"
    specification = importlib.util.spec_from_file_location("author_proof", script)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    binary = tmp_path / "strategy/zkvm/target/release/atlas-zkvm"
    binary.parent.mkdir(parents=True)
    binary.write_text("not executed")
    binary.chmod(0o700)
    captured = []
    monkeypatch.setattr(module.subprocess, "run", lambda arguments, **kwargs: captured.append(arguments) or type("Result", (), {"returncode": 0})())
    assert module.main(["prepare", "--dataset", "data.json", "--python-source", "source.py", "--output", "private.json"]) == 0
    assert module.main(["prove", "--witness", "private.json", "--output", "proof", "--resume"]) == 0
    assert "prepare-zk-witness.py" in captured[0][1]
    assert "prove-private-program.py" in captured[1][1]
    assert "--resume" in captured[1]
    assert all("--publish-local" not in arguments for arguments in captured)
