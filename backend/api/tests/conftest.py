"""
Test setup for the FastAPI backend.

- python-dotenv is disabled so the developer's real .env (and real ARNs / SQS URL) are never used
- the database and SQS client are replaced with mocks
- Clerk authentication is overridden so each test chooses the signed-in user
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import dotenv
import pytest

dotenv.load_dotenv = lambda *args, **kwargs: False

os.environ["AURORA_CLUSTER_ARN"] = "arn:aws:rds:us-east-1:123456789012:cluster:test"
os.environ["AURORA_SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test"
os.environ["DEFAULT_AWS_REGION"] = "us-east-1"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["CLERK_JWKS_URL"] = "https://example.invalid/.well-known/jwks.json"
os.environ["SQS_QUEUE_URL"] = ""

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

USER_ID = "user_alice"


@pytest.fixture
def db(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(main, "db", fake)
    return fake


@pytest.fixture
def sqs(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(main, "sqs_client", fake)
    return fake


@pytest.fixture
def client(db, sqs):
    class Creds:
        decoded = {"sub": USER_ID, "name": "Alice", "email": "alice@example.com"}

    main.app.dependency_overrides[main.get_current_user_id] = lambda: USER_ID
    main.app.dependency_overrides[main.clerk_guard] = lambda: Creds()
    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.dependency_overrides.clear()
