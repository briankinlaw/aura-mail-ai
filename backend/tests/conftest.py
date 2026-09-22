import os
import pytest
from unittest.mock import patch
import starlette.testclient

# In Phase 6, production ASGI middleware strictly enforces loopback client IP (127.0.0.1/::1)
# and TrustedHostMiddleware strictly enforces loopback hostnames (localhost/127.0.0.1).
# Patch TestClient default constructor parameters for tests so they connect via canonical loopback
# while allowing tests to explicitly pass arbitrary base_url or client for adversarial verification.
_orig_testclient_init = starlette.testclient.TestClient.__init__

def _patched_testclient_init(
    self,
    app,
    base_url: str = "https://localhost:8000",
    client: tuple = ("127.0.0.1", 50000),
    **kwargs
):
    if base_url == "http://testserver":
        base_url = "https://localhost:8000"
    if client == ("testclient", 50000):
        client = ("127.0.0.1", 50000)
    _orig_testclient_init(self, app, base_url=base_url, client=client, **kwargs)

starlette.testclient.TestClient.__init__ = _patched_testclient_init

@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """
    Ensures unit and regression tests run in offline isolation,
    preventing slow outbound network calls to LLM services unless explicitly mocked.
    Also resets provenance store to ensure consistent test execution.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "")
    try:
        test_reset_provenance_store()
    except Exception:
        pass
    with patch("backend.radar.triage_service.get_gemini_client", return_value=None), \
         patch("backend.radar.scribe_service.get_gemini_client", return_value=None):
        yield
    try:
        test_reset_provenance_store()
    except Exception:
        pass


def test_reset_provenance_store(store=None):
    """
    Test helper providing offline administrative recovery for test suite resets.
    Not exported or used in production runtime code.
    """
    from backend.canonical_grounding import PROVENANCE_STORE
    from backend.offline_recovery import (
        _write_empty_store_atomically,
        _verify_empty_store,
        _remove_disabled_marker,
        _validate_provenance_paths,
    )
    target_store = store or PROVENANCE_STORE
    target_dir = target_store.storage_path.parent
    storage_path, state_path, lock_path, audit_path = _validate_provenance_paths(target_dir)
    _write_empty_store_atomically(target_dir, storage_path)
    _verify_empty_store(storage_path)
    if state_path.exists():
        _remove_disabled_marker(state_path)
    target_store._load()
