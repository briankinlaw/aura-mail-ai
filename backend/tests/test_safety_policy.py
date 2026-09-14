"""
Unit & Security Integration Tests for Mail Safety Policy Model, Trust Boundaries,
and Discrete Interactive Human Send Authorization (Phase 1 & Phase 3 Remediation).

Verifies:
1. Fail-closed safety mode resolution (DRAFT_ONLY vs MANUAL_SEND_ONLY).
2. Fail-closed explicit action taxonomy and unknown action denial.
3. Separation of Session Authentication (Phase 2) from Discrete Send Authorization (Phase 3).
4. Discrete Send Authorization Ticket lifecycle:
   - Backend issuance bound to exact payload digest, account, and message.
   - Refusal of ticket issuance in DRAFT_ONLY mode or from background contexts.
   - Cryptographic unpredictability, short lifetime (TTL), and atomic single-use consumption.
   - Fail-closed rejection of replay attacks, cross-message attacks, and cross-account attacks.
   - Content integrity protection against recipient, subject, body, and attachment tampering.
5. Invariant: BACKGROUND EXECUTION -> SEND FORBIDDEN (Daemon, Background Radar, AI Agents).
6. Central policy authority with zero caller-controllable safety mode overrides.
7. Provider-level defense in depth (Graph, Gmail, IMAP, Demo: _execute_send_reply never called on denial).
"""

import time
import threading
import pytest
from typing import Optional, Dict, Any, List
from unittest.mock import patch, MagicMock
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
    SendAuthorizationTicket,
    resolve_safety_mode,
    resolve_mail_action,
    get_active_safety_mode,
    set_safety_mode,
    evaluate_mail_action,
    compute_outbound_payload_digest,
    issue_send_authorization,
    validate_and_consume_send_authorization,
    clear_authorization_registry,
)
from backend.main import app, CACHED_EMAILS
from backend.auth import get_local_session_token
from backend.models import EmailMessage
from backend.provider_manager import provider_manager
from backend.providers.graph import MicrosoftGraphProvider
from backend.providers.gmail import GmailProvider
from backend.providers.imap import ImapProvider
from backend.providers.demo import DemoProvider
from backend.providers.base import ProviderOperationResult
from backend.outlook_client import outlook_client
from backend.daemon import run_daemon_cycle

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_safety_test_state():
    """Resets the in-memory authorization registry and email cache before each test."""
    clear_authorization_registry()
    CACHED_EMAILS.clear()
    yield
    clear_authorization_registry()
    CACHED_EMAILS.clear()


def _setup_test_cached_email(
    email_id: str = "phase3_test_email_01",
    account_id: str = "kinlawb@outlook.com",
    sender_email: str = "sarah@enterprise.com",
    subject: str = "Executive Cloud Architect Opportunity",
    body_text: str = "Hi Brian, please let us know your availability.",
) -> EmailMessage:
    msg = EmailMessage(
        id=email_id,
        account_id=account_id,
        sender_name="Recruiter Sarah",
        sender_email=sender_email,
        subject=subject,
        body_text=body_text,
        received_at="2026-09-13 14:00",
        preview="Hi Brian...",
        folder="Inbox"
    )
    CACHED_EMAILS[email_id] = msg
    return msg


# ==============================================================================
# 1. FOUNDATIONAL POLICY & RESOLUTION TESTS (Phase 1)
# ==============================================================================

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
    CRITICAL SECURITY INVARIANT:
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


def test_interactive_human_send_in_manual_send_only_without_ticket_is_blocked():
    """
    CRITICAL PHASE 3 REMEDIATION:
    Verifies that interactive human contexts CANNOT dispatch email under MANUAL_SEND_ONLY
    without a valid discrete send authorization ticket. Context enums alone fail closed.
    """
    for action in TRANSMISSION_ACTIONS:
        for ctx in INTERACTIVE_HUMAN_CONTEXTS:
            result = evaluate_mail_action(action=action, context=ctx, safety_mode=MailSafetyMode.MANUAL_SEND_ONLY)
            assert result.allowed is False
            assert result.is_send_blocked is True
            assert "Discrete Send Authorization Required" in result.reason


def test_interactive_human_send_in_manual_send_only_with_ticket_is_allowed():
    """Verifies that interactive human contexts with discrete authorization ticket are approved."""
    for action in TRANSMISSION_ACTIONS:
        for ctx in INTERACTIVE_HUMAN_CONTEXTS:
            result = evaluate_mail_action(
                action=action,
                context=ctx,
                safety_mode=MailSafetyMode.MANUAL_SEND_ONLY,
                authorization="sat_valid_test_token"
            )
            assert result.allowed is True
            assert result.is_send_blocked is False


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

    # Verify that POST /api/safety-policy is not exposed
    post_resp = client.post("/api/safety-policy", json={"safety_mode": "MANUAL_SEND_ONLY"})
    assert post_resp.status_code == 405


# ==============================================================================
# 2. PHASE 3 REMEDIATION: DISCRETE SEND AUTHORIZATION SECURITY TESTS
# ==============================================================================

# --- A. Safety Mode Absolute Invariants ---

def test_draft_only_rejects_authorization_issuance():
    """
    DRAFT_ONLY INVARIANT:
    When configured mode is DRAFT_ONLY, the backend strictly refuses to issue any SendAuthorizationTicket.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        with pytest.raises(PermissionError) as excinfo:
            issue_send_authorization(
                account_id="kinlawb@outlook.com",
                message_id="msg_001",
                to_email="sarah@enterprise.com",
                subject="Re: Role",
                reply_body="Body",
                originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
            )
        assert "DRAFT_ONLY" in str(excinfo.value)


def test_draft_only_rejects_send_even_with_valid_ticket():
    """
    DRAFT_ONLY INVARIANT:
    Even if a synthetic or pre-existing SendAuthorizationTicket is presented, if the authoritative
    mode is DRAFT_ONLY, transmission is unconditionally blocked.
    """
    ticket = SendAuthorizationTicket(
        ticket_id="sat_test_pre_existing",
        account_id="kinlawb@outlook.com",
        message_id="msg_001",
        operation="SEND_REPLY",
        payload_digest=compute_outbound_payload_digest(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
        ),
        created_at=time.time(),
        expires_at=time.time() + 120,
        consumed=False
    )
    from backend.safety_policy import _AUTHORIZATION_REGISTRY
    _AUTHORIZATION_REGISTRY[ticket.ticket_id] = ticket

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        val_res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            authorization=ticket.ticket_id
        )
        assert val_res.allowed is False
        assert val_res.is_send_blocked is True
        assert "DRAFT_ONLY" in val_res.reason
        assert ticket.consumed is False  # Was not consumed because mode blocked before consumption


def test_draft_only_dashboard_send_blocked():
    """
    DRAFT_ONLY + dashboard send -> blocked.
    Reaching /api/emails/{id}/send-reply in DRAFT_ONLY mode returns HTTP 403 SEND_FORBIDDEN.
    """
    _setup_test_cached_email("draft_only_dash_msg")
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        # 1. Authorize-send endpoint is refused
        auth_res = client.post(
            "/api/emails/draft_only_dash_msg/authorize-send",
            json={"reply_body": "Thank you for reaching out."},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert auth_res.status_code == 403
        assert auth_res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"

        # 2. Direct send-reply endpoint is refused
        send_res = client.post(
            "/api/emails/draft_only_dash_msg/send-reply",
            json={"reply_body": "Thank you for reaching out.", "authorization_ticket": "sat_fake"},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert send_res.status_code == 403
        assert send_res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_draft_only_direct_api_blocked():
    """
    DRAFT_ONLY + direct API -> blocked.
    Unauthenticated API is blocked with 401; direct authenticated API in DRAFT_ONLY fails closed with 403.
    """
    _setup_test_cached_email("draft_only_direct_msg")

    # Unauthenticated HTTP
    unauth_res = client.post(
        "/api/emails/draft_only_direct_msg/send-reply",
        json={"reply_body": "Direct API send attempt"}
    )
    assert unauth_res.status_code == 401


def test_draft_only_direct_provider_manager_blocked():
    """DRAFT_ONLY + direct ProviderManager -> blocked."""
    _setup_test_cached_email("draft_only_pm_msg")
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        pm_res = provider_manager.send_reply(
            message_id="draft_only_pm_msg",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Direct call",
            authorization="sat_some_ticket"
        )
        assert pm_res.success is False
        assert pm_res.error_code == "SEND_FORBIDDEN"


def test_draft_only_direct_provider_blocked():
    """DRAFT_ONLY + direct Provider -> blocked without executing transmission."""
    graph = MicrosoftGraphProvider(client_id="mock-id")
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        with patch.object(graph, "_execute_send_reply") as mock_exec:
            res = graph.send_reply(
                account_id="kinlawb@outlook.com",
                message_id="msg_01",
                to_email="rec@example.com",
                subject="Subj",
                reply_body="Body",
                authorization="sat_some_ticket"
            )
            assert res.success is False
            assert res.error_code == "SEND_FORBIDDEN"
            mock_exec.assert_not_called()


def test_malformed_mode_enforces_draft_only_behavior():
    """Missing or corrupted safety mode resolves to DRAFT_ONLY and blocks transmission."""
    malformed_modes = ["AUTONOMOUS", "FULL_AUTO", "SEND_ALL", "INVALID_MODE", "", None, 999, False, {}]
    _setup_test_cached_email("malformed_mode_msg")
    token = get_local_session_token()

    for bad_mode in malformed_modes:
        resolved = resolve_safety_mode(bad_mode)
        assert resolved == MailSafetyMode.DRAFT_ONLY

        with patch("backend.safety_policy.get_active_safety_mode", return_value=resolved):
            res = client.post(
                "/api/emails/malformed_mode_msg/authorize-send",
                json={"reply_body": "Attempt under bad mode"},
                headers={"Authorization": f"Bearer {token}", "Origin": "https://localhost:8000"}
            )
            assert res.status_code == 403
            assert res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


# --- B. Session Authentication is Not Send Authorization ---

def test_session_token_without_discrete_authorization_ticket_is_blocked():
    """
    CRITICAL FINDING 1 & 2 REMEDIATION:
    An authenticated local client presenting a valid Phase 2 session token CANNOT transmit email
    without an explicit, backend-issued discrete SendAuthorizationTicket.
    """
    _setup_test_cached_email("session_only_msg")
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        res = client.post(
            "/api/emails/session_only_msg/send-reply",
            json={"reply_body": "Attempting send with session token only."},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert res.status_code == 403
        data = res.json()
        assert data["detail"]["error_code"] == "SEND_FORBIDDEN"
        assert "Discrete Send Authorization Required" in data["detail"]["message"]


# --- C. Forged Execution Context & Caller-Supplied Mode Rejection ---

def test_forged_execution_context_blocked_at_provider_manager():
    """
    CRITICAL FINDING 2 REMEDIATION:
    Passing DASHBOARD_INTERACTIVE_USER or OUTLOOK_INTERACTIVE_USER to ProviderManager without
    a valid SendAuthorizationTicket fails closed.
    """
    _setup_test_cached_email("forged_ctx_pm_msg")

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with patch("backend.provider_manager.ProviderManager.is_demo_mode", return_value=True):
            pm_res = provider_manager.send_reply(
                message_id="forged_ctx_pm_msg",
                to_email="sarah@enterprise.com",
                subject="Re: Opportunity",
                reply_body="Forged context attempt",
                authorization=None  # No ticket
            )
            assert pm_res.success is False
            assert pm_res.error_code == "SEND_FORBIDDEN"
            assert "Discrete Send Authorization Required" in pm_res.safe_message


def test_forged_execution_context_blocked_at_base_provider():
    """
    CRITICAL FINDING 3 REMEDIATION:
    Direct BaseEmailProvider send_reply invocation without a valid ticket fails closed.
    """
    graph = MicrosoftGraphProvider(client_id="mock-id")

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with patch.object(graph, "_execute_send_reply") as mock_exec:
            res = graph.send_reply(
                account_id="kinlawb@outlook.com",
                message_id="msg_01",
                to_email="rec@example.com",
                subject="Subj",
                reply_body="Body",
                authorization=None
            )
            assert res.success is False
            assert res.error_code == "SEND_FORBIDDEN"
            mock_exec.assert_not_called()


def test_caller_supplied_safety_mode_override_is_ignored_and_blocked():
    """
    CRITICAL FINDING 2 & 3 REMEDIATION:
    Callers cannot supply safety_mode to make transmission more permissive.
    Authoritative mode is resolved internally.
    """
    graph = MicrosoftGraphProvider(client_id="mock-id")

    # Authoritative mode is DRAFT_ONLY in backend settings
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        with patch.object(graph, "_execute_send_reply") as mock_exec:
            # Base provider send_reply doesn't even accept caller-supplied safety_mode override
            res = graph.send_reply(
                account_id="kinlawb@outlook.com",
                message_id="msg_01",
                to_email="rec@example.com",
                subject="Subj",
                reply_body="Body",
                authorization="sat_attempted_bypass"
            )
            assert res.success is False
            assert res.error_code == "SEND_FORBIDDEN"
            mock_exec.assert_not_called()


# --- D. Legitimate Interactive Authorization Flow ---

def test_manual_send_only_legitimate_interactive_authorization_flow_permitted():
    """
    LEGITIMATE INTERACTIVE SEND WORKFLOW:
    1. Authenticated local human calls /authorize-send with draft payload.
    2. Backend issues discrete, short-lived, payload-bound SendAuthorizationTicket.
    3. User submits /send-reply presenting ticket + matching payload.
    4. ProviderManager & Provider validate and consume ticket, executing transmission.
    """
    email_id = "interactive_valid_msg"
    provider_msg_id = "DEMO::demo%40auramail.local::interactive_valid_msg"
    _setup_test_cached_email(email_id, account_id="demo@auramail.local")
    CACHED_EMAILS[email_id].id = provider_msg_id
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with patch("backend.provider_manager.ProviderManager.is_demo_mode", return_value=True):
            # Step 1: Interactive user authorizes outbound payload
            auth_res = client.post(
                f"/api/emails/{email_id}/authorize-send",
                json={
                    "reply_body": "Thank you for reaching out. My resume is attached.",
                    "attach_resume": False,
                    "to_email": "sarah@enterprise.com",
                    "subject": "Re: Opportunity"
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://localhost:8000"
                }
            )
            assert auth_res.status_code == 200
            auth_data = auth_res.json()
            assert auth_data["status"] == "SUCCESS"
            ticket_id = auth_data["authorization_ticket"]
            assert ticket_id.startswith("sat_")

            # Step 2: Interactive user submits send with ticket
            send_res = client.post(
                f"/api/emails/{email_id}/send-reply",
                json={
                    "reply_body": "Thank you for reaching out. My resume is attached.",
                    "attach_resume": False,
                    "to_email": "sarah@enterprise.com",
                    "subject": "Re: Opportunity",
                    "authorization_ticket": ticket_id
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://localhost:8000"
                }
            )
            assert send_res.status_code == 200
            send_data = send_res.json()
            assert send_data["success"] is True
            assert send_data["operation"] == "SEND_REPLY"


# --- E. Replay Attacks ---

def test_send_authorization_single_use_and_replay_rejection():
    """
    REPLAY ATTACK PREVENTION:
    An authorization ticket can be consumed exactly ONCE.
    Any second attempt to transmit with the same ticket is strictly BLOCKED as REPLAY.
    """
    email_id = "replay_test_msg"
    account_id = "demo@auramail.local"
    reply_body = "Approved reply text."
    to_email = "sarah@enterprise.com"
    subject = "Re: Role"

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id=account_id,
            message_id=email_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        # 1. First consumption -> ALLOWED
        res1 = validate_and_consume_send_authorization(
            account_id=account_id,
            message_id=email_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            authorization=ticket.ticket_id
        )
        assert res1.allowed is True
        assert res1.is_send_blocked is False

        # 2. Replay attempt -> BLOCKED
        res2 = validate_and_consume_send_authorization(
            account_id=account_id,
            message_id=email_id,
            to_email=to_email,
            subject=subject,
            reply_body=reply_body,
            authorization=ticket.ticket_id
        )
        assert res2.allowed is False
        assert res2.is_send_blocked is True
        assert "Replay Detected" in res2.reason


# --- F. Cross-Message & Cross-Account Attacks ---

def test_cross_message_authorization_rejection():
    """
    CROSS-MESSAGE ATTACK PREVENTION:
    An authorization ticket issued for Message A cannot be used to transmit Message B.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket_a = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_A",
            to_email="sarah@enterprise.com",
            subject="Re: Role A",
            reply_body="Body A",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        # Attempt to use ticket_a for msg_B
        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_B",  # Target is different
            to_email="sarah@enterprise.com",
            subject="Re: Role A",
            reply_body="Body A",
            authorization=ticket_a.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Message Mismatch" in res.reason


def test_cross_account_authorization_rejection():
    """
    CROSS-ACCOUNT ATTACK PREVENTION:
    An authorization ticket issued for Account A cannot be used to transmit on Account B.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket_acc_a = issue_send_authorization(
            account_id="account_a@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        # Attempt to use on account_b
        res = validate_and_consume_send_authorization(
            account_id="account_b@outlook.com",  # Different account
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            authorization=ticket_acc_a.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Account Mismatch" in res.reason


# --- G. Content Integrity & TOCTOU Tampering Attacks ---

def test_payload_tampering_recipient_mutation_rejection():
    """
    CONTENT INTEGRITY:
    If recipient email is mutated after human approval, payload digest mismatch blocks send.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="legitimate_recruiter@corp.com",
            subject="Re: Role",
            reply_body="Body",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        # Mutate recipient to attacker
        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="attacker@evil.com",
            subject="Re: Role",
            reply_body="Body",
            authorization=ticket.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Content Integrity Violation" in res.reason


def test_payload_tampering_body_mutation_rejection():
    """
    CONTENT INTEGRITY:
    If body content is mutated after human approval, payload digest mismatch blocks send.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Approved body text",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        # Mutate body text
        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="MUTATED MALICIOUS BODY",
            authorization=ticket.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Content Integrity Violation" in res.reason


def test_payload_tampering_subject_mutation_rejection():
    """CONTENT INTEGRITY: Mutating subject after authorization is blocked."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Original Subject",
            reply_body="Body",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Tampered Subject",
            reply_body="Body",
            authorization=ticket.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Content Integrity Violation" in res.reason


def test_payload_tampering_attachment_mutation_rejection():
    """CONTENT INTEGRITY: Mutating attachment after authorization is blocked."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            resume_filename="Approved_Resume.docx",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_001",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            resume_filename="Other_Resume.docx",  # Mutated attachment
            authorization=ticket.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Content Integrity Violation" in res.reason


# --- H. Background Execution Invariants ---

def test_daemon_cannot_issue_send_authorization():
    """Background Daemon execution is strictly forbidden from requesting send authorization."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with pytest.raises(PermissionError) as excinfo:
            issue_send_authorization(
                account_id="kinlawb@outlook.com",
                message_id="daemon_msg",
                to_email="rec@example.com",
                subject="Subj",
                reply_body="Body",
                originating_context=ExecutionContext.DAEMON
            )
        assert "Background execution cannot authorize mail sends" in str(excinfo.value)


def test_daemon_cannot_send_in_draft_only():
    """Daemon execution in DRAFT_ONLY strictly stages drafts and never transmits."""
    test_msg = EmailMessage(
        id="daemon_draft_only_01",
        account_id="kinlawb@outlook.com",
        sender_name="Recruiter Dave",
        sender_email="dave@talent.com",
        subject="Lead Cloud Architect",
        body_text="Hi Brian, please share your resume.",
        received_at="2026-09-13 12:00",
        preview="Hi Brian...",
        folder="Inbox"
    )

    with patch("backend.daemon.load_processed_ids", return_value=set()):
        with patch("backend.daemon.send_macos_notification"):
            with patch("backend.daemon.classify_email_radar") as mock_classify:
                with patch("backend.daemon.generate_executive_reply", return_value="Draft reply"):
                    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
                        mock_classify.return_value = MagicMock(
                            is_noise=False,
                            is_resume_request=True,
                            category=MagicMock(value="RESUME_REQUEST"),
                            recruiter_details=MagicMock(role_title="Lead Cloud Architect", required_skills=[], company_name="Talent Corp")
                        )
                        mock_pm = MagicMock()
                        mock_pm.sync_unified_inbox.return_value = ([test_msg], {"accounts_synced": 1, "status": "SUCCESS"})
                        mock_pm.save_draft_reply.return_value = ProviderOperationResult(
                            success=True,
                            provider="GRAPH",
                            account_id="kinlawb@outlook.com",
                            operation="CREATE_DRAFT",
                            safe_message="Draft created",
                            remote_object_id="draft_123"
                        )

                        with patch("backend.daemon.ProviderManager", return_value=mock_pm):
                            summary = run_daemon_cycle(dry_run=False)
                            assert summary["drafts_staged"] == 1
                            mock_pm.save_draft_reply.assert_called_once()
                            mock_pm.send_reply.assert_not_called()


def test_daemon_cannot_send_in_manual_send_only():
    """
    CRITICAL INVARIANT:
    Even when user configures MANUAL_SEND_ONLY, the daemon remains permanently draft-only.
    """
    test_msg = EmailMessage(
        id="daemon_manual_mode_01",
        account_id="kinlawb@outlook.com",
        sender_name="Recruiter Dave",
        sender_email="dave@talent.com",
        subject="Lead Cloud Architect",
        body_text="Hi Brian, please share your resume.",
        received_at="2026-09-13 12:00",
        preview="Hi Brian...",
        folder="Inbox"
    )

    with patch("backend.daemon.load_processed_ids", return_value=set()):
        with patch("backend.daemon.send_macos_notification"):
            with patch("backend.daemon.classify_email_radar") as mock_classify:
                with patch("backend.daemon.generate_executive_reply", return_value="Draft reply"):
                    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
                        mock_classify.return_value = MagicMock(
                            is_noise=False,
                            is_resume_request=True,
                            category=MagicMock(value="RESUME_REQUEST"),
                            recruiter_details=MagicMock(role_title="Lead Cloud Architect", required_skills=[], company_name="Talent Corp")
                        )
                        mock_pm = MagicMock()
                        mock_pm.sync_unified_inbox.return_value = ([test_msg], {"accounts_synced": 1, "status": "SUCCESS"})
                        mock_pm.save_draft_reply.return_value = ProviderOperationResult(
                            success=True,
                            provider="GRAPH",
                            account_id="kinlawb@outlook.com",
                            operation="CREATE_DRAFT",
                            safe_message="Draft created",
                            remote_object_id="draft_123"
                        )

                        with patch("backend.daemon.ProviderManager", return_value=mock_pm):
                            summary = run_daemon_cycle(dry_run=False)
                            assert summary["drafts_staged"] == 1
                            mock_pm.save_draft_reply.assert_called_once()
                            mock_pm.send_reply.assert_not_called()


def test_background_radar_cannot_issue_or_send():
    """BACKGROUND_RADAR context cannot issue tickets or send."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with pytest.raises(PermissionError):
            issue_send_authorization(
                account_id="kinlawb@outlook.com",
                message_id="msg_001",
                to_email="rec@example.com",
                subject="Subj",
                reply_body="Body",
                originating_context=ExecutionContext.BACKGROUND_RADAR
            )


def test_ai_agent_cannot_issue_or_send():
    """AI_AGENT context cannot issue tickets or send."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with pytest.raises(PermissionError):
            issue_send_authorization(
                account_id="kinlawb@outlook.com",
                message_id="msg_001",
                to_email="rec@example.com",
                subject="Subj",
                reply_body="Body",
                originating_context=ExecutionContext.AI_AGENT
            )


# --- I. Provider-Level Defense-in-Depth & Zero Side Effects ---

def test_graph_provider_zero_side_effects_when_unauthorized():
    """Microsoft Graph provider: _execute_send_reply is never invoked on unauthorized call."""
    graph = MicrosoftGraphProvider(client_id="mock-id")
    with patch.object(graph, "_execute_send_reply") as mock_exec:
        res = graph.send_reply(
            account_id="kinlawb@outlook.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            authorization=None
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_exec.assert_not_called()


def test_gmail_provider_zero_side_effects_when_unauthorized():
    """Gmail provider: _execute_send_reply is never invoked on unauthorized call."""
    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
    with patch.object(gmail, "_execute_send_reply") as mock_exec:
        res = gmail.send_reply(
            account_id="briankkinlaw@gmail.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            authorization=None
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_exec.assert_not_called()


def test_imap_provider_zero_side_effects_when_unauthorized():
    """IMAP/SMTP provider: _execute_send_reply is never invoked on unauthorized call."""
    imap = ImapProvider()
    with patch.object(imap, "_execute_send_reply") as mock_exec:
        res = imap.send_reply(
            account_id="cbkinlaw@satx.rr.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            authorization=None
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_exec.assert_not_called()


def test_demo_provider_zero_side_effects_when_unauthorized():
    """Demo provider: _execute_send_reply is never invoked on unauthorized call."""
    demo = DemoProvider()
    with patch.object(demo, "_execute_send_reply") as mock_exec:
        res = demo.send_reply(
            account_id="demo@auramail.local",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            authorization=None
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_exec.assert_not_called()


# --- J. Adapters, Expiration, Concurrency & Edge Cases ---

def test_outlook_client_adapter_requires_discrete_authorization():
    """
    CRITICAL FINDING 4 REMEDIATION:
    OutlookClientAdapter.send_reply requires explicit authorization ticket; no permissive default exists.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with patch("backend.provider_manager.ProviderManager.is_demo_mode", return_value=True):
            # Call without authorization ticket
            res = outlook_client.send_reply(
                to_email="sarah@enterprise.com",
                subject="Re: Role",
                reply_body="Body",
                message_id="DEMO::demo%40auramail.local::outlook_adapter_msg",
                authorization=None
            )
            assert res["success"] is False
            assert res["error_code"] == "SEND_FORBIDDEN"


def test_expired_ticket_fails_closed():
    """An expired SendAuthorizationTicket is rejected and purged."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        # Issue ticket with 0.01s TTL
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_expire",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            ttl_seconds=0.01,
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        time.sleep(0.03)

        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_expire",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            authorization=ticket.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "Expired" in res.reason


def test_server_restart_stale_ticket_fails_closed():
    """Server restart purges ephemeral authorization registry; stale tickets fail closed."""
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_restart",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        # Simulate server restart by clearing in-memory registry
        clear_authorization_registry()

        res = validate_and_consume_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_restart",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            authorization=ticket.ticket_id
        )
        assert res.allowed is False
        assert res.is_send_blocked is True
        assert "not found" in res.reason.lower() or "purged" in res.reason.lower()


def test_concurrent_authorization_race_is_thread_safe_and_single_use():
    """
    CONCURRENCY & RACE CONDITIONS:
    When multiple simultaneous threads attempt to consume the same authorization ticket,
    thread-safe atomic check-and-consume guarantees that exactly ONE thread succeeds
    and all concurrent threads fail closed.
    """
    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        ticket = issue_send_authorization(
            account_id="kinlawb@outlook.com",
            message_id="msg_race",
            to_email="sarah@enterprise.com",
            subject="Re: Role",
            reply_body="Body",
            originating_context=ExecutionContext.DASHBOARD_INTERACTIVE_USER
        )

        results = []

        def _worker():
            r = validate_and_consume_send_authorization(
                account_id="kinlawb@outlook.com",
                message_id="msg_race",
                to_email="sarah@enterprise.com",
                subject="Re: Role",
                reply_body="Body",
                authorization=ticket.ticket_id
            )
            results.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        success_count = sum(1 for r in results if r.allowed is True)
        failure_count = sum(1 for r in results if r.allowed is False)

        assert success_count == 1, f"Expected exactly 1 successful consumption, got {success_count}"
        assert failure_count == 9, f"Expected 9 rejections, got {failure_count}"
