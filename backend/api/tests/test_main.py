"""Unit tests for the FastAPI routes, with the database, SQS and Clerk mocked."""

import json

import pytest

import main
from conftest import USER_ID

OTHER_USER = "user_mallory"
NOT_FOUND = "The requested resource was not found."
FORBIDDEN = "You don't have permission to access this resource."


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_routes_require_authentication(db):
    # Without the dependency overrides, the real Clerk guard rejects missing tokens
    from fastapi.testclient import TestClient

    main.app.dependency_overrides.clear()
    response = TestClient(main.app).get("/api/accounts")
    assert response.status_code in (401, 403)
    db.accounts.find_by_user.assert_not_called()


# ---------- user ----------


def test_get_existing_user(client, db):
    db.users.find_by_clerk_id.return_value = {"clerk_user_id": USER_ID}
    response = client.get("/api/user")
    assert response.json() == {"user": {"clerk_user_id": USER_ID}, "created": False}
    db.users.db.insert.assert_not_called()


def test_first_visit_creates_user_with_defaults(client, db):
    db.users.find_by_clerk_id.side_effect = [None, {"clerk_user_id": USER_ID, "display_name": "Alice"}]
    response = client.get("/api/user")
    assert response.json()["created"] is True
    table, data = db.users.db.insert.call_args.args
    assert table == "users"
    assert data["clerk_user_id"] == USER_ID
    assert data["display_name"] == "Alice"
    assert data["years_until_retirement"] == 20


def test_update_user_only_sends_fields_provided(client, db):
    db.users.find_by_clerk_id.return_value = {"clerk_user_id": USER_ID}
    response = client.put("/api/user", json={"years_until_retirement": 15})
    assert response.status_code == 200
    table, data, where, params = db.users.db.update.call_args.args
    assert data == {"years_until_retirement": 15}
    assert params == {"clerk_user_id": USER_ID}


# ---------- accounts ----------


def test_list_accounts_is_scoped_to_signed_in_user(client, db):
    db.accounts.find_by_user.return_value = [{"id": "a1"}]
    assert client.get("/api/accounts").json() == [{"id": "a1"}]
    db.accounts.find_by_user.assert_called_once_with(USER_ID)


def test_create_account(client, db):
    db.users.find_by_clerk_id.return_value = {"clerk_user_id": USER_ID}
    db.accounts.create_account.return_value = "a1"
    db.accounts.find_by_id.return_value = {"id": "a1", "account_name": "Roth"}
    response = client.post("/api/accounts", json={"account_name": "Roth", "cash_balance": "100.50"})
    assert response.status_code == 200
    assert db.accounts.create_account.call_args.kwargs["clerk_user_id"] == USER_ID
    assert str(db.accounts.create_account.call_args.kwargs["cash_balance"]) == "100.50"


def test_create_account_validates_input(client, db):
    response = client.post("/api/accounts", json={"account_name": ""})
    assert response.status_code == 422
    db.accounts.create_account.assert_not_called()


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("put", "/api/accounts/a1", {"account_name": "x"}),
        ("delete", "/api/accounts/a1", None),
        ("get", "/api/accounts/a1/positions", None),
    ],
)
def test_account_routes_block_other_users(client, db, method, path, body):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": OTHER_USER}
    response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json()["detail"] == FORBIDDEN
    db.accounts.update.assert_not_called()
    db.accounts.delete.assert_not_called()
    db.positions.find_by_account.assert_not_called()


@pytest.mark.parametrize(
    "method, path", [("put", "/api/accounts/a1"), ("delete", "/api/accounts/a1"), ("get", "/api/accounts/a1/positions")]
)
def test_account_routes_404_for_missing_account(client, db, method, path):
    db.accounts.find_by_id.return_value = None
    response = client.request(method, path, json={} if method == "put" else None)
    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND


def test_update_own_account(client, db):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": USER_ID}
    response = client.put("/api/accounts/a1", json={"cash_balance": 250.0})
    assert response.status_code == 200
    db.accounts.update.assert_called_once_with("a1", {"cash_balance": 250.0})


def test_delete_own_account_removes_positions_first(client, db):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": USER_ID}
    db.positions.find_by_account.return_value = [{"id": "p1"}, {"id": "p2"}]
    response = client.delete("/api/accounts/a1")
    assert response.status_code == 200
    assert [c.args[0] for c in db.positions.delete.call_args_list] == ["p1", "p2"]
    db.accounts.delete.assert_called_once_with("a1")


def test_list_positions_attaches_instrument(client, db):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": USER_ID}
    db.positions.find_by_account.return_value = [{"id": "p1", "symbol": "SPY"}]
    db.instruments.find_by_symbol.return_value = {"symbol": "SPY", "name": "S&P 500"}
    response = client.get("/api/accounts/a1/positions")
    assert response.json() == {"positions": [{"id": "p1", "symbol": "SPY", "instrument": {"symbol": "SPY", "name": "S&P 500"}}]}


# ---------- positions ----------


def test_create_position_uppercases_symbol(client, db):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": USER_ID}
    db.instruments.find_by_symbol.return_value = {"symbol": "SPY"}
    db.positions.add_position.return_value = "p1"
    db.positions.find_by_id.return_value = {"id": "p1"}

    response = client.post("/api/positions", json={"account_id": "a1", "symbol": "spy", "quantity": "3"})

    assert response.status_code == 200
    assert db.positions.add_position.call_args.kwargs["symbol"] == "SPY"
    db.instruments.create_instrument.assert_not_called()


def test_create_position_creates_unknown_instrument(client, db):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": USER_ID}
    db.instruments.find_by_symbol.return_value = None
    db.positions.add_position.return_value = "p1"

    client.post("/api/positions", json={"account_id": "a1", "symbol": "abcd", "quantity": "1"})

    instrument = db.instruments.create_instrument.call_args.args[0]
    assert instrument.symbol == "ABCD"
    assert instrument.instrument_type == "stock"
    assert instrument.allocation_asset_class == {"equity": 100.0}


def test_create_position_in_another_users_account_is_forbidden(client, db):
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": OTHER_USER}
    response = client.post("/api/positions", json={"account_id": "a1", "symbol": "SPY", "quantity": "1"})
    assert response.status_code == 403
    db.positions.add_position.assert_not_called()


@pytest.mark.parametrize("quantity", ["0", "-5"])
def test_create_position_rejects_non_positive_quantity(client, db, quantity):
    response = client.post("/api/positions", json={"account_id": "a1", "symbol": "SPY", "quantity": quantity})
    assert response.status_code == 422


@pytest.mark.parametrize("method", ["put", "delete"])
def test_position_routes_block_other_users(client, db, method):
    db.positions.find_by_id.return_value = {"id": "p1", "account_id": "a1"}
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": OTHER_USER}
    response = client.request(method, "/api/positions/p1", json={"quantity": 1} if method == "put" else None)
    assert response.status_code == 403
    db.positions.update.assert_not_called()
    db.positions.delete.assert_not_called()


def test_update_own_position(client, db):
    db.positions.find_by_id.return_value = {"id": "p1", "account_id": "a1"}
    db.accounts.find_by_id.return_value = {"id": "a1", "clerk_user_id": USER_ID}
    assert client.put("/api/positions/p1", json={"quantity": 12.5}).status_code == 200
    db.positions.update.assert_called_once_with("p1", {"quantity": 12.5})


def test_missing_position_is_404(client, db):
    db.positions.find_by_id.return_value = None
    assert client.delete("/api/positions/p1").status_code == 404


# ---------- instruments ----------


def test_list_instruments_simplifies_rows(client, db):
    db.instruments.find_all.return_value = [
        {"symbol": "SPY", "name": "S&P", "instrument_type": "etf", "current_price": "590.10", "extra": 1},
        {"symbol": "NEW", "name": "New", "instrument_type": "stock", "current_price": None},
    ]
    assert client.get("/api/instruments").json() == [
        {"symbol": "SPY", "name": "S&P", "instrument_type": "etf", "current_price": 590.1},
        {"symbol": "NEW", "name": "New", "instrument_type": "stock", "current_price": None},
    ]


# ---------- analysis jobs ----------


def test_trigger_analysis_creates_job_and_queues_message(client, db, sqs, monkeypatch):
    monkeypatch.setattr(main, "SQS_QUEUE_URL", "https://sqs.example/queue")
    db.users.find_by_clerk_id.return_value = {"clerk_user_id": USER_ID}
    db.jobs.create_job.return_value = "job-1"

    response = client.post("/api/analyze", json={"analysis_type": "portfolio", "options": {"x": 1}})

    assert response.status_code == 200
    assert response.json()["job_id"] == "job-1"
    assert db.jobs.create_job.call_args.kwargs["clerk_user_id"] == USER_ID
    kwargs = sqs.send_message.call_args.kwargs
    assert kwargs["QueueUrl"] == "https://sqs.example/queue"
    assert json.loads(kwargs["MessageBody"]) == {
        "job_id": "job-1", "clerk_user_id": USER_ID, "analysis_type": "portfolio", "options": {"x": 1}
    }


def test_trigger_analysis_without_queue_url_does_not_send(client, db, sqs, monkeypatch):
    monkeypatch.setattr(main, "SQS_QUEUE_URL", "")
    db.users.find_by_clerk_id.return_value = {"clerk_user_id": USER_ID}
    db.jobs.create_job.return_value = "job-1"
    assert client.post("/api/analyze", json={}).status_code == 200
    sqs.send_message.assert_not_called()


def test_get_job_checks_ownership(client, db):
    db.jobs.find_by_id.return_value = {"id": "j1", "clerk_user_id": OTHER_USER}
    assert client.get("/api/jobs/j1").status_code == 403

    db.jobs.find_by_id.return_value = {"id": "j1", "clerk_user_id": USER_ID, "status": "completed"}
    assert client.get("/api/jobs/j1").json()["status"] == "completed"

    db.jobs.find_by_id.return_value = None
    assert client.get("/api/jobs/j1").status_code == 404


def test_list_jobs_sorted_newest_first(client, db):
    db.jobs.find_by_user.return_value = [
        {"id": "old", "created_at": "2026-01-01"},
        {"id": "new", "created_at": "2026-03-01"},
    ]
    response = client.get("/api/jobs")
    assert [j["id"] for j in response.json()["jobs"]] == ["new", "old"]
    db.jobs.find_by_user.assert_called_once_with(USER_ID, limit=100)


def test_reset_accounts_counts_deletions_and_continues_on_error(client, db):
    db.users.find_by_clerk_id.return_value = {"clerk_user_id": USER_ID}
    db.accounts.find_by_user.return_value = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
    db.accounts.delete.side_effect = [1, RuntimeError("locked"), 1]
    response = client.delete("/api/reset-accounts")
    assert response.json()["accounts_deleted"] == 2
    db.accounts.find_by_user.assert_called_once_with(USER_ID)


def test_unexpected_errors_do_not_leak_details(client, db):
    db.accounts.find_by_user.side_effect = RuntimeError("secret connection string")
    response = client.get("/api/accounts")
    assert response.status_code == 500
    assert "secret" not in response.text


# ---------- missing user ----------


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("put", "/api/user", {"display_name": "x"}),
        ("post", "/api/accounts", {"account_name": "x"}),
        ("post", "/api/analyze", {}),
        ("delete", "/api/reset-accounts", None),
        ("post", "/api/populate-test-data", None),
    ],
)
def test_missing_user_returns_404(client, db, method, path, body):
    db.users.find_by_clerk_id.return_value = None
    response = client.request(method, path, json=body)
    assert response.status_code == 404
    assert response.json()["detail"] == NOT_FOUND
    db.accounts.create_account.assert_not_called()
    db.jobs.create_job.assert_not_called()
