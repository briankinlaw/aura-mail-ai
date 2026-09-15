import os
import pytest
from unittest.mock import patch

@pytest.fixture(autouse=True)
def isolate_test_environment(monkeypatch):
    """
    Ensures unit and regression tests run in offline isolation,
    preventing slow outbound network calls to LLM services unless explicitly mocked.
    """
    monkeypatch.setenv("GEMINI_API_KEY", "")
    with patch("backend.radar.triage_service.get_gemini_client", return_value=None), \
         patch("backend.radar.scribe_service.get_gemini_client", return_value=None):
        yield


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
