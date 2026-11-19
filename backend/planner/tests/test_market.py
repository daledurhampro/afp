"""Unit tests for market price updates and the price lookup fallback."""

from unittest.mock import MagicMock

import pytest

import market
import prices


@pytest.fixture
def db():
    fake = MagicMock()
    fake.jobs.find_by_id.return_value = {"clerk_user_id": "user_1"}
    fake.accounts.find_by_user.return_value = [{"id": "a1"}, {"id": "a2"}]
    fake.positions.find_by_account.side_effect = lambda account_id: {
        "a1": [{"symbol": "SPY"}, {"symbol": "BND"}],
        "a2": [{"symbol": "SPY"}],
    }[account_id]
    fake.instruments.find_by_symbol.side_effect = lambda s: {"symbol": s}
    fake.client.update.return_value = 1
    return fake


def test_update_instrument_prices_collects_unique_symbols(monkeypatch, db):
    seen = {}
    monkeypatch.setattr(market, "update_prices_for_symbols", lambda symbols, _db: seen.setdefault("s", symbols))
    market.update_instrument_prices("j1", db)
    assert seen["s"] == {"SPY", "BND"}


def test_update_instrument_prices_missing_job(monkeypatch, db):
    db.jobs.find_by_id.return_value = None
    called = MagicMock()
    monkeypatch.setattr(market, "update_prices_for_symbols", called)
    market.update_instrument_prices("j1", db)
    called.assert_not_called()


def test_update_instrument_prices_never_raises(db):
    db.accounts.find_by_user.side_effect = RuntimeError("db down")
    market.update_instrument_prices("j1", db)  # non-critical: logs only


def test_update_prices_writes_only_positive_prices(monkeypatch, db):
    def fake_price(symbol):
        if symbol == "ERR":
            raise RuntimeError("api error")
        return {"SPY": 590.0, "ZERO": 0.0}.get(symbol, 0.0)

    monkeypatch.setattr(market, "get_share_price", fake_price)

    market.update_prices_for_symbols({"SPY", "ZERO", "ERR"}, db)

    db.client.update.assert_called_once_with(
        "instruments", {"current_price": 590.0}, "symbol = :symbol", {"symbol": "SPY"}
    )


def test_update_prices_skips_unknown_instruments(monkeypatch, db):
    monkeypatch.setattr(market, "get_share_price", lambda s: 10.0)
    db.instruments.find_by_symbol.side_effect = lambda s: None
    market.update_prices_for_symbols({"NOPE"}, db)
    db.client.update.assert_not_called()


def test_get_all_portfolio_symbols(db):
    db.client.query.return_value = [{"symbol": "SPY"}, {"symbol": "BND"}, {"symbol": None}]
    assert market.get_all_portfolio_symbols(db) == {"SPY", "BND"}
    assert "SELECT DISTINCT symbol FROM positions" in db.client.query.call_args.args[0]


def test_get_all_portfolio_symbols_returns_empty_on_error(db):
    db.client.query.side_effect = RuntimeError("db down")
    assert market.get_all_portfolio_symbols(db) == set()


def test_get_share_price_without_api_key_returns_random_fallback(monkeypatch):
    monkeypatch.setattr(prices, "polygon_api_key", None)
    price = prices.get_share_price("SPY")
    assert isinstance(price, float) and 1 <= price <= 100


def test_get_share_price_falls_back_when_polygon_fails(monkeypatch):
    monkeypatch.setattr(prices, "polygon_api_key", "key")

    def boom(symbol):
        raise RuntimeError("rate limited")

    monkeypatch.setattr(prices, "get_share_price_polygon", boom)
    assert 1 <= prices.get_share_price("SPY") <= 100


def test_get_share_price_uses_polygon_when_available(monkeypatch):
    monkeypatch.setattr(prices, "polygon_api_key", "key")
    monkeypatch.setattr(prices, "get_share_price_polygon", lambda s: 123.45)
    assert prices.get_share_price("SPY") == 123.45


@pytest.mark.parametrize("paid, expected", [(True, "min"), (False, "eod")])
def test_polygon_plan_selects_endpoint(monkeypatch, paid, expected):
    monkeypatch.setattr(prices, "is_paid_polygon", paid)
    monkeypatch.setattr(prices, "get_share_price_polygon_min", lambda s: "min")
    monkeypatch.setattr(prices, "get_share_price_polygon_eod", lambda s: "eod")
    assert prices.get_share_price_polygon("SPY") == expected
