#!/usr/bin/env python3
"""
Run the unit tests for every backend project.

Each backend directory is its own uv project with its own dependencies, so the
tests are run separately in each one. pytest is supplied with `uv run --with`,
so it is not added to any project's dependencies (and never ends up in a
Lambda package).

These are unit tests: AWS, Bedrock, Clerk and the database are all mocked, and
your .env file is not loaded, so they cost nothing and need no deployed
infrastructure.

Usage (from the scripts directory):
    uv run run_tests.py              # run all projects
    uv run run_tests.py api planner  # run only some projects
    uv run run_tests.py -- -x -vv    # pass extra options to pytest
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent / "backend"

PROJECTS = [
    "database",
    "api",
    "planner",
    "tagger",
    "reporter",
    "charter",
    "retirement",
    "researcher",
    "ingest",
    "scheduler",
]


def main() -> int:
    args = sys.argv[1:]
    pytest_args = []
    if "--" in args:
        split = args.index("--")
        args, pytest_args = args[:split], args[split + 1 :]

    selected = args or PROJECTS
    unknown = [p for p in selected if p not in PROJECTS]
    if unknown:
        print(f"Unknown project(s): {', '.join(unknown)}. Choose from: {', '.join(PROJECTS)}")
        return 2

    # The scripts project's own virtualenv must not leak into the other projects
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}

    results = {}
    for project in selected:
        print(f"\n{'=' * 60}\n🧪 {project}\n{'=' * 60}", flush=True)
        cmd = ["uv", "run", "--with", "pytest", "pytest", "tests", "-q", "-p", "no:cacheprovider", *pytest_args]
        results[project] = subprocess.run(cmd, cwd=BACKEND / project, env=env).returncode

    print(f"\n{'=' * 60}\nSummary\n{'=' * 60}")
    for project, code in results.items():
        print(f"  {'✅' if code == 0 else '❌'} {project}")

    failed = [p for p, code in results.items() if code != 0]
    if failed:
        print(f"\n{len(failed)} project(s) failed: {', '.join(failed)}")
        return 1
    print("\nAll unit tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
