"""Unit tests for the EventBridge scheduler Lambda (HTTP call mocked)."""

import io
import json

import pytest

import lambda_function


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    def fake_urlopen(request, timeout):
        calls["url"] = request.full_url
        calls["method"] = request.get_method()
        calls["body"] = request.data
        calls["timeout"] = timeout
        return FakeResponse(b'"ok"')

    monkeypatch.setattr(lambda_function.urllib.request, "urlopen", fake_urlopen)
    return calls


def test_requires_app_runner_url(monkeypatch):
    monkeypatch.delenv("APP_RUNNER_URL", raising=False)
    with pytest.raises(ValueError, match="APP_RUNNER_URL"):
        lambda_function.handler({}, None)


@pytest.mark.parametrize("url", ["abc.awsapprunner.com", "https://abc.awsapprunner.com", "http://abc.awsapprunner.com"])
def test_posts_to_research_endpoint_over_https(monkeypatch, captured, url):
    monkeypatch.setenv("APP_RUNNER_URL", url)
    response = lambda_function.handler({}, None)
    assert response["statusCode"] == 200
    assert captured["url"] == "https://abc.awsapprunner.com/research"
    assert captured["method"] == "POST"
    assert json.loads(captured["body"]) == {}


def test_returns_500_when_request_fails(monkeypatch):
    monkeypatch.setenv("APP_RUNNER_URL", "abc.awsapprunner.com")

    def boom(request, timeout):
        raise OSError("connection refused")

    monkeypatch.setattr(lambda_function.urllib.request, "urlopen", boom)
    response = lambda_function.handler({}, None)
    assert response["statusCode"] == 500
    assert "connection refused" in response["body"]
