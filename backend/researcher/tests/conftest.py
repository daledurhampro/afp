"""Test setup: keep unit tests isolated from the real .env and the ingest API."""

import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv = lambda *args, **kwargs: False
os.environ.pop("AFP_API_ENDPOINT", None)
os.environ.pop("AFP_API_KEY", None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
