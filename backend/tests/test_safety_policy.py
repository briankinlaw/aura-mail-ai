"""
Unit Tests for Mail Safety Policy Model & Trust Boundaries (Phase 1 Corrective).
Verifies fail-closed mode resolution, explicit action taxonomy, fail-closed unknown
action denial, execution context matrix, and invariant enforcement.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from backend.safety_policy import (
    MailSafetyMode,
    ExecutionContext,
    MailAction,
    SAFE_STAGING_ACTIONS,
    TRANSMISSION_ACTIONS,
    BACKGROUND_CONTEXTS,
    INTERACTIVE_HUMAN_CONTEXTS,
    PolicyEvaluationResult,
    resolve_safety_mode,
    resolve_mail_action,
    get_active_safety_mode,
    set_safety_mode,
    evaluate_mail_action,
)
from backend.main import app

client = TestClient(app)


def test_default_mode_resolution():
    """Verifies that missing or null safety mode resolutions default to DRAFT_ONLY."""
    assert resolve_safety_mode(None) == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode("") == MailSafetyMode.DRAFT_ONLY


def test_valid_draft_only():
    """Verifies that explicit DRAFT_ONLY strings resolve to DRAFT_ONLY."""
    assert resolve_safety_mode("DRAFT_ONLY") == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode("draft_only") == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode("SAFE_REVIEW") == MailSafetyMode.DRAFT_ONLY


def test_valid_manual_send_only():
    """Verifies that explicit MANUAL_SEND_ONLY string resolves to MANUAL_SEND_ONLY."""
    assert resolve_safety_mode("MANUAL_SEND_ONLY") == MailSafetyMode.MANUAL_SEND_ONLY
    assert resolve_safety_mode("manual_send_only") == MailSafetyMode.MANUAL_SEND_ONLY


def test_missing_and_corrupted_mode_fails_closed():
    """Verifies fail-closed behavior for empty, non-string, or corrupted configuration."""
    assert resolve_safety_mode({}) == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode([]) == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode(123) == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode(False) == MailSafetyMode.DRAFT_ONLY


def test_unknown_mode_never_falls_forward():
    """
    CRITICAL SECURITY INVARIANT:
    Verifies that unrecognized modes (e.g. AUTONOMOUS, AUTO_SEND, UNSAFE)
    FAIL CLOSED to DRAFT_ONLY and never silently fall forward into MANUAL_SEND_ONLY.
    """
    assert resolve_safety_mode("AUTONOMOUS") == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode("FULL_AUTO") == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode("SEND_ALL") == MailSafetyMode.DRAFT_ONLY
    assert resolve_safety_mode("UNKNOWN_FUTURE_MODE") == MailSafetyMode.DRAFT_ONLY


def test_unknown_or_unclassified_action_fails_closed():
    """
    CRITICAL SECURITY INVARIANT (Finding 2 Correction):
    Verifies that unknown, unclassified, or unexpected action strings FAIL CLOSED
    and are denied by default across all contexts and modes.
    """
    unknown_actions = [
        "CUSTOM_UNKNOWN_ACTION",
        "EXECUTE_ARBITRARY_PAYLOAD",
        "UNKNOWN_OP",
        "DO_SOMETHING_MAGIC",
        "",
        "INVALID_VERB"
    ]
    for action in unknown_actions:
        assert resolve_mail_action(action) is None
        for ctx in ExecutionContext:
            for mode in [MailSafetyMode.DRAFT_ONLY, MailSafetyMode.MANUAL_SEND_ONLY]:
                result = evaluate_mail_action(action=action, context=ctx, safety_mode=mode)
                assert result.allowed is False
                assert "Fail-Closed" in result.reason or "denied by default" in result.reason


def test_all_transmission_actions_blocked_for_background_contexts_under_all_modes():
    """
    PERMANENT SAFETY INVARIANT:
    BACKGROUND EXECUTION -> SEND FORBIDDEN
    Verifies that every transmission operation is strictly blocked for all background
    contexts regardless of whether policy is DRAFT_ONLY or MANUAL_SEND_ONLY.
    """
    for action in TRANSMISSION_ACTIONS:
        for ctx in BACKGROUND_CONTEXTS:
            for mode in [MailSafetyMode.DRAFT_ONLY, MailSafetyMode.MANUAL_SEND_ONLY]:
                result = evaluate_mail_action(action=action, context=ctx, safety_mode=mode)
                assert result.allowed is False
                assert result.is_send_blocked is True
                assert "BACKGROUND EXECUTION -> SEND FORBIDDEN" in result.reason or "strictly prohibited" in result.reason


def test_interactive_human_send_in_draft_only_is_blocked():
    """Verifies that interactive human contexts cannot dispatch email when policy is DRAFT_ONLY."""
    for action in TRANSMISSION_ACTIONS:
        for ctx in INTERACTIVE_HUMAN_CONTEXTS:
            result = evaluate_mail_action(action=action, context=ctx, safety_mode=MailSafetyMode.DRAFT_ONLY)
            assert result.allowed is False
            assert result.is_send_blocked is True
            assert "DRAFT_ONLY" in result.reason


def test_interactive_human_send_in_manual_send_only_is_permitted():
    """Verifies that explicit human interactive contexts may dispatch email under MANUAL_SEND_ONLY."""
    for action in TRANSMISSION_ACTIONS:
        for ctx in INTERACTIVE_HUMAN_CONTEXTS:
            result = evaluate_mail_action(action=action, context=ctx, safety_mode=MailSafetyMode.MANUAL_SEND_ONLY)
            assert result.allowed is True
            assert result.is_send_blocked is False
            assert "permitted" in result.reason.lower()


def test_all_safe_staging_actions_permitted_across_all_contexts():
    """Verifies that all classified safe staging/analysis actions are permitted across all contexts."""
    for action in SAFE_STAGING_ACTIONS:
        for ctx in ExecutionContext:
            for mode in [MailSafetyMode.DRAFT_ONLY, MailSafetyMode.MANUAL_SEND_ONLY]:
                result = evaluate_mail_action(action=action, context=ctx, safety_mode=mode)
                assert result.allowed is True
                assert result.is_send_blocked is False


def test_trust_boundary_programmatic_mutation_rejection():
    """
    TRUST BOUNDARY TEST:
    Verifies that autonomous/background code cannot modify Mail Safety Policy.
    Only interactive human contexts are authorized to change policy in backend config.
    """
    for ctx in BACKGROUND_CONTEXTS:
        with pytest.raises(PermissionError):
            set_safety_mode(MailSafetyMode.MANUAL_SEND_ONLY, human_actor_context=ctx)

    with patch("backend.config.save_settings") as mock_save:
        updated = set_safety_mode(
            MailSafetyMode.MANUAL_SEND_ONLY,
            human_actor_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )
        assert updated == MailSafetyMode.MANUAL_SEND_ONLY
        assert mock_save.called


def test_read_only_safety_policy_api_endpoint():
    """Verifies read-only policy endpoint reports active status and invariants."""
    response = client.get("/api/safety-policy")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "SUCCESS"
    assert "active_mode" in data
    assert "permanent_invariants" in data

    # Verify that POST /api/safety-policy is not exposed without authenticated provenance
    post_resp = client.post("/api/safety-policy", json={"safety_mode": "MANUAL_SEND_ONLY"})
    assert post_resp.status_code == 405  # Method Not Allowed
