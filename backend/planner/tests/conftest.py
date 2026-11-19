"""Test setup: keep unit tests isolated from the real .env and AWS."""

import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

os.environ["AURORA_CLUSTER_ARN"] = "arn:aws:rds:us-east-1:123456789012:cluster:test"
os.environ["AURORA_SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test"
os.environ["DEFAULT_AWS_REGION"] = "us-east-1"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.pop("LANGFUSE_SECRET_KEY", None)
os.environ["OPENAI_AGENTS_DISABLE_TRACING"] = "1"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
