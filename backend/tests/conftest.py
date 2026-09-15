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
    from backend.offline_recovery import execute_offline_recovery_transaction
    target_store = store or PROVENANCE_STORE
    if target_store.is_available() and not target_store.state_path.exists():
        target_store.disable_store("Test suite reset")
    execute_offline_recovery_transaction(
        target_dir=target_store.storage_path.parent,
        interactive=False,
        is_test_harness=True,
        actor_override="test_suite_admin"
    )
    target_store._load()
