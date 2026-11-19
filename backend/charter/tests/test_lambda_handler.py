"""Unit tests for the Charter Lambda handler: JSON parsing and event handling."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import lambda_handler as handler


@pytest.fixture
def run_with_output(monkeypatch):
    """Run run_charter_agent with the LLM replaced by a canned final_output."""

    def _run(output, db=None):
        monkeypatch.setattr(handler, "create_agent", lambda job_id, data, db: ("model", "task"))

        async def fake_run(agent, input, max_turns):
            return SimpleNamespace(final_output=output, messages=[])

        monkeypatch.setattr(handler.Runner, "run", fake_run)
        return asyncio.run(handler.run_charter_agent("job-1", {"accounts": []}, db))

    return _run


CHARTS_JSON = json.dumps(
    {
        "charts": [
            {"key": "asset_class", "title": "Asset Classes", "type": "pie", "data": [{"name": "Equity", "value": 1}]},
            {"title": "No key given", "type": "bar", "data": []},
        ]
    }
)


def test_parses_charts_and_saves_keyed_by_chart_key(run_with_output):
    db = MagicMock()
    db.jobs.update_charts.return_value = 1

    result = run_with_output(CHARTS_JSON, db)

    assert result["success"] is True
    assert result["charts_generated"] == 2
    assert result["chart_keys"] == ["asset_class", "chart_2"]
    job_id, saved = db.jobs.update_charts.call_args.args
    assert job_id == "job-1"
    assert "key" not in saved["asset_class"]
    assert saved["asset_class"]["title"] == "Asset Classes"


def test_extracts_json_surrounded_by_prose(run_with_output):
    db = MagicMock()
    db.jobs.update_charts.return_value = 1
    result = run_with_output(f"Here are your charts:\n```json\n{CHARTS_JSON}\n```\nEnjoy!", db)
    assert result["charts_generated"] == 2


@pytest.mark.parametrize("output", ["", "no json here", "{not: valid json}", '{"charts": []}'])
def test_bad_or_empty_output_is_reported_as_failure(run_with_output, output):
    db = MagicMock()
    result = run_with_output(output, db)
    assert result["success"] is False
    assert result["charts_generated"] == 0
    db.jobs.update_charts.assert_not_called()


def test_database_error_is_reported_as_failure(run_with_output):
    db = MagicMock()
    db.jobs.update_charts.side_effect = RuntimeError("db down")
    result = run_with_output(CHARTS_JSON, db)
    assert result["success"] is False
    assert result["charts_generated"] == 2


def test_lambda_handler_requires_job_id():
    response = handler.lambda_handler({}, None)
    assert response["statusCode"] == 400
    assert "job_id" in json.loads(response["body"])["error"]


def test_lambda_handler_returns_404_when_job_missing(monkeypatch):
    db = MagicMock()
    db.jobs.find_by_id.return_value = None
    monkeypatch.setattr(handler, "Database", lambda: db)
    response = handler.lambda_handler({"job_id": "missing"}, None)
    assert response["statusCode"] == 404


def test_lambda_handler_loads_portfolio_from_database(monkeypatch):
    db = MagicMock()
    db.jobs.find_by_id.return_value = {"clerk_user_id": "user_1"}
    db.users.find_by_clerk_id.return_value = {"years_until_retirement": 25}
    db.accounts.find_by_user.return_value = [{"id": "a1", "account_name": "401k", "cash_balance": "100"}]
    db.positions.find_by_account.return_value = [{"symbol": "SPY", "quantity": "2"}]
    db.instruments.find_by_symbol.return_value = {"symbol": "SPY", "current_price": 500}
    monkeypatch.setattr(handler, "Database", lambda: db)

    captured = {}

    async def fake_agent(job_id, portfolio_data, db):
        captured["data"] = portfolio_data
        return {"success": True}

    monkeypatch.setattr(handler, "run_charter_agent", fake_agent)

    response = handler.lambda_handler(json.dumps({"job_id": "j1"}), None)  # string events are accepted

    assert response["statusCode"] == 200
    data = captured["data"]
    assert data["years_until_retirement"] == 25
    assert data["accounts"][0]["cash_balance"] == 100.0
    assert data["accounts"][0]["positions"][0] == {
        "symbol": "SPY", "quantity": 2.0, "instrument": {"symbol": "SPY", "current_price": 500}
    }
