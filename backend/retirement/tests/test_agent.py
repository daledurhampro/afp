"""Unit tests for the Retirement agent's calculations (no LLM calls)."""

import random

import pytest

import agent
from agent import (
    calculate_asset_allocation,
    calculate_portfolio_value,
    generate_projections,
    run_monte_carlo_simulation,
)

PORTFOLIO = {
    "accounts": [
        {
            "cash_balance": 1000,
            "positions": [
                {
                    "symbol": "SPY",
                    "quantity": 10,
                    "instrument": {"current_price": 500, "allocation_asset_class": {"equity": 100}},
                },
                {
                    "symbol": "AOR",
                    "quantity": 20,
                    "instrument": {
                        "current_price": 100,
                        "allocation_asset_class": {"equity": 60, "fixed_income": 40},
                    },
                },
            ],
        },
        {
            "cash_balance": "2000",  # values from the DB can arrive as strings
            "positions": [
                {
                    "symbol": "VNQ",
                    "quantity": 10,
                    "instrument": {"current_price": 100, "allocation_asset_class": {"real_estate": 100}},
                }
            ],
        },
    ]
}
# 1000 + 5000 + 2000 + 2000 + 1000 = 11,000

ALL_EQUITY = {"equity": 1.0, "bonds": 0.0, "real_estate": 0.0, "commodities": 0.0, "cash": 0.0}


def test_portfolio_value_includes_cash_and_positions():
    assert calculate_portfolio_value(PORTFOLIO) == pytest.approx(11000)


def test_portfolio_value_defaults_price_to_100_when_missing():
    data = {"accounts": [{"positions": [{"quantity": 3, "instrument": {}}]}]}
    assert calculate_portfolio_value(data) == 300


def test_portfolio_value_empty():
    assert calculate_portfolio_value({}) == 0


def test_asset_allocation_fractions():
    alloc = calculate_asset_allocation(PORTFOLIO)
    assert alloc["equity"] == pytest.approx((5000 + 1200) / 11000)
    assert alloc["bonds"] == pytest.approx(800 / 11000)
    assert alloc["real_estate"] == pytest.approx(1000 / 11000)
    assert alloc["cash"] == pytest.approx(3000 / 11000)
    assert alloc["commodities"] == 0
    assert sum(alloc.values()) == pytest.approx(1.0)


def test_asset_allocation_empty_portfolio_is_all_zero():
    assert calculate_asset_allocation({"accounts": []}) == {
        "equity": 0, "bonds": 0, "real_estate": 0, "commodities": 0, "cash": 0
    }


def test_monte_carlo_is_reproducible_with_seed_and_has_expected_shape():
    random.seed(1)
    first = run_monte_carlo_simulation(100_000, 10, 40_000, ALL_EQUITY, num_simulations=200)
    random.seed(1)
    second = run_monte_carlo_simulation(100_000, 10, 40_000, ALL_EQUITY, num_simulations=200)
    assert first == second
    assert set(first) == {
        "success_rate", "median_final_value", "percentile_10", "percentile_90",
        "average_years_lasted", "expected_value_at_retirement",
    }
    assert 0 <= first["success_rate"] <= 100
    assert first["percentile_10"] <= first["median_final_value"] <= first["percentile_90"]
    assert 0 <= first["average_years_lasted"] <= 30


def test_monte_carlo_expected_value_is_deterministic():
    # 0 years of accumulation: the expected value is just today's value
    result = run_monte_carlo_simulation(50_000, 0, 1_000, ALL_EQUITY, num_simulations=10)
    assert result["expected_value_at_retirement"] == 50_000

    # 1 year at 7% plus a 10k contribution
    result = run_monte_carlo_simulation(100_000, 1, 1_000, ALL_EQUITY, num_simulations=10)
    assert result["expected_value_at_retirement"] == pytest.approx(117_000)


def test_monte_carlo_extremes():
    random.seed(0)
    rich = run_monte_carlo_simulation(50_000_000, 5, 10_000, ALL_EQUITY, num_simulations=100)
    assert rich["success_rate"] == 100.0

    broke = run_monte_carlo_simulation(0, 0, 1_000_000, ALL_EQUITY, num_simulations=100)
    assert broke["success_rate"] == 0.0
    assert broke["median_final_value"] == 0


def test_projections_milestones_and_phases():
    projections = generate_projections(100_000, 10, ALL_EQUITY, current_age=50)
    ages = [p["age"] for p in projections]
    assert ages[0] == 50
    assert all(b - a == 5 for a, b in zip(ages, ages[1:]))
    assert [p["phase"] for p in projections if p["year"] <= 10] == ["accumulation"] * 3
    assert all(p["phase"] == "retirement" for p in projections if p["year"] > 10)
    assert projections[0]["portfolio_value"] == 100_000
    # accumulation phase grows the portfolio
    assert projections[1]["portfolio_value"] > projections[0]["portfolio_value"]
    # retirement income is 4% of the portfolio at the start of the period
    retirement = [p for p in projections if p["phase"] == "retirement"]
    assert retirement and all(p["annual_income"] > 0 for p in retirement)


def test_create_agent_builds_task_without_calling_llm(monkeypatch):
    monkeypatch.setattr(agent, "LitellmModel", lambda model: f"model:{model}")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    monkeypatch.setenv("BEDROCK_REGION", "us-east-1")

    model, tools, task = agent.create_agent(
        "job-1", PORTFOLIO, {"years_until_retirement": 20, "target_retirement_income": 50_000, "current_age": 45}
    )

    assert model == "model:bedrock/us.amazon.nova-pro-v1:0"
    assert tools == []
    assert "Portfolio Value: $11,000" in task
    assert "Years to Retirement: 20" in task
    assert "Target Annual Income: $50,000" in task
    assert "Current Age: 45" in task
    assert agent.os.environ["AWS_REGION_NAME"] == "us-east-1"
