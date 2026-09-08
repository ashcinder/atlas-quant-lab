from pathlib import Path

from app.catalog import find_asset
from app.fundamentals import (
    FundamentalsProviderError,
    FundamentalsService,
    ProviderSnapshot,
)


class FakeProvider:
    def __init__(self, data: dict | None = None, fail: bool = False) -> None:
        self.data = data or {}
        self.fail = fail
        self.calls = 0

    def supports(self, _asset) -> bool:
        return True

    def fetch(self, _asset) -> ProviderSnapshot:
        self.calls += 1
        if self.fail:
            raise FundamentalsProviderError("provider unavailable")
        return ProviderSnapshot(self.data, "Test Provider", "deterministic fixture")


def metric(response, key: str):
    return next(
        metric for section in response.sections for metric in section.metrics if metric.key == key
    )


def service(tmp_path: Path, provider: FakeProvider) -> FundamentalsService:
    return FundamentalsService(cache_dir=tmp_path / "fundamentals", providers=[provider])


def test_equity_metrics_are_normalized_derived_and_cached(tmp_path: Path) -> None:
    provider = FakeProvider(
        {
            "currency": "USD",
            "financialCurrency": "USD",
            "trailingPE": 20,
            "priceToBook": 4,
            "marketCap": 1_000,
            "freeCashflow": 50,
            "operatingCashflow": 80,
            "sharesOutstanding": 10,
            "totalCash": 300,
            "totalDebt": 100,
            "totalAssets": 2_000,
            "ebitda": 200,
            "debtToEquity": 50,
            "returnOnEquity": 0.18,
        }
    )
    fundamentals = service(tmp_path, provider)

    response = fundamentals.fetch("AAPL", "equity")
    cached = fundamentals.fetch("AAPL", "equity")

    assert response.status == "partial"
    assert metric(response, "trailing_pe").value == 20
    assert metric(response, "price_to_book").value == 4
    assert metric(response, "earnings_yield").value == 0.05
    assert metric(response, "book_to_market").value == 0.25
    assert metric(response, "fcf_yield").value == 0.05
    assert metric(response, "price_to_fcf").value == 20
    assert metric(response, "net_cash").value == 200
    assert metric(response, "net_debt_to_ebitda").value == -1
    assert metric(response, "debt_to_assets").value == 0.05
    assert metric(response, "debt_to_equity").value == 0.5
    assert metric(response, "free_cashflow_per_share").value == 5
    assert metric(response, "roe").value == 0.18
    assert cached.cache_hit is True
    assert provider.calls == 1


def test_missing_values_are_preserved_instead_of_estimated(tmp_path: Path) -> None:
    provider = FakeProvider({"currency": "USD", "currentPrice": 100})

    response = service(tmp_path, provider).fetch("AAPL", "equity")

    assert response.status == "partial"
    assert metric(response, "current_price").value == 100
    assert metric(response, "trailing_pe").value is None
    assert any("缺失字段保持为空" in warning for warning in response.warnings)


def test_stale_cache_is_returned_when_refresh_fails(tmp_path: Path) -> None:
    healthy = FakeProvider({"currency": "USD", "currentPrice": 100})
    cache_dir = tmp_path / "fundamentals"
    first_service = FundamentalsService(cache_dir=cache_dir, providers=[healthy])
    first_service.fetch("AAPL", "equity")

    failing = FakeProvider(fail=True)
    response = FundamentalsService(cache_dir=cache_dir, providers=[failing]).fetch(
        "AAPL", "equity", refresh=True
    )

    assert response.cache_hit is True
    assert response.is_stale is True
    assert any("上次可用快照" in warning for warning in response.warnings)


def test_crypto_does_not_expose_company_valuation_metrics(tmp_path: Path) -> None:
    provider = FakeProvider({"currency": "USD", "marketCap": 1_000, "circulatingSupply": 10})

    response = service(tmp_path, provider).fetch("BTC-USD", "crypto")
    keys = {item.key for section in response.sections for item in section.metrics}

    assert "market_cap" in keys
    assert "circulating_supply" in keys
    assert "trailing_pe" not in keys
    assert any("没有公司层面的 PE、PB" in warning for warning in response.warnings)


def test_catalog_asset_is_kept_in_response(tmp_path: Path) -> None:
    provider = FakeProvider({"currentPrice": 1800})

    response = service(tmp_path, provider).fetch("600519.SS", "equity")

    assert response.asset == find_asset("600519.SS", "equity")
