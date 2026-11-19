"""Unit tests for the Planner's orchestration helpers (Lambda and DB are mocked)."""

import asyncio
import io
import json
from unittest.mock import MagicMock

import pytest

import agent


def lambda_response(payload):
    return {"Payload": io.BytesIO(json.dumps(payload).encode())}


@pytest.fixture
def lambda_client(monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(agent, "lambda_client", client)
    monkeypatch.setattr(agent, "MOCK_LAMBDAS", False)
    return client


def make_db(positions, instruments, user=None):
    db = MagicMock()
    db.jobs.find_by_id.return_value = {"clerk_user_id": "user_1"}
    db.users.find_by_clerk_id.return_value = user
    db.accounts.find_by_user.return_value = [{"id": "a1", "cash_balance": "1000"}]
    db.positions.find_by_account.return_value = positions
    db.instruments.find_by_symbol.side_effect = lambda s: instruments.get(s)
    return db


FULL = {"allocation_regions": {"x": 1}, "allocation_sectors": {"x": 1}, "allocation_asset_class": {"x": 1}}


# ---------- invoke_lambda_agent ----------


def test_invoke_unwraps_api_style_response(lambda_client):
    lambda_client.invoke.return_value = lambda_response({"statusCode": 200, "body": json.dumps({"success": True})})
    result = asyncio.run(agent.invoke_lambda_agent("Reporter", "afp-reporter", {"job_id": "j"}))
    assert result == {"success": True}
    kwargs = lambda_client.invoke.call_args.kwargs
    assert kwargs["FunctionName"] == "afp-reporter"
    assert json.loads(kwargs["Payload"]) == {"job_id": "j"}


def test_invoke_handles_non_json_body(lambda_client):
    lambda_client.invoke.return_value = lambda_response({"statusCode": 200, "body": "plain text"})
    result = asyncio.run(agent.invoke_lambda_agent("X", "fn", {}))
    assert result == {"message": "plain text"}


def test_invoke_handles_dict_body(lambda_client):
    lambda_client.invoke.return_value = lambda_response({"statusCode": 200, "body": {"ok": 1}})
    assert asyncio.run(agent.invoke_lambda_agent("X", "fn", {})) == {"ok": 1}


def test_invoke_returns_error_on_exception(lambda_client):
    lambda_client.invoke.side_effect = RuntimeError("throttled")
    assert asyncio.run(agent.invoke_lambda_agent("X", "fn", {})) == {"error": "throttled"}


def test_invoke_mock_mode_skips_lambda(lambda_client, monkeypatch):
    monkeypatch.setattr(agent, "MOCK_LAMBDAS", True)
    result = asyncio.run(agent.invoke_lambda_agent("X", "fn", {}))
    assert result["mock"] is True
    lambda_client.invoke.assert_not_called()


@pytest.mark.parametrize(
    "func, name",
    [
        (agent.invoke_reporter_internal, "Reporter"),
        (agent.invoke_charter_internal, "Charter"),
        (agent.invoke_retirement_internal, "Retirement"),
    ],
)
def test_internal_invokers_report_success_and_failure(monkeypatch, func, name):
    async def ok(*args):
        return {"success": True}

    async def fail(*args):
        return {"error": "boom"}

    monkeypatch.setattr(agent, "invoke_lambda_agent", ok)
    assert "completed successfully" in asyncio.run(func("j"))
    monkeypatch.setattr(agent, "invoke_lambda_agent", fail)
    assert asyncio.run(func("j")) == f"{name} agent failed: boom"


# ---------- handle_missing_instruments ----------


def test_tags_only_instruments_missing_allocations(lambda_client):
    db = make_db(
        positions=[{"symbol": "SPY"}, {"symbol": "HALF"}, {"symbol": "UNKNOWN"}],
        instruments={"SPY": {"name": "S&P", **FULL}, "HALF": {"name": "Half", "allocation_regions": {"x": 1}}},
    )
    lambda_client.invoke.return_value = lambda_response({"statusCode": 200})

    agent.handle_missing_instruments("j", db)

    payload = json.loads(lambda_client.invoke.call_args.kwargs["Payload"])
    assert payload == {"instruments": [{"symbol": "HALF", "name": "Half"}, {"symbol": "UNKNOWN", "name": ""}]}


def test_does_not_call_tagger_when_everything_is_tagged(lambda_client):
    db = make_db(positions=[{"symbol": "SPY"}], instruments={"SPY": FULL})
    agent.handle_missing_instruments("j", db)
    lambda_client.invoke.assert_not_called()


def test_missing_job_is_a_no_op(lambda_client):
    db = MagicMock()
    db.jobs.find_by_id.return_value = None
    agent.handle_missing_instruments("j", db)
    db.accounts.find_by_user.assert_not_called()


def test_tagger_errors_do_not_raise(lambda_client):
    db = make_db(positions=[{"symbol": "X"}], instruments={})
    lambda_client.invoke.side_effect = RuntimeError("lambda down")
    agent.handle_missing_instruments("j", db)  # should log, not raise


# ---------- load_portfolio_summary ----------


def test_portfolio_summary():
    db = make_db(
        positions=[{"symbol": "SPY", "quantity": "10"}, {"symbol": "NOPRICE", "quantity": "5"}],
        instruments={"SPY": {"current_price": "500"}, "NOPRICE": {"current_price": None}},
        user={"years_until_retirement": 15, "target_retirement_income": "75000"},
    )
    assert agent.load_portfolio_summary("j", db) == {
        "total_value": 6000.0,
        "num_accounts": 1,
        "num_positions": 2,
        "years_until_retirement": 15,
        "target_retirement_income": 75000.0,
    }


def test_portfolio_summary_raises_for_missing_job_or_user():
    db = MagicMock()
    db.jobs.find_by_id.return_value = None
    with pytest.raises(ValueError, match="Job"):
        agent.load_portfolio_summary("j", db)

    db = make_db(positions=[], instruments={}, user=None)
    with pytest.raises(ValueError, match="User"):
        agent.load_portfolio_summary("j", db)


def test_create_agent(monkeypatch):
    monkeypatch.setattr(agent, "LitellmModel", lambda model: f"model:{model}")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.amazon.nova-pro-v1:0")
    model, tools, task, context = agent.create_agent(
        "j1", {"num_positions": 4, "years_until_retirement": 12}, db=None
    )
    assert model == "model:bedrock/us.amazon.nova-pro-v1:0"
    assert len(tools) == 3
    assert context.job_id == "j1"
    assert "4 positions" in task and "12 years" in task
