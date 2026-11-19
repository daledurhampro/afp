"""
Shared test setup for the database package.

Unit tests must never touch real AWS, so we:
- stop python-dotenv from loading the developer's real .env file
- provide fake Aurora configuration so DataAPIClient can be constructed
"""

import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False

os.environ["AURORA_CLUSTER_ARN"] = "arn:aws:rds:us-east-1:123456789012:cluster:test"
os.environ["AURORA_SECRET_ARN"] = "arn:aws:secretsmanager:us-east-1:123456789012:secret:test"
os.environ["DEFAULT_AWS_REGION"] = "us-east-1"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

# Make the `src` package importable when running from backend/database
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
