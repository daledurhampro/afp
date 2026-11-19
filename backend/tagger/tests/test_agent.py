"""Unit tests for the Tagger's structured output model and DB conversion (no LLM calls)."""

import asyncio
from decimal import Decimal

import pytest
from pydantic import ValidationError

import agent
from agent import (
    AllocationBreakdown,
    InstrumentClassification,
    RegionAllocation,
    SectorAllocation,
    classification_to_db_format,
)


def classification(**overrides):
    data = dict(
        symbol="VT",
        name="Vanguard Total World",
        instrument_type="etf",
        current_price=110.5,
        allocation_asset_class=AllocationBreakdown(equity=100),
        allocation_regions=RegionAllocation(north_america=60, europe=20, **{"global": 20}),
        allocation_sectors=SectorAllocation(technology=40, financials=30, other=30),
    )
    data.update(overrides)
    return InstrumentClassification(**data)


def test_valid_classification():
    c = classification()
    assert c.allocation_regions.global_ == 20


@pytest.mark.parametrize(
    "field, value",
    [
        ("allocation_asset_class", AllocationBreakdown(equity=50)),
        ("allocation_regions", RegionAllocation(asia=10)),
        ("allocation_sectors", SectorAllocation(energy=200 / 3)),
    ],
)
def test_allocations_must_sum_to_100(field, value):
    with pytest.raises(ValidationError, match="must sum to 100"):
        classification(**{field: value})


def test_price_must_be_positive():
    with pytest.raises(ValidationError):
        classification(current_price=0)


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        AllocationBreakdown(equity=100, crypto=0)


def test_conversion_drops_zero_values_and_maps_global_alias():
    inst = classification_to_db_format(classification())
    assert inst.symbol == "VT"
    assert inst.current_price == Decimal("110.5")
    assert inst.allocation_asset_class == {"equity": 100}
    assert inst.allocation_regions == {"north_america": 60, "europe": 20, "global": 20}
    assert inst.allocation_sectors == {"technology": 40, "financials": 30, "other": 30}


def test_conversion_rejects_unknown_instrument_type():
    # The LLM can return any string for instrument_type; the DB schema only allows known types
    with pytest.raises(ValidationError):
        classification_to_db_format(classification(instrument_type="crypto"))


def test_tag_instruments_skips_failures(monkeypatch):
    calls = []

    async def fake_classify(symbol, name, instrument_type):
        calls.append(symbol)
        if symbol == "BAD":
            raise ValueError("model returned garbage")
        return classification(symbol=symbol)

    async def no_sleep(_):
        return None

    monkeypatch.setattr(agent, "classify_instrument", fake_classify)
    monkeypatch.setattr(asyncio, "sleep", no_sleep)

    results = asyncio.run(agent.tag_instruments([{"symbol": "VT"}, {"symbol": "BAD"}, {"symbol": "SPY"}]))

    assert calls == ["VT", "BAD", "SPY"]
    assert [r.symbol for r in results] == ["VT", "SPY"]
