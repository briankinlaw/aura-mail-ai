"""
Unit Tests for Mail Safety Policy Model & Trust Boundaries (Phase 1).
Verifies fail-closed resolution, execution context matrix, and invariant enforcement.
"""

import pytest
from unittest.mock import patch

from backend.safety_policy import (
    MailSafetyMode,
    ExecutionContext,
    PolicyEvaluationResult,
    resolve_safety_mode,
    get_active_safety_mode,
    set_safety_mode,
    evaluate_mail_action,
    BACKGROUND_CONTEXTS,
    INTERACTIVE_HUMAN_CONTEXTS
)


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


def test_background_contexts_cannot_send_under_draft_only():
    """Verifies that all background contexts are blocked from sending under DRAFT_ONLY."""
    for ctx in BACKGROUND_CONTEXTS:
        result = evaluate_mail_action(
            action="SEND_REPLY",
            context=ctx,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert result.allowed is False
        assert result.is_send_blocked is True
        assert "SEND FORBIDDEN" in result.reason or "strictly prohibited" in result.reason


def test_background_contexts_cannot_override_policy_even_under_manual_send():
    """
    PERMANENT SAFETY INVARIANT:
    BACKGROUND EXECUTION -> SEND FORBIDDEN
    Verifies that even if the system safety mode is MANUAL_SEND_ONLY,
    background contexts (Daemon, Radar, Scheduled Jobs, AI agents) CAN NEVER transmit email.
    """
    for ctx in BACKGROUND_CONTEXTS:
        result = evaluate_mail_action(
            action="SEND_REPLY",
            context=ctx,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert result.allowed is False
        assert result.is_send_blocked is True
        assert "BACKGROUND EXECUTION -> SEND FORBIDDEN" in result.reason


def test_interactive_human_send_in_draft_only_is_blocked():
    """Verifies that interactive human contexts cannot dispatch email when policy is DRAFT_ONLY."""
    for ctx in INTERACTIVE_HUMAN_CONTEXTS:
        result = evaluate_mail_action(
            action="SEND_REPLY",
            context=ctx,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert result.allowed is False
        assert result.is_send_blocked is True
        assert "DRAFT_ONLY" in result.reason


def test_interactive_human_send_in_manual_send_only_is_permitted():
    """Verifies that explicit human interactive contexts may dispatch email under MANUAL_SEND_ONLY."""
    for ctx in INTERACTIVE_HUMAN_CONTEXTS:
        result = evaluate_mail_action(
            action="SEND_REPLY",
            context=ctx,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert result.allowed is True
        assert result.is_send_blocked is False
        assert "permitted" in result.reason.lower()


def test_non_send_operations_always_permitted():
    """Verifies that analysis, draft creation, and calendar brokering are always permitted across all contexts."""
    for action in ["CREATE_DRAFT", "TRIAGE", "GENERATE_DRAFT", "CALENDAR_AVAILABILITY", "ANALYZE_FIT"]:
        for ctx in ExecutionContext:
            result = evaluate_mail_action(
                action=action,
                context=ctx,
                safety_mode=MailSafetyMode.DRAFT_ONLY
            )
            assert result.allowed is True
            assert result.is_send_blocked is False


def test_trust_boundary_mutation_rejection():
    """
    TRUST BOUNDARY TEST:
    Verifies that autonomous/background code cannot modify Mail Safety Policy.
    Only interactive human contexts are authorized to change policy.
    """
    # Background contexts must raise PermissionError
    for ctx in BACKGROUND_CONTEXTS:
        with pytest.raises(PermissionError):
            set_safety_mode(MailSafetyMode.MANUAL_SEND_ONLY, human_actor_context=ctx)

    # Interactive human context succeeds
    with patch("backend.config.save_settings") as mock_save:
        updated = set_safety_mode(
            MailSafetyMode.MANUAL_SEND_ONLY,
            human_actor_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )
        assert updated == MailSafetyMode.MANUAL_SEND_ONLY
        assert mock_save.called
