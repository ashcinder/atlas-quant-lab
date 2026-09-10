import pandas as pd
from app.data.service import MarketDataService
from tests.test_data_and_signals import CountingProvider


def test_database_survives_restart_without_csv(tmp_path):
    service = MarketDataService(tmp_path)
    provider = CountingProvider()
    service.providers["binance"] = provider
    original = service.fetch("BTC-USD", "crypto", "1d", None, None, source="binance")
    assert not list(tmp_path.glob("*.csv.gz"))
    restarted = MarketDataService(tmp_path)
    restarted.providers["binance"] = provider
    cached = restarted.fetch("BTC-USD", "crypto", "1d", None, None, source="binance")
    assert provider.calls == 1 and cached.cache_hit
    pd.testing.assert_frame_equal(original.frame, cached.frame, check_names=False, check_freq=False)


def test_legacy_csv_migration_is_non_destructive(tmp_path):
    service = MarketDataService(tmp_path)
    path = service._cache_path("binance", "BTC-USD", "1d", None, None, "auto")
    CountingProvider().frame.to_csv(path, compression="gzip")
    assert service._read_cache(path) is not None
    assert path.exists()
    assert service.store.timestamp(path.name) is not None


def test_sources_are_not_mixed(tmp_path):
    service = MarketDataService(tmp_path)
    frame = CountingProvider().frame
    service.store.write("binance", frame)
    assert service.store.read("yahoo") is None
