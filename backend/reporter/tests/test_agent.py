"""Unit tests for the Reporter agent's portfolio formatting (no LLM calls)."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import agent
from agent import ReporterContext, calculate_portfolio_metrics, format_portfolio_for_analysis

PORTFOLIO = {
    "accounts": [
        {
            "name": "401k",
            "cash_balance": 500,
            "positions": [
                {"symbol": "SPY", "quantity": 10, "instrument": {"name": "S&P 500", "current_price": 500}},
                {"symbol": "BND", "quantity": 20, "instrument": {"name": "Bonds", "current_price": 75}},
            ],
        },
        {
            "name": "Roth",
            "cash_balance": "250",
            "positions": [
                {"symbol": "SPY", "quantity": 1, "instrument": {"current_price": 500}},
                {"symbol": "NEW", "quantity": 5, "instrument": {}},  # no price yet
            ],
        },
    ]
}


def test_metrics():
    m = calculate_portfolio_metrics(PORTFOLIO)
    assert m["num_accounts"] == 2
    assert m["num_positions"] == 4
    assert m["unique_symbols"] == 3
    assert m["cash_balance"] == 750
    # 5000 + 1500 + 500 + cash 750; NEW has no price so it is excluded
    assert m["total_value"] == 7750


def test_metrics_empty():
    m = calculate_portfolio_metrics({})
    assert (m["num_accounts"], m["num_positions"], m["unique_symbols"], m["total_value"]) == (0, 0, 0, 0)


def test_format_includes_overview_accounts_and_user_profile():
    text = format_portfolio_for_analysis(
        PORTFOLIO, {"years_until_retirement": 25, "target_retirement_income": 90000}
    )
    assert "- 2 accounts" in text
    assert "- 3 unique holdings" in text
    assert "- $750.00 in cash" in text
    assert "- $7,750.00 total value" in text
    assert "401k ($500.00 cash):" in text
    assert "  - SPY: 10.00 shares" in text
    assert "Years to retirement: 25" in text
    assert "Target retirement income: $90,000/year" in text


def test_format_handles_missing_user_data():
    text = format_portfolio_for_analysis({"accounts": []}, {})
    assert "Years to retirement: Not specified" in text
    assert "Target retirement income: $0/year" in text


def test_format_includes_allocation_hints_when_present():
    data = {
        "accounts": [
            {
                "name": "A",
                "positions": [
                    {
                        "symbol": "VT",
                        "quantity": 1,
                        "instrument": {
                            "asset_class": "equity",
                            "regions": [
                                {"name": "US", "percentage": 60},
                                {"name": "Europe", "percentage": 20},
                                {"name": "Asia", "percentage": 20},
                            ],
                        },
                    }
                ],
            }
        ]
    }
    text = format_portfolio_for_analysis(data, {})
    assert "VT: 1.00 shares (Asset: equity, Regions: US 60%, Europe 20%)" in text


def test_create_agent(monkeypatch):
    monkeypatch.setattr(agent, "LitellmModel", lambda model: f"model:{model}")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    db = object()
    model, tools, task, context = agent.create_agent("job-1", PORTFOLIO, {"years_until_retirement": 10}, db)
    assert model == "model:bedrock/us.amazon.nova-pro-v1:0"
    assert tools == [agent.get_market_insights]
    assert isinstance(context, ReporterContext) and context.job_id == "job-1" and context.db is db
    assert "Portfolio Overview:" in task


def _invoke_market_insights(symbols):
    tool = agent.get_market_insights
    ctx = SimpleNamespace(context=ReporterContext(job_id="j", portfolio_data={}, user_data={}))
    return asyncio.run(tool.on_invoke_tool(ctx, json.dumps({"symbols": symbols})))


def test_market_insights_formats_vector_results(monkeypatch):
    sts, sagemaker, s3v = MagicMock(), MagicMock(), MagicMock()
    sts.get_caller_identity.return_value = {"Account": "123"}
    sagemaker.invoke_endpoint.return_value = {"Body": SimpleNamespace(read=lambda: b"[[[0.1, 0.2]]]")}
    s3v.query_vectors.return_value = {
        "vectors": [
            {"metadata": {"text": "Strong earnings", "company_name": "Apple"}},
            {"metadata": {"text": "Rates steady"}},
            {"metadata": {}},
        ]
    }
    clients = {"sts": sts, "sagemaker-runtime": sagemaker, "s3vectors": s3v}
    import boto3

    monkeypatch.setattr(boto3, "client", lambda name, **kwargs: clients[name])

    result = _invoke_market_insights(["AAPL"])

    assert result == "Market Insights:\nApple: Strong earnings...\n- Rates steady..."
    assert s3v.query_vectors.call_args.kwargs["vectorBucketName"] == "afp-vectors-123"
    assert s3v.query_vectors.call_args.kwargs["queryVector"] == {"float32": [0.1, 0.2]}


def test_market_insights_falls_back_on_error(monkeypatch):
    import boto3

    def boom(*args, **kwargs):
        raise RuntimeError("no credentials")

    monkeypatch.setattr(boto3, "client", boom)
    assert "unavailable" in _invoke_market_insights(["AAPL"])
