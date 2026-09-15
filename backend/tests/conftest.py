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
    Test helper providing authorized AdministrativeRecoveryContext for test resets.
    Not exported or used in production runtime code.
    """
    from backend.canonical_grounding import (
        PROVENANCE_STORE,
        RecoveryStrategy,
        RecoveryExecutionContext,
        AdministrativeRecoveryContext,
    )
    from backend.auth import issue_administrative_recovery_token
    target_store = store or PROVENANCE_STORE
    # Ensure store meets recovery precondition (disabled or marker exists)
    if target_store.is_available() and not target_store.state_path.exists():
        target_store.disable_store("Test suite reset")
    token = issue_administrative_recovery_token(actor="test_suite_admin")
    ctx = AdministrativeRecoveryContext(
        actor="test_suite_admin",
        execution_context=RecoveryExecutionContext.LOCAL_ADMIN_MAINTENANCE,
        explicitly_confirmed=True,
        authorization_evidence=token,
    )
    target_store.recover_store(RecoveryStrategy.RESET_ALL_PROVENANCE, ctx)
