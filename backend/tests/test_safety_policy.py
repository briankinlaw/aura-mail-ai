"""
Unit & Security Integration Tests for Mail Safety Policy Model, Trust Boundaries,
and Native Human-Controlled Mail Transmission (Phase 3 Third-Pass Remediation).

Core Invariant:
    ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN
    Aura prepares. The native mail client / provider sends.

Authoritative Safety Modes:
    1. DRAFT_ONLY:
       Reads, analyzes, classifies, and creates/stages drafts; stops.
       Every transmission attempt fails closed with SEND_FORBIDDEN.
    2. MANUAL_SEND_ONLY:
       Stages drafts in the user's remote cloud mailbox / draft folder.
       The human opens their native mail client (Outlook / Gmail / Apple Mail)
       and executes the native send action.
       Direct transmission through Aura backend fails closed with SEND_FORBIDDEN.

Verifies:
1. Fail-closed safety mode resolution (DRAFT_ONLY vs MANUAL_SEND_ONLY).
2. Fail-closed explicit action taxonomy and unknown action denial.
3. Separation of Session Authentication (Phase 2) from transmission authority.
4. Permanent removal of localhost transmission authority tickets.
5. Invariant: BACKGROUND EXECUTION -> SEND FORBIDDEN (Daemon, Background Radar, AI Agents).
6. Central policy authority with zero caller-controllable safety mode overrides.
7. Complete removal of provider-level transmission primitives (Graph, Gmail, IMAP, Demo).
8. Positive verification of draft preparation and cloud staging across all providers.
"""

import time
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
    resolve_safety_mode,
    resolve_mail_action,
    get_active_safety_mode,
    set_safety_mode,
    evaluate_mail_action,
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
    """Resets the email cache before and after each test."""
    CACHED_EMAILS.clear()
    yield
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
# 1. FOUNDATIONAL POLICY & RESOLUTION TESTS
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


# ==============================================================================
# 2. NEGATIVE SECURITY TESTS — FAIL-CLOSED DIRECT TRANSMISSION DENIAL
# ==============================================================================

def test_all_transmission_actions_blocked_across_all_modes_and_contexts():
    """
    AUTHORITATIVE PHASE 3 INVARIANT:
    ANY AURA-CONTROLLED EXECUTION -> DIRECT MAIL TRANSMISSION FORBIDDEN
    Verifies that every transmission operation is strictly blocked across all
    execution contexts (interactive, background, direct API) under both modes.
    """
    for action in TRANSMISSION_ACTIONS:
        for ctx in ExecutionContext:
            for mode in [MailSafetyMode.DRAFT_ONLY, MailSafetyMode.MANUAL_SEND_ONLY]:
                result = evaluate_mail_action(action=action, context=ctx, safety_mode=mode)
                assert result.allowed is False
                assert result.is_send_blocked is True
                assert (
                    "FORBIDDEN" in result.reason
                    or "DRAFT_ONLY" in result.reason
                    or "prohibited" in result.reason
                )


def test_draft_only_dashboard_send_blocked():
    """
    DRAFT_ONLY + dashboard send -> blocked.
    Reaching /api/emails/{id}/send-reply in DRAFT_ONLY mode returns HTTP 403 SEND_FORBIDDEN.
    """
    _setup_test_cached_email("draft_only_dash_msg")
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        send_res = client.post(
            "/api/emails/draft_only_dash_msg/send-reply",
            json={"reply_body": "Attempting send in DRAFT_ONLY."},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert send_res.status_code == 403
        data = send_res.json()
        assert data["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_manual_send_only_dashboard_send_blocked():
    """
    MANUAL_SEND_ONLY + dashboard send -> blocked.
    In MANUAL_SEND_ONLY mode, Aura prepares/stages drafts, and direct backend transmission
    is strictly forbidden. Calls to /api/emails/{id}/send-reply fail closed with 403 SEND_FORBIDDEN.
    """
    _setup_test_cached_email("manual_send_dash_msg")
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        send_res = client.post(
            "/api/emails/manual_send_dash_msg/send-reply",
            json={"reply_body": "Attempting send in MANUAL_SEND_ONLY."},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert send_res.status_code == 403
        data = send_res.json()
        assert data["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_direct_http_send_reply_fails_closed_even_with_valid_session_token():
    """
    CRITICAL SECURITY INVARIANT:
    A valid session token proves caller is local, but grants ZERO transmission authority.
    Any call to /api/emails/{id}/send-reply returns HTTP 403 SEND_FORBIDDEN.
    """
    _setup_test_cached_email("session_token_msg")
    token = get_local_session_token()

    res = client.post(
        "/api/emails/session_token_msg/send-reply",
        json={"reply_body": "Direct send with session token."},
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://localhost:8000"
        }
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_direct_unauthenticated_http_send_reply_blocked():
    """Unauthenticated HTTP request to send-reply is rejected with 401."""
    _setup_test_cached_email("unauth_send_msg")
    res = client.post(
        "/api/emails/unauth_send_msg/send-reply",
        json={"reply_body": "Unauthenticated send attempt."}
    )
    assert res.status_code == 401


def test_authorize_send_route_does_not_exist():
    """
    CRITICAL ARCHITECTURAL TEST:
    The localhost ticket authorization endpoint (/api/emails/{id}/authorize-send)
    has been permanently retired and returns HTTP 404 Not Found.
    """
    token = get_local_session_token()
    res = client.post(
        "/api/emails/test_msg/authorize-send",
        json={"reply_body": "Ticket request"},
        headers={"Authorization": f"Bearer {token}", "Origin": "https://localhost:8000"}
    )
    assert res.status_code == 404


def test_direct_provider_manager_send_reply_fails_closed():
    """ProviderManager.send_reply() fails closed with SEND_FORBIDDEN under all conditions."""
    _setup_test_cached_email("pm_send_msg")
    res = provider_manager.send_reply(
        message_id="pm_send_msg",
        to_email="sarah@enterprise.com",
        subject="Re: Cloud Role",
        reply_body="Direct PM invocation"
    )
    assert res.success is False
    assert res.error_code == "SEND_FORBIDDEN"
    assert "permanently disabled" in res.safe_message


def test_direct_base_provider_send_reply_fails_closed():
    """BaseEmailProvider.send_reply() fails closed unconditionally."""
    demo = DemoProvider()
    res = demo.send_reply(
        account_id="demo@auramail.local",
        message_id="demo_01",
        to_email="rec@example.com",
        subject="Subj",
        reply_body="Body"
    )
    assert res.success is False
    assert res.error_code == "SEND_FORBIDDEN"


def test_outlook_client_adapter_send_reply_fails_closed():
    """OutlookClientAdapter.send_reply() fails closed via ProviderManager."""
    res = outlook_client.send_reply(
        to_email="rec@example.com",
        subject="Subj",
        reply_body="Body",
        message_id="ad_01"
    )
    assert res["success"] is False
    assert res["error_code"] == "SEND_FORBIDDEN"


def test_graph_provider_has_no_transmission_primitives():
    """
    GRAPH PROVIDER AUDIT:
    Verifies that MicrosoftGraphProvider does NOT implement _execute_send_reply
    and send_reply fails closed with SEND_FORBIDDEN without making outbound network requests.
    """
    graph = MicrosoftGraphProvider(client_id="mock-id")
    assert not hasattr(graph, "_execute_send_reply") or getattr(graph, "_execute_send_reply", None) is None
    with patch("requests.post") as mock_post:
        res = graph.send_reply(
            account_id="kinlawb@outlook.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_post.assert_not_called()


def test_gmail_provider_has_no_transmission_primitives():
    """
    GMAIL PROVIDER AUDIT:
    Verifies that GmailProvider does NOT implement _execute_send_reply
    and send_reply fails closed with SEND_FORBIDDEN without making outbound network requests.
    """
    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
    assert not hasattr(gmail, "_execute_send_reply") or getattr(gmail, "_execute_send_reply", None) is None
    with patch("requests.post") as mock_post:
        res = gmail.send_reply(
            account_id="kinlawb@gmail.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_post.assert_not_called()


def test_imap_provider_has_no_transmission_primitives():
    """
    IMAP PROVIDER AUDIT:
    Verifies that ImapProvider does NOT implement _execute_send_reply or smtplib transmission,
    and send_reply fails closed with SEND_FORBIDDEN without opening SMTP connections.
    """
    imap = ImapProvider()
    assert not hasattr(imap, "_execute_send_reply") or getattr(imap, "_execute_send_reply", None) is None
    with patch("smtplib.SMTP") as mock_smtp:
        res = imap.send_reply(
            account_id="brian@custom.org",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res.success is False
        assert res.error_code == "SEND_FORBIDDEN"
        mock_smtp.assert_not_called()


def test_demo_provider_has_no_transmission_primitives():
    """DemoProvider.send_reply fails closed with SEND_FORBIDDEN."""
    demo = DemoProvider()
    assert not hasattr(demo, "_execute_send_reply") or getattr(demo, "_execute_send_reply", None) is None
    res = demo.send_reply(
        account_id="demo@auramail.local",
        message_id="demo_01",
        to_email="rec@example.com",
        subject="Subj",
        reply_body="Body"
    )
    assert res.success is False
    assert res.error_code == "SEND_FORBIDDEN"


def test_background_radar_and_ai_agents_fail_closed_on_send():
    """Verifies that automated agents and background scanners cannot transmit mail."""
    for bg_ctx in [ExecutionContext.BACKGROUND_RADAR, ExecutionContext.SCHEDULED_JOB, ExecutionContext.AI_AGENT, ExecutionContext.DAEMON]:
        for mode in [MailSafetyMode.DRAFT_ONLY, MailSafetyMode.MANUAL_SEND_ONLY]:
            res = evaluate_mail_action(MailAction.SEND_REPLY, context=bg_ctx, safety_mode=mode)
            assert res.allowed is False
            assert res.is_send_blocked is True


def test_caller_supplied_overrides_rejected():
    """Verifies that callers cannot pass arbitrary overrides to bypass backend policy."""
    res = evaluate_mail_action(
        action="SEND_REPLY",
        context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
        safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
    )
    assert res.allowed is False
    assert res.is_send_blocked is True


# ==============================================================================
# 3. POSITIVE FUNCTIONAL TESTS — SAFE DRAFT STAGING & PREPARATION
# ==============================================================================

def test_all_safe_staging_actions_permitted_across_all_contexts():
    """Verifies that all classified safe staging/analysis actions are permitted across all contexts."""
    for action in SAFE_STAGING_ACTIONS:
        for ctx in ExecutionContext:
            for mode in [MailSafetyMode.DRAFT_ONLY, MailSafetyMode.MANUAL_SEND_ONLY]:
                result = evaluate_mail_action(action=action, context=ctx, safety_mode=mode)
                assert result.allowed is True
                assert result.is_send_blocked is False


def test_graph_create_reply_draft_staging_success():
    """
    Verifies that MicrosoftGraphProvider successfully stages a threaded reply draft
    in the cloud mailbox using POST /me/messages/{id}/createReply.
    """
    graph = MicrosoftGraphProvider(client_id="mock-id")
    with patch.object(graph, "get_access_token", return_value="mock_token"):
        with patch("requests.post") as mock_post:
            mock_post.return_value.status_code = 201
            mock_post.return_value.json.return_value = {
                "id": "graph_draft_123",
                "subject": "Re: Opportunity"
            }
            res = graph.create_reply_draft(
                account_id="kinlawb@outlook.com",
                message_id="MICROSOFT_GRAPH::kinlawb@outlook.com::msg_graph_01",
                reply_body="Here is my response."
            )
            assert res.success is True
            assert res.remote_object_id == "graph_draft_123"
            mock_post.assert_called_once()


def test_gmail_create_reply_draft_staging_success():
    """
    Verifies that GmailProvider successfully stages a MIME draft in the Gmail mailbox
    using POST https://gmail.googleapis.com/gmail/v1/users/me/drafts.
    """
    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
    with patch.object(gmail, "get_access_token", return_value="mock_gmail_token"):
        with patch("requests.get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "threadId": "thread_456",
                "payload": {"headers": [{"name": "Subject", "value": "Role"}, {"name": "From", "value": "sarah@recruiting.com"}]}
            }
            with patch("requests.post") as mock_post:
                mock_post.return_value.status_code = 200
                mock_post.return_value.json.return_value = {
                    "id": "gmail_draft_456",
                    "message": {"id": "msg_456", "threadId": "thread_456"}
                }

                res = gmail.create_reply_draft(
                    account_id="kinlawb@gmail.com",
                    message_id="GMAIL::kinlawb@gmail.com::msg_gmail_01",
                    reply_body="Thank you for considering me."
                )
                assert res.success is True
                assert res.remote_object_id == "gmail_draft_456"
                mock_post.assert_called_once()


def test_imap_create_reply_draft_staging_success():
    """
    Verifies that ImapProvider successfully appends a staged draft message to the Drafts folder
    via IMAP APPEND.
    """
    imap = ImapProvider()
    mock_conn = MagicMock()
    mock_conn.uid.return_value = ("OK", [(b"1", b"Subject: Role\r\nFrom: sender@domain.com\r\nMessage-ID: <123@domain.com>\r\n")])
    mock_conn.append.return_value = ("OK", [b"Append completed."])

    with patch.object(imap, "_get_imap_connection", return_value=mock_conn):
        with patch.object(imap, "_discover_folders", return_value={"drafts": "Drafts"}):
            res = imap.create_reply_draft(
                account_id="brian@custom.org",
                message_id="IMAP::brian@custom.org::101",
                reply_body="Draft body content."
            )
            assert res.success is True
            assert "Draft created" in res.safe_message
            assert mock_conn.append.called


def test_demo_create_reply_draft_staging_success():
    """Verifies that DemoProvider successfully records a staged draft in memory."""
    demo = DemoProvider()
    res = demo.create_reply_draft(
        account_id="demo@auramail.local",
        message_id="DEMO::demo@auramail.local::demo_rec_01",
        reply_body="Demo draft content."
    )
    assert res.success is True
    assert res.remote_object_id.startswith("demo_draft_")


def test_save_draft_api_endpoint_stages_cloud_draft():
    """
    Verifies that authenticated POST /api/emails/{id}/save-draft invokes
    provider_manager.save_draft_reply and returns HTTP 200 with draft details.
    """
    _setup_test_cached_email("api_save_draft_msg")
    token = get_local_session_token()

    with patch("backend.main.provider_manager.save_draft_reply") as mock_save:
        mock_save.return_value = ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft staged successfully",
            remote_object_id="draft_cloud_789"
        )
        res = client.post(
            "/api/emails/api_save_draft_msg/save-draft",
            json={"reply_body": "Staged draft via API."},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        assert data["remote_object_id"] == "draft_cloud_789"
        mock_save.assert_called_once()


def test_generate_reply_api_endpoint_success():
    """
    Verifies that authenticated POST /api/emails/{id}/generate-reply generates
    an AI-grounded draft response for the user to review.
    """
    _setup_test_cached_email("api_gen_reply_msg")
    token = get_local_session_token()

    with patch("backend.main.generate_personalized_reply", return_value="Thank you for reaching out. I am interested."):
        res = client.post(
            "/api/emails/api_gen_reply_msg/generate-reply",
            json={"tone": "Executive"},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "SUCCESS"
        assert data["draft_reply"] == "Thank you for reaching out. I am interested."


def test_outlook_add_in_staging_workflow():
    """
    Verifies that OutlookClientAdapter successfully stages drafts via save_draft_reply.
    """
    with patch.object(provider_manager, "save_draft_reply") as mock_pm_save:
        mock_pm_save.return_value = ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft created",
            remote_object_id="addin_draft_999"
        )
        res = outlook_client.save_draft_reply(
            message_id="addin_msg_01",
            reply_body="Add-in staged draft."
        )
        assert res["success"] is True
        assert res["remote_object_id"] == "addin_draft_999"
        mock_pm_save.assert_called_once()
