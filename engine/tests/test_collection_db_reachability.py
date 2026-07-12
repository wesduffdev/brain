"""Regression for BUG #81: an ambient DATABASE_URL to an unreachable server must
not break collection of non-integration tests (app.main connects at import)."""
import os
import subprocess
import sys
from pathlib import Path


def test_unreachable_database_url_does_not_break_collection():
    engine_dir = Path(__file__).resolve().parent.parent
    env = {
        **os.environ,
        "DATABASE_URL": "postgresql+psycopg://x:x@127.0.0.1:59999/none",  # closed port
        "PYTHONPATH": ".",
    }
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_voice.py", "--collect-only", "-q"],
        cwd=str(engine_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert r.returncode == 0, f"collection failed:\n{r.stdout}\n{r.stderr}"
    assert "error" not in r.stdout.lower(), r.stdout
