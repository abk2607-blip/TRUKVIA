"""Iter130 · Pytest bootstrap — load /app/backend/.env before test collection.

Uvicorn/supervisor loads the .env for the running app; pytest invoked
directly from a shell does not. Every test that reads DEMO_TOKEN_VALUE,
IS_PREVIEW_ENV, MONGO_URL, etc. at import time needs these vars present
by the time collection starts. This conftest is loaded first by pytest's
own discovery, before any test-file `import os` line executes."""
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path("/app/backend/.env"))
except Exception:
    # dotenv is a runtime dep of the backend; if it is somehow missing we
    # fall back to a minimal manual parser so tests can still run.
    env_path = Path("/app/backend/.env")
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
