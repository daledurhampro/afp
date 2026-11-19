"""Unit tests for the Researcher's ingest tool (HTTP calls mocked)."""

import asyncio
import json

import pytest

import tools


def call_tool(topic, analysis):
    """Invoke the tool the way the Agents SDK does; returns the tool output as text."""
    result = asyncio.run(
        tools.ingest_financial_document.on_invoke_tool(None, json.dumps({"topic": topic, "analysis": analysis}))
    )
    return str(result)


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(tools, "AFP_API_ENDPOINT", "https://api.example/ingest")
    monkeypatch.setattr(tools, "AFP_API_KEY", "key")


def test_not_configured_returns_local_mode_message(monkeypatch):
    monkeypatch.setattr(tools, "AFP_API_ENDPOINT", None)
    result = call_tool("AAPL", "text")
    assert "not configured" in result


def test_successful_ingest(configured, monkeypatch):
    sent = {}

    def fake_ingest(document):
        sent.update(document)
        return {"document_id": "doc-1"}

    monkeypatch.setattr(tools, "ingest_with_retries", fake_ingest)
    result = call_tool("AAPL Analysis", "Apple looks strong")

    assert "doc-1" in result and "Successfully ingested" in result
    assert sent["text"] == "Apple looks strong"
    assert sent["metadata"]["topic"] == "AAPL Analysis"
    assert "timestamp" in sent["metadata"]


def test_failed_ingest_returns_error(configured, monkeypatch):
    def boom(document):
        raise RuntimeError("503 from API Gateway")

    monkeypatch.setattr(tools, "ingest_with_retries", boom)
    result = call_tool("AAPL", "text")
    assert "503 from API Gateway" in result


def test_ingest_retries_then_succeeds(monkeypatch):
    attempts = []

    def flaky(document):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("cold start")
        return {"document_id": "doc-2"}

    monkeypatch.setattr(tools, "_ingest", flaky)
    monkeypatch.setattr(tools.ingest_with_retries.retry, "sleep", lambda seconds: None)
    assert tools.ingest_with_retries({"text": "x"}) == {"document_id": "doc-2"}
    assert len(attempts) == 3
