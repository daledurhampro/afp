"""Unit tests for the Charter agent's portfolio analysis (no LLM calls)."""

import agent
from agent import analyze_portfolio

PORTFOLIO = {
    "accounts": [
        {
            "name": "401(k)",
            "type": "401k",
            "cash_balance": 1000,
            "positions": [
                {
                    "symbol": "SPY",
                    "quantity": 10,
                    "instrument": {
                        "current_price": 500,
                        "allocation_asset_class": {"equity": 100},
                        "allocation_regions": {"north_america": 100},
                        "allocation_sectors": {"technology": 50, "healthcare": 50},
                    },
                },
                {
                    "symbol": "BND",
                    "quantity": 40,
                    "instrument": {
                        "current_price": 75,
                        "allocation_asset_class": {"fixed_income": 100},
                        "allocation_regions": {"north_america": 100},
                        "allocation_sectors": {"treasury": 100},
                    },
                },
            ],
        },
        {
            "name": "Roth IRA",
            "type": "roth_ira",
            "cash_balance": None,  # missing cash should count as 0
            "positions": [
                {
                    "symbol": "SPY",  # same symbol in a second account
                    "quantity": 2,
                    "instrument": {
                        "current_price": 500,
                        "allocation_asset_class": {"equity": 100},
                        "allocation_regions": {"north_america": 100},
                        "allocation_sectors": {"technology": 50, "healthcare": 50},
                    },
                }
            ],
        },
    ]
}
# SPY 6000, BND 3000, cash 1000 -> total 10,000


def test_totals_and_counts():
    text = analyze_portfolio(PORTFOLIO)
    assert "Total Value: $10,000.00" in text
    assert "Number of Accounts: 2" in text
    assert "Number of Positions: 2" in text  # unique symbols


def test_account_breakdown_percentages():
    text = analyze_portfolio(PORTFOLIO)
    assert "401(k) (401k): $9,000.00 (90.0%)" in text
    assert "Roth IRA (roth_ira): $1,000.00 (10.0%)" in text


def test_holdings_combined_across_accounts_and_sorted():
    text = analyze_portfolio(PORTFOLIO)
    holdings = text.split("Top Holdings by Value:")[1].split("Calculated Allocations:")[0]
    assert holdings.index("SPY: $6,000.00 (60.0%)") < holdings.index("BND: $3,000.00 (30.0%)")


def test_aggregated_allocations_include_cash():
    text = analyze_portfolio(PORTFOLIO)
    assert "equity: $6,000.00" in text
    assert "fixed_income: $3,000.00" in text
    assert "cash: $1,000.00" in text
    assert "north_america: $9,000.00" in text
    assert "technology: $3,000.00" in text
    assert "treasury: $3,000.00" in text


def test_missing_price_defaults_to_one_dollar():
    data = {"accounts": [{"name": "A", "positions": [{"symbol": "XYZ", "quantity": 7, "instrument": {}}]}]}
    assert "Total Value: $7.00" in analyze_portfolio(data)


def test_empty_portfolio_does_not_divide_by_zero():
    text = analyze_portfolio({"accounts": []})
    assert "Total Value: $0.00" in text
    assert "Number of Accounts: 0" in text


def test_create_agent_returns_model_and_task(monkeypatch):
    monkeypatch.setattr(agent, "LitellmModel", lambda model: f"model:{model}")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    model, task = agent.create_agent("job-1", PORTFOLIO)
    assert model == "model:bedrock/us.amazon.nova-pro-v1:0"
    assert "Total Value: $10,000.00" in task
