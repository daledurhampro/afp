"""Unit tests for the table model classes, using a mocked DataAPIClient."""

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.models import Accounts, BaseModel, Database, Instruments, Jobs, Positions, Users
from src.schemas import InstrumentCreate


@pytest.fixture
def client():
    return MagicMock()


def params_by_name(params):
    return {p["name"]: p["value"] for p in params}


def test_base_model_requires_table_name(client):
    with pytest.raises(ValueError, match="table_name"):
        BaseModel(client)


def test_find_by_id_casts_to_uuid(client):
    Accounts(client).find_by_id("abc")
    sql, params = client.query_one.call_args.args
    assert "FROM accounts WHERE id = :id::uuid" in sql
    assert params_by_name(params)["id"] == {"stringValue": "abc"}


def test_update_and_delete_scope_by_id(client):
    Positions(client).update("p1", {"quantity": 5})
    client.update.assert_called_once_with("positions", {"quantity": 5}, "id = :id::uuid", {"id": "p1"})
    Positions(client).delete("p1")
    client.delete.assert_called_once_with("positions", "id = :id::uuid", {"id": "p1"})


def test_users_create_user_drops_none_values(client):
    Users(client).create_user("user_1", display_name="Dee")
    table, data = client.insert.call_args.args
    assert table == "users"
    assert data == {"clerk_user_id": "user_1", "display_name": "Dee"}
    assert client.insert.call_args.kwargs["returning"] == "clerk_user_id"


def test_users_find_by_clerk_id(client):
    Users(client).find_by_clerk_id("user_1")
    sql, params = client.query_one.call_args.args
    assert "clerk_user_id = :clerk_id" in sql
    assert params_by_name(params)["clerk_id"] == {"stringValue": "user_1"}


def test_accounts_find_by_user_filters_on_clerk_id(client):
    Accounts(client).find_by_user("user_1")
    sql, params = client.query.call_args.args
    assert "WHERE clerk_user_id = :user_id" in sql
    assert params_by_name(params)["user_id"] == {"stringValue": "user_1"}


def test_instruments_create_instrument_stores_allocations(client):
    inst = InstrumentCreate(
        symbol="BND",
        name="Vanguard Total Bond",
        instrument_type="etf",
        allocation_regions={"north_america": 100},
        allocation_sectors={"treasury": 100},
        allocation_asset_class={"fixed_income": 100},
    )
    Instruments(client).create_instrument(inst)
    table, data = client.insert.call_args.args
    assert table == "instruments"
    assert data["symbol"] == "BND"
    assert data["allocation_asset_class"] == {"fixed_income": 100}
    assert client.insert.call_args.kwargs["returning"] == "symbol"


def test_instruments_search_wraps_query_in_wildcards(client):
    Instruments(client).search("van")
    _, params = client.query.call_args.args
    assert params_by_name(params)["query"] == {"stringValue": "%van%"}


def test_positions_add_position_returns_new_id(client):
    client.execute.return_value = {"records": [[{"stringValue": "pos-1"}]]}
    assert Positions(client).add_position("acct-1", "SPY", Decimal("10")) == "pos-1"
    sql, params = client.execute.call_args.args
    assert "ON CONFLICT (account_id, symbol)" in sql
    assert params_by_name(params)["quantity"] == {"stringValue": "10"}


def test_positions_add_position_without_records_returns_none(client):
    client.execute.return_value = {}
    assert Positions(client).add_position("acct-1", "SPY", Decimal("1")) is None


def test_positions_portfolio_value(client):
    client.query_one.return_value = {"num_positions": 2, "total_value": "1500.5", "total_shares": "12"}
    assert Positions(client).get_portfolio_value("a1") == {
        "num_positions": 2,
        "total_value": 1500.5,
        "total_shares": 12.0,
    }


def test_positions_portfolio_value_empty(client):
    client.query_one.return_value = None
    assert Positions(client).get_portfolio_value("a1") == {"num_positions": 0, "total_value": 0, "total_shares": 0}


def test_jobs_create_job_starts_pending(client):
    Jobs(client).create_job("user_1", "portfolio_analysis", {"x": 1})
    _, data = client.insert.call_args.args
    assert data["status"] == "pending"
    assert data["request_payload"] == {"x": 1}


@pytest.mark.parametrize(
    "status, timestamp_field",
    [("running", "started_at"), ("completed", "completed_at"), ("failed", "completed_at")],
)
def test_jobs_update_status_sets_timestamps(client, status, timestamp_field):
    Jobs(client).update_status("j1", status, error_message="boom" if status == "failed" else None)
    _, data, where, where_params = client.update.call_args.args
    assert data["status"] == status
    assert timestamp_field in data
    assert where_params == {"id": "j1"}
    assert ("error_message" in data) == (status == "failed")


@pytest.mark.parametrize(
    "method, column",
    [
        ("update_report", "report_payload"),
        ("update_charts", "charts_payload"),
        ("update_retirement", "retirement_payload"),
        ("update_summary", "summary_payload"),
    ],
)
def test_jobs_payload_updates(client, method, column):
    getattr(Jobs(client), method)("j1", {"k": "v"})
    _, data, _, _ = client.update.call_args.args
    assert data == {column: {"k": "v"}}


def test_jobs_find_by_user_with_and_without_status(client):
    jobs = Jobs(client)
    jobs.find_by_user("user_1", limit=5)
    sql, params = client.query.call_args.args
    assert "status = :status" not in sql
    assert params_by_name(params)["limit"] == {"longValue": 5}

    jobs.find_by_user("user_1", status="completed")
    sql, params = client.query.call_args.args
    assert "status = :status" in sql
    assert params_by_name(params)["status"] == {"stringValue": "completed"}


def test_database_wires_up_all_models():
    db = Database()
    for name in ["users", "instruments", "accounts", "positions", "jobs"]:
        assert getattr(db, name).db is db.client
