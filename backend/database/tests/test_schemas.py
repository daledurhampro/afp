"""Unit tests for the Pydantic validation schemas."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.schemas import (
    AccountCreate,
    AssetClassAllocation,
    InstrumentCreate,
    JobCreate,
    PortfolioAnalysis,
    PositionCreate,
    RegionAllocation,
    SectorAllocation,
    UserCreate,
)


def instrument(**overrides):
    data = dict(
        symbol="SPY",
        name="SPDR S&P 500 ETF",
        instrument_type="etf",
        current_price=Decimal("590.00"),
        allocation_regions={"north_america": 100},
        allocation_sectors={"technology": 60, "healthcare": 40},
        allocation_asset_class={"equity": 100},
    )
    data.update(overrides)
    return InstrumentCreate(**data)


# ---------- InstrumentCreate ----------


def test_valid_instrument():
    inst = instrument()
    assert inst.symbol == "SPY"
    assert inst.allocation_asset_class == {"equity": 100}


@pytest.mark.parametrize(
    "field", ["allocation_regions", "allocation_sectors", "allocation_asset_class"]
)
def test_allocation_must_sum_to_100(field):
    bad = {"north_america": 50} if field == "allocation_regions" else (
        {"technology": 50} if field == "allocation_sectors" else {"equity": 50}
    )
    with pytest.raises(ValidationError, match="sum to 100"):
        instrument(**{field: bad})


def test_allocation_allows_small_rounding_error():
    inst = instrument(allocation_sectors={"technology": 33.3, "healthcare": 33.3, "financials": 33.3})
    assert sum(inst.allocation_sectors.values()) == pytest.approx(99.9)


def test_allocation_cannot_be_empty():
    with pytest.raises(ValidationError, match="cannot be empty"):
        instrument(allocation_regions={})


def test_unknown_region_rejected():
    with pytest.raises(ValidationError):
        instrument(allocation_regions={"mars": 100})


def test_unknown_instrument_type_rejected():
    with pytest.raises(ValidationError):
        instrument(instrument_type="crypto")


@pytest.mark.parametrize("price", [Decimal("-1"), Decimal("1000000")])
def test_price_bounds(price):
    with pytest.raises(ValidationError):
        instrument(current_price=price)


@pytest.mark.parametrize("symbol", ["", "X" * 21])
def test_symbol_length(symbol):
    with pytest.raises(ValidationError):
        instrument(symbol=symbol)


# ---------- standalone allocation models ----------


def test_standalone_allocation_models_validate_sum():
    assert RegionAllocation(allocations={"europe": 100}).allocations == {"europe": 100}
    assert AssetClassAllocation(allocations={"equity": 60, "fixed_income": 40})
    assert SectorAllocation(allocations={"other": 100})
    for model, key in [
        (RegionAllocation, "europe"),
        (AssetClassAllocation, "equity"),
        (SectorAllocation, "other"),
    ]:
        with pytest.raises(ValidationError):
            model(allocations={key: 10})


# ---------- user / account / position / job ----------


def test_user_defaults():
    user = UserCreate(clerk_user_id="user_1")
    assert user.asset_class_targets == {"equity": 70, "fixed_income": 30}
    assert user.region_targets == {"north_america": 50, "international": 50}


@pytest.mark.parametrize("years", [-1, 101])
def test_user_years_until_retirement_bounds(years):
    with pytest.raises(ValidationError):
        UserCreate(clerk_user_id="user_1", years_until_retirement=years)


def test_account_defaults_and_bounds():
    acct = AccountCreate(account_name="Roth IRA")
    assert acct.cash_balance == Decimal("0")
    with pytest.raises(ValidationError):
        AccountCreate(account_name="")
    with pytest.raises(ValidationError):
        AccountCreate(account_name="x", cash_balance=Decimal("-5"))
    with pytest.raises(ValidationError):
        AccountCreate(account_name="x", cash_interest=Decimal("1.5"))


def test_position_quantity_must_be_positive_and_date_defaults_to_today():
    pos = PositionCreate(account_id="a1", symbol="SPY", quantity=Decimal("0.5"))
    assert pos.as_of_date == date.today()
    with pytest.raises(ValidationError):
        PositionCreate(account_id="a1", symbol="SPY", quantity=Decimal("0"))


def test_job_type_must_be_known():
    assert JobCreate(clerk_user_id="u", job_type="portfolio_analysis")
    with pytest.raises(ValidationError):
        JobCreate(clerk_user_id="u", job_type="make_me_rich")


@pytest.mark.parametrize("score", [0, 11])
def test_portfolio_analysis_risk_score_bounds(score):
    with pytest.raises(ValidationError):
        PortfolioAnalysis(
            total_value=Decimal("1"),
            asset_allocation={},
            region_allocation={},
            sector_allocation={},
            risk_score=score,
            recommendations=[],
        )
