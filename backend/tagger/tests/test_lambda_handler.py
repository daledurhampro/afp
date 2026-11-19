"""Unit tests for the Tagger Lambda handler with a mocked database."""

import json
from unittest.mock import MagicMock

import pytest

import lambda_handler as handler
from agent import AllocationBreakdown, InstrumentClassification, RegionAllocation, SectorAllocation


def classification(symbol):
    return InstrumentClassification(
        symbol=symbol,
        name=f"{symbol} fund",
        instrument_type="etf",
        current_price=10,
        allocation_asset_class=AllocationBreakdown(equity=100),
        allocation_regions=RegionAllocation(north_america=100),
        allocation_sectors=SectorAllocation(diversified=100),
    )


@pytest.fixture
def db(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(handler, "db", fake)
    return fake


@pytest.fixture
def classified(monkeypatch):
    def _set(symbols):
        async def fake_tag(instruments):
            return [classification(s) for s in symbols]

        monkeypatch.setattr(handler, "tag_instruments", fake_tag)

    return _set


def test_no_instruments_returns_400(db):
    response = handler.lambda_handler({"instruments": []}, None)
    assert response["statusCode"] == 400


def test_creates_new_and_updates_existing_instruments(db, classified):
    classified(["NEW", "OLD"])
    db.instruments.find_by_symbol.side_effect = lambda s: {"symbol": s} if s == "OLD" else None

    response = handler.lambda_handler({"instruments": [{"symbol": "NEW"}, {"symbol": "OLD"}]}, None)
    body = json.loads(response["body"])

    assert response["statusCode"] == 200
    assert body["tagged"] == 2
    assert body["updated"] == ["NEW", "OLD"]
    assert body["errors"] == []
    db.instruments.create_instrument.assert_called_once()
    assert db.instruments.create_instrument.call_args.args[0].symbol == "NEW"

    table, data, where, params = db.client.update.call_args.args
    assert table == "instruments"
    assert "symbol" not in data  # the key is not overwritten
    assert params == {"symbol": "OLD"}


def test_database_errors_are_collected_per_symbol(db, classified):
    classified(["A", "B"])
    db.instruments.find_by_symbol.return_value = None
    db.instruments.create_instrument.side_effect = [None, RuntimeError("insert failed")]

    body = json.loads(handler.lambda_handler({"instruments": [{"symbol": "A"}, {"symbol": "B"}]}, None)["body"])

    assert body["updated"] == ["A"]
    assert body["errors"] == [{"symbol": "B", "error": "insert failed"}]
