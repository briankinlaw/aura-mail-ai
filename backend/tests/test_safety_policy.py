"""
Unit Tests for Mail Safety Policy Model & Trust Boundaries (Phase 1 Corrective).
Verifies fail-closed mode resolution, explicit action taxonomy, fail-closed unknown
action denial, execution context matrix, and invariant enforcement.
"""

import pytest
from typing import Optional, Dict, Any, List
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


# ==============================================================================
# PHASE 3 — ENFORCEMENT AT PRIVILEGED BACKEND SEND BOUNDARY
# ==============================================================================

from unittest.mock import MagicMock
from backend.auth import get_local_session_token
from backend.models import EmailMessage
from backend.main import CACHED_EMAILS
from backend.provider_manager import provider_manager
from backend.providers.graph import MicrosoftGraphProvider
from backend.providers.gmail import GmailProvider
from backend.providers.imap import ImapProvider
from backend.providers.demo import DemoProvider
from backend.providers.base import ProviderOperationResult
from backend.daemon import run_daemon_cycle


def _setup_test_cached_email(email_id: str = "phase3_test_email_01", provider_msg_id: Optional[str] = None) -> EmailMessage:
    msg = EmailMessage(
        id=provider_msg_id or email_id,
        account_id="kinlawb@outlook.com",
        sender_name="Recruiter Sarah",
        sender_email="sarah@enterprise.com",
        subject="Executive Cloud Architect Opportunity",
        body_text="Hi Brian, please let us know your availability.",
        received_at="2026-09-13 14:00",
        preview="Hi Brian...",
        folder="Inbox"
    )
    CACHED_EMAILS[email_id] = msg
    return msg


def test_draft_only_dashboard_send_blocked():
    """
    EXPLICIT REQUIREMENT: DRAFT_ONLY + dashboard send -> blocked
    Under DRAFT_ONLY policy, even an authenticated dashboard user cannot transmit email.
    The backend endpoint fails closed with HTTP 403 SEND_FORBIDDEN.
    """
    _setup_test_cached_email("draft_only_dash_msg")
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        # 1. API endpoint boundary
        res = client.post(
            "/api/emails/draft_only_dash_msg/send-reply",
            json={"reply_body": "Thank you for reaching out."},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": "https://localhost:8000"
            }
        )
        assert res.status_code == 403
        data = res.json()
        assert data["detail"]["error_code"] == "SEND_FORBIDDEN"
        assert "DRAFT_ONLY" in data["detail"]["safety_mode"]

        # 2. ProviderManager boundary
        pm_res = provider_manager.send_reply(
            message_id="draft_only_dash_msg",
            to_email="sarah@enterprise.com",
            subject="Re: Opportunity",
            reply_body="Thank you",
            context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert pm_res.success is False
        assert pm_res.error_code == "SEND_FORBIDDEN"
        assert "DRAFT_ONLY" in pm_res.safe_message


def test_draft_only_direct_api_blocked():
    """
    EXPLICIT REQUIREMENT: DRAFT_ONLY + direct API -> blocked
    Direct unauthenticated API calls are blocked at auth boundary (401),
    and direct programmatic API context calls fail closed with SEND_FORBIDDEN.
    """
    _setup_test_cached_email("draft_only_direct_msg")

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.DRAFT_ONLY):
        # 1. Direct unauthenticated HTTP API call
        unauth_client = TestClient(app)
        res = unauth_client.post(
            "/api/emails/draft_only_direct_msg/send-reply",
            json={"reply_body": "Direct API send attempt"}
        )
        assert res.status_code == 401

        # 2. Direct programmatic send_reply with UNAUTHENTICATED_API context
        pm_res = provider_manager.send_reply(
            message_id="draft_only_direct_msg",
            to_email="sarah@enterprise.com",
            subject="Re: Opportunity",
            reply_body="Direct API send attempt",
            context=ExecutionContext.UNAUTHENTICATED_API,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert pm_res.success is False
        assert pm_res.error_code == "SEND_FORBIDDEN"


def test_manual_send_only_unauthorized_api_blocked():
    """
    EXPLICIT REQUIREMENT: MANUAL_SEND_ONLY + unauthorized API -> blocked
    Under MANUAL_SEND_ONLY, unauthenticated requests or calls with UNAUTHENTICATED_API context
    must strictly fail closed.
    """
    _setup_test_cached_email("manual_unauth_msg")

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        # 1. Unauthenticated HTTP call
        unauth_client = TestClient(app)
        res = unauth_client.post(
            "/api/emails/manual_unauth_msg/send-reply",
            json={"reply_body": "Unauthorized send"}
        )
        assert res.status_code == 401

        # 2. Programmatic UNAUTHENTICATED_API context call
        pm_res = provider_manager.send_reply(
            message_id="manual_unauth_msg",
            to_email="sarah@enterprise.com",
            subject="Re: Opportunity",
            reply_body="Unauthorized send",
            context=ExecutionContext.UNAUTHENTICATED_API,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert pm_res.success is False
        assert pm_res.error_code == "SEND_FORBIDDEN"


def test_manual_send_only_background_context_blocked():
    """
    EXPLICIT REQUIREMENT: MANUAL_SEND_ONLY + background context -> blocked
    PERMANENT SAFETY INVARIANT: Background execution can NEVER satisfy transmission authorization.
    All background contexts (DAEMON, BACKGROUND_RADAR, SCHEDULED_JOB, AI_AGENT, UNAUTHENTICATED_API)
    are strictly denied even when policy mode is MANUAL_SEND_ONLY.
    """
    _setup_test_cached_email("manual_bg_msg")

    for bg_context in BACKGROUND_CONTEXTS:
        pm_res = provider_manager.send_reply(
            message_id="manual_bg_msg",
            to_email="sarah@enterprise.com",
            subject="Re: Opportunity",
            reply_body="Background send attempt",
            context=bg_context,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert pm_res.success is False
        assert pm_res.error_code == "SEND_FORBIDDEN"
        assert "BACKGROUND EXECUTION -> SEND FORBIDDEN" in pm_res.safe_message or "prohibited" in pm_res.safe_message


def test_manual_send_only_legitimate_interactive_authorization_permitted():
    """
    EXPLICIT REQUIREMENT: MANUAL_SEND_ONLY + legitimate interactive authorization -> permitted
    When policy is MANUAL_SEND_ONLY and explicit interactive human authorization is provided
    (DASHBOARD_INTERACTIVE_USER with valid session token or OUTLOOK_INTERACTIVE_USER),
    transmission is authorized and dispatched to provider.
    """
    email_id = "interactive_perm_msg"
    provider_msg_id = "DEMO::demo%40auramail.local::interactive_perm_msg"
    _setup_test_cached_email(email_id, provider_msg_id=provider_msg_id)
    token = get_local_session_token()

    with patch("backend.safety_policy.get_active_safety_mode", return_value=MailSafetyMode.MANUAL_SEND_ONLY):
        with patch("backend.provider_manager.ProviderManager.is_demo_mode", return_value=True):
            # 1. Authenticated Dashboard interactive send
            res = client.post(
                f"/api/emails/{email_id}/send-reply",
                json={"reply_body": "Interactive approved reply.", "attach_resume": False},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://localhost:8000"
                }
            )
            assert res.status_code == 200
            data = res.json()
            assert data["success"] is True
            assert data["operation"] == "SEND_REPLY"

            # 2. Direct ProviderManager call with DASHBOARD_INTERACTIVE_USER
            pm_res1 = provider_manager.send_reply(
                message_id=provider_msg_id,
                to_email="sarah@enterprise.com",
                subject="Re: Opportunity",
                reply_body="Approved reply",
                context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
                safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
            )
            assert pm_res1.success is True

            # 3. Direct ProviderManager call with OUTLOOK_INTERACTIVE_USER
            pm_res2 = provider_manager.send_reply(
                message_id=provider_msg_id,
                to_email="sarah@enterprise.com",
                subject="Re: Opportunity",
                reply_body="Approved reply",
                context=ExecutionContext.OUTLOOK_INTERACTIVE_USER,
                safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
            )
            assert pm_res2.success is True


def test_daemon_in_draft_only_cannot_send():
    """
    EXPLICIT REQUIREMENT: daemon in DRAFT_ONLY -> cannot send
    The daemon must remain permanently draft-only. Any attempt by daemon to transmit fails closed.
    """
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

    # Programmatic check: direct send_reply from DAEMON context is rejected
    pm_res = provider_manager.send_reply(
        message_id="daemon_draft_only_01",
        to_email="dave@talent.com",
        subject="Re: Role",
        reply_body="Reply",
        context=ExecutionContext.DAEMON,
        safety_mode=MailSafetyMode.DRAFT_ONLY
    )
    assert pm_res.success is False
    assert pm_res.error_code == "SEND_FORBIDDEN"


def test_daemon_in_manual_send_only_cannot_send():
    """
    EXPLICIT REQUIREMENT: daemon in MANUAL_SEND_ONLY -> cannot send
    CRITICAL INVARIANT: Even when user configures MANUAL_SEND_ONLY, the autonomous background
    daemon MUST REMAIN PERMANENTLY DRAFT-ONLY. Background execution can NEVER send.
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

    # Programmatic check: direct send_reply from DAEMON context is rejected under MANUAL_SEND_ONLY
    pm_res = provider_manager.send_reply(
        message_id="daemon_manual_mode_01",
        to_email="dave@talent.com",
        subject="Re: Role",
        reply_body="Reply",
        context=ExecutionContext.DAEMON,
        safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
    )
    assert pm_res.success is False
    assert pm_res.error_code == "SEND_FORBIDDEN"
    assert "BACKGROUND EXECUTION -> SEND FORBIDDEN" in pm_res.safe_message


def test_malformed_mode_enforces_draft_only_behavior():
    """
    EXPLICIT REQUIREMENT: malformed mode -> DRAFT_ONLY behavior
    Any missing, malformed, unknown, or corrupted mode fails closed to DRAFT_ONLY,
    blocking transmission across API and providers.
    """
    malformed_modes = ["AUTONOMOUS", "FULL_AUTO", "SEND_ALL", "INVALID_MODE", "", None, 999, False, {}]
    _setup_test_cached_email("malformed_mode_msg")
    token = get_local_session_token()

    for bad_mode in malformed_modes:
        resolved = resolve_safety_mode(bad_mode)
        assert resolved == MailSafetyMode.DRAFT_ONLY

        with patch("backend.safety_policy.get_active_safety_mode", return_value=resolved):
            res = client.post(
                "/api/emails/malformed_mode_msg/send-reply",
                json={"reply_body": "Attempt under malformed mode"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://localhost:8000"
                }
            )
            assert res.status_code == 403
            assert res.json()["detail"]["error_code"] == "SEND_FORBIDDEN"


def test_graph_cannot_bypass():
    """
    EXPLICIT REQUIREMENT: Graph cannot bypass
    Direct invocation of MicrosoftGraphProvider.send_reply without interactive human context
    or in DRAFT_ONLY mode is blocked by the BaseEmailProvider send boundary and never
    executes Graph transmission logic.
    """
    graph = MicrosoftGraphProvider(client_id="mock-id")

    with patch.object(graph, "_execute_send_reply") as mock_exec:
        # 1. Direct call without context (defaults to UNAUTHENTICATED_API)
        res1 = graph.send_reply(
            account_id="kinlawb@outlook.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res1.success is False
        assert res1.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 2. Direct call from DAEMON context
        res2 = graph.send_reply(
            account_id="kinlawb@outlook.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DAEMON,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert res2.success is False
        assert res2.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 3. Direct call under DRAFT_ONLY
        res3 = graph.send_reply(
            account_id="kinlawb@outlook.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert res3.success is False
        assert res3.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called


def test_gmail_cannot_bypass():
    """
    EXPLICIT REQUIREMENT: Gmail cannot bypass
    Direct invocation of GmailProvider.send_reply without interactive human context
    or in DRAFT_ONLY mode is blocked by BaseEmailProvider and never executes Gmail transmission.
    """
    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")

    with patch.object(gmail, "_execute_send_reply") as mock_exec:
        # 1. Direct call without context
        res1 = gmail.send_reply(
            account_id="briankkinlaw@gmail.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res1.success is False
        assert res1.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 2. Direct call from DAEMON context under MANUAL_SEND_ONLY
        res2 = gmail.send_reply(
            account_id="briankkinlaw@gmail.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DAEMON,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert res2.success is False
        assert res2.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 3. Direct call under DRAFT_ONLY
        res3 = gmail.send_reply(
            account_id="briankkinlaw@gmail.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert res3.success is False
        assert res3.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called


def test_imap_cannot_bypass():
    """
    EXPLICIT REQUIREMENT: IMAP cannot bypass
    Direct invocation of ImapProvider.send_reply without interactive human context
    or in DRAFT_ONLY mode is blocked by BaseEmailProvider and never executes SMTP transmission.
    """
    imap = ImapProvider()

    with patch.object(imap, "_execute_send_reply") as mock_exec:
        # 1. Direct call without context
        res1 = imap.send_reply(
            account_id="cbkinlaw@satx.rr.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res1.success is False
        assert res1.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 2. Direct call from DAEMON context under MANUAL_SEND_ONLY
        res2 = imap.send_reply(
            account_id="cbkinlaw@satx.rr.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DAEMON,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert res2.success is False
        assert res2.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 3. Direct call under DRAFT_ONLY
        res3 = imap.send_reply(
            account_id="cbkinlaw@satx.rr.com",
            message_id="msg_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DASHBOARD_INTERACTIVE_USER,
            safety_mode=MailSafetyMode.DRAFT_ONLY
        )
        assert res3.success is False
        assert res3.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called


def test_demo_provider_cannot_bypass():
    """
    EXPLICIT REQUIREMENT: Demo Provider cannot bypass
    Direct invocation of DemoProvider.send_reply without interactive context
    or in DRAFT_ONLY mode is blocked by BaseEmailProvider.
    """
    demo = DemoProvider()

    with patch.object(demo, "_execute_send_reply") as mock_exec:
        # 1. Direct call without context
        res1 = demo.send_reply(
            account_id="demo@auramail.local",
            message_id="demo_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body"
        )
        assert res1.success is False
        assert res1.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called

        # 2. Direct call from DAEMON context
        res2 = demo.send_reply(
            account_id="demo@auramail.local",
            message_id="demo_01",
            to_email="rec@example.com",
            subject="Subj",
            reply_body="Body",
            context=ExecutionContext.DAEMON,
            safety_mode=MailSafetyMode.MANUAL_SEND_ONLY
        )
        assert res2.success is False
        assert res2.error_code == "SEND_FORBIDDEN"
        assert not mock_exec.called
