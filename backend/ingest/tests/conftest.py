"""Test setup: keep unit tests isolated from the real .env and AWS."""

import os
import sys
from pathlib import Path

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ["VECTOR_BUCKET"] = "test-vectors"
os.environ["SAGEMAKER_ENDPOINT"] = "test-endpoint"
os.environ["INDEX_NAME"] = "test-index"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
