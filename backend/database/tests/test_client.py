"""Unit tests for the Aurora Data API client wrapper (no AWS calls)."""

from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from src.client import DataAPIClient


@pytest.fixture
def client():
    c = DataAPIClient()
    c.client = MagicMock()  # replace the boto3 rds-data client
    return c


def last_call_kwargs(client):
    return client.client.execute_statement.call_args.kwargs


# ---------- construction ----------


def test_missing_configuration_raises(monkeypatch):
    monkeypatch.delenv("AURORA_CLUSTER_ARN")
    with pytest.raises(ValueError, match="Missing required Aurora configuration"):
        DataAPIClient()


def test_explicit_arguments_override_environment():
    c = DataAPIClient(cluster_arn="cluster-x", secret_arn="secret-y", database="db-z")
    assert (c.cluster_arn, c.secret_arn, c.database) == ("cluster-x", "secret-y", "db-z")


def test_database_defaults_to_afp(monkeypatch):
    monkeypatch.delenv("AURORA_DATABASE", raising=False)
    assert DataAPIClient().database == "afp"


# ---------- _build_parameters ----------


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, {"isNull": True}),
        (True, {"booleanValue": True}),
        (42, {"longValue": 42}),
        (1.5, {"doubleValue": 1.5}),
        (Decimal("12.34"), {"stringValue": "12.34"}),
        (date(2026, 1, 2), {"stringValue": "2026-01-02"}),
        (datetime(2026, 1, 2, 3, 4, 5), {"stringValue": "2026-01-02T03:04:05"}),
        ({"equity": 100}, {"stringValue": '{"equity": 100}'}),
        ([1, 2], {"stringValue": "[1, 2]"}),
        ("hello", {"stringValue": "hello"}),
    ],
)
def test_build_parameters_types(client, value, expected):
    assert client._build_parameters({"col": value}) == [{"name": "col", "value": expected}]


def test_build_parameters_bool_is_not_treated_as_int(client):
    # bool is a subclass of int, so ordering of the isinstance checks matters
    assert client._build_parameters({"flag": False})[0]["value"] == {"booleanValue": False}


def test_build_parameters_empty(client):
    assert client._build_parameters({}) == []
    assert client._build_parameters(None) == []


# ---------- _extract_value ----------


@pytest.mark.parametrize(
    "field, expected",
    [
        ({"isNull": True}, None),
        ({"booleanValue": False}, False),
        ({"longValue": 7}, 7),
        ({"doubleValue": 2.5}, 2.5),
        ({"stringValue": "plain"}, "plain"),
        ({"stringValue": '{"a": 1}'}, {"a": 1}),
        ({"stringValue": "[1, 2]"}, [1, 2]),
        ({"stringValue": "{not json"}, "{not json"),
        ({"stringValue": ""}, ""),
        ({"blobValue": b"\x00"}, b"\x00"),
        ({}, None),
    ],
)
def test_extract_value(client, field, expected):
    assert client._extract_value(field) == expected


# ---------- query / query_one ----------


def test_query_maps_columns_to_dicts(client):
    client.client.execute_statement.return_value = {
        "columnMetadata": [{"name": "symbol"}, {"name": "price"}],
        "records": [
            [{"stringValue": "SPY"}, {"doubleValue": 590.0}],
            [{"stringValue": "BND"}, {"isNull": True}],
        ],
    }
    assert client.query("SELECT ...") == [
        {"symbol": "SPY", "price": 590.0},
        {"symbol": "BND", "price": None},
    ]


def test_query_without_records_returns_empty_list(client):
    client.client.execute_statement.return_value = {}
    assert client.query("SELECT ...") == []


def test_query_one_returns_first_or_none(client):
    client.client.execute_statement.return_value = {
        "columnMetadata": [{"name": "id"}],
        "records": [[{"longValue": 1}], [{"longValue": 2}]],
    }
    assert client.query_one("SELECT ...") == {"id": 1}

    client.client.execute_statement.return_value = {"columnMetadata": [], "records": []}
    assert client.query_one("SELECT ...") is None


def test_execute_passes_arns_and_parameters(client):
    client.client.execute_statement.return_value = {}
    params = [{"name": "x", "value": {"longValue": 1}}]
    client.execute("SELECT 1", params)
    kwargs = last_call_kwargs(client)
    assert kwargs["resourceArn"] == client.cluster_arn
    assert kwargs["secretArn"] == client.secret_arn
    assert kwargs["database"] == client.database
    assert kwargs["parameters"] == params
    assert kwargs["includeResultMetadata"] is True


def test_execute_omits_parameters_when_none(client):
    client.client.execute_statement.return_value = {}
    client.execute("SELECT 1")
    assert "parameters" not in last_call_kwargs(client)


# ---------- insert / update / delete ----------


def test_insert_adds_type_casts_and_returning(client):
    client.client.execute_statement.return_value = {"records": [[{"stringValue": "new-id"}]]}
    result = client.insert(
        "accounts",
        {
            "name": "401k",
            "cash_balance": Decimal("10.00"),
            "meta": {"a": 1},
            "as_of": date(2026, 1, 1),
            "ts": datetime(2026, 1, 1, 12, 0),
        },
        returning="id",
    )
    sql = last_call_kwargs(client)["sql"]
    assert result == "new-id"
    assert ":name," in sql
    assert ":cash_balance::numeric" in sql
    assert ":meta::jsonb" in sql
    assert ":as_of::date" in sql
    assert ":ts::timestamp" in sql
    assert "RETURNING id" in sql


def test_insert_without_returning_returns_none(client):
    client.client.execute_statement.return_value = {}
    assert client.insert("t", {"a": 1}) is None
    assert "RETURNING" not in last_call_kwargs(client)["sql"]


def test_update_builds_set_clause_and_merges_where_params(client):
    client.client.execute_statement.return_value = {"numberOfRecordsUpdated": 3}
    rows = client.update("jobs", {"status": "done", "payload": {"k": "v"}}, "id = :id::uuid", {"id": "j1"})
    kwargs = last_call_kwargs(client)
    assert rows == 3
    assert "status = :status" in kwargs["sql"]
    assert "payload = :payload::jsonb" in kwargs["sql"]
    assert "WHERE id = :id::uuid" in kwargs["sql"]
    assert {p["name"] for p in kwargs["parameters"]} == {"status", "payload", "id"}


def test_delete_returns_row_count(client):
    client.client.execute_statement.return_value = {"numberOfRecordsUpdated": 1}
    assert client.delete("accounts", "id = :id::uuid", {"id": "a1"}) == 1
    assert last_call_kwargs(client)["sql"] == "DELETE FROM accounts WHERE id = :id::uuid"


def test_transactions_use_client(client):
    client.client.begin_transaction.return_value = {"transactionId": "tx-1"}
    assert client.begin_transaction() == "tx-1"
    client.commit_transaction("tx-1")
    client.rollback_transaction("tx-1")
    assert client.client.commit_transaction.call_args.kwargs["transactionId"] == "tx-1"
    assert client.client.rollback_transaction.call_args.kwargs["transactionId"] == "tx-1"
