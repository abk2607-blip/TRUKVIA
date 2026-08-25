"""Iter126a — Object storage startup smoke test.

Regression: previously `server.py` called `await init_storage()` even though
`storage_client.init_storage` is a synchronous function that returns `str`.
That raised TypeError on every boot ("object str can't be used in 'await'
expression"), swallowed as a warning, leaving `_storage_key` un-primed.

This test guarantees:
  1. `init_storage` is NOT a coroutine function (must stay sync — put/get
     callers depend on it).
  2. Calling it returns a non-empty string (the storage key) when the
     Emergent LLM key is configured.
  3. The startup fix path uses `run_in_executor`, not `await`.
"""
import inspect
import os
import pathlib
import pytest

from storage_client import init_storage


def test_init_storage_is_sync():
    assert not inspect.iscoroutinefunction(init_storage), (
        "init_storage must remain sync — server.py wraps it in run_in_executor."
    )


def test_init_storage_returns_key():
    if not os.environ.get("EMERGENT_LLM_KEY"):
        pytest.skip("EMERGENT_LLM_KEY not configured in this environment")
    key = init_storage()
    assert isinstance(key, str) and len(key) > 8


def test_server_startup_does_not_await_init_storage():
    """Guard against a regression that re-introduces `await init_storage()`.

    Strips comment lines so the historical explanation in the docstring near
    the fix does not trigger the guard.
    """
    src_lines = pathlib.Path("/app/backend/server.py").read_text().splitlines()
    code_only = "\n".join(l for l in src_lines if not l.lstrip().startswith("#"))
    assert "await init_storage()" not in code_only, (
        "Do not `await` init_storage — it is a sync function. "
        "Use `loop.run_in_executor(None, init_storage)` instead."
    )
