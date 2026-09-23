"""Aura Mail AI - Multi-Account Routing, Alias Resolution & Security Tests.

Covers multi-mailbox merge, alias deduplication, historical account exclusion,
truth-in-error guarantees (no fake success / no sample fallback on failure),
and repository secret scanning.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path

from backend.config import BASE_DIR, load_settings
from backend.models import EmailMessage
from backend.provider_manager import ProviderManager, provider_manager
from backend.security import scan_repository_for_secrets

def test_repository_secrets_sanitized():
    """Verifies that no plaintext API keys or credentials exist anywhere in tracked repository files."""
    findings = scan_repository_for_secrets(BASE_DIR)
    assert findings == [], f"Found potential secrets in repository files: {findings}"

def test_alias_deduplication_and_historical_exclusion():
    """Verifies that aliases are not fetched twice and historical accounts are excluded."""
    pm = ProviderManager()
    
    mock_settings = {
        "demo_mode": False,
        "user_profile": {
            "historical_email_accounts": ["bkinlaw@dxc.com", "brian.kinlaw@cdw.com", "briankinlaw@revealwhy.com"]
        },
        "configured_accounts": [
            {
                "account_id": "kinlawb@outlook.com",
                "email": "kinlawb@outlook.com",
                "provider": "MICROSOFT_GRAPH",
                "enabled": True,
                "is_primary": True,
                "is_alias": False
            },
            {
                "account_id": "test.alias@outlook.com",
                "email": "test.alias@outlook.com",
                "provider": "MICROSOFT_GRAPH",
                "enabled": True,
                "is_primary": False,
                "is_alias": True,
                "alias_of": "kinlawb@outlook.com"
            },
            {
                "account_id": "bkinlaw@dxc.com",
                "email": "bkinlaw@dxc.com",
                "provider": "MICROSOFT_GRAPH",
                "enabled": True
            }
        ]
    }

    mock_msg = EmailMessage(
        id="MICROSOFT_GRAPH::kinlawb@outlook.com::msg_100",
        subject="Primary Reachout",
        sender_name="Recruiter",
        sender_email="rec@company.com",
        received_at="2026-09-10T12:00:00Z",
        preview="Preview",
        body_text="Body"
    )

    with patch("backend.provider_manager.load_settings", return_value=mock_settings):
        with patch("backend.provider_manager.save_settings"):
            with patch.object(pm.graph_provider, "fetch_inbox_messages", return_value=([mock_msg], None)) as mock_fetch:
                messages, stats = pm.sync_unified_inbox()
                
                # Should call fetch_inbox_messages EXACTLY ONCE for kinlawb@outlook.com
                # (skipping the alias test.alias@outlook.com and skipping historical bkinlaw@dxc.com)
                assert mock_fetch.call_count == 1
                assert mock_fetch.call_args[0][0] == "kinlawb@outlook.com"
                assert len(messages) == 1
                assert stats["accounts_synced"] == 1
                assert stats["skipped_accounts"] == [
                    {"account_id": "test.alias@outlook.com", "reason": "alias", "alias_of": "kinlawb@outlook.com"},
                    {"account_id": "bkinlaw@dxc.com", "reason": "historical"},
                ]

def test_no_sample_emails_on_live_sync_failure():
    """Verifies that live sync failures report truthful errors and NEVER inject mock/sample reachouts."""
    pm = ProviderManager()
    
    mock_settings = {
        "demo_mode": False,
        "user_profile": {"historical_email_accounts": []},
        "configured_accounts": [
            {
                "account_id": "kinlawb@outlook.com",
                "email": "kinlawb@outlook.com",
                "provider": "MICROSOFT_GRAPH",
                "enabled": True
            }
        ]
    }

    with patch("backend.provider_manager.load_settings", return_value=mock_settings):
        with patch("backend.provider_manager.save_settings"):
            with patch.object(pm.graph_provider, "fetch_inbox_messages", return_value=([], "Microsoft Graph API Timeout (504)")):
                messages, stats = pm.sync_unified_inbox()
                
                # Must return empty messages and record failure
                assert messages == []
                assert stats["accounts_failed"] == 1
                assert "Timeout" in stats["errors"][0]["error"]
                # Absolutely no demo/sample emails substituted
                for m in messages:
                    assert "[DEMO]" not in m.subject

def test_rate_limit_429_returns_retryable():
    """Verifies that HTTP 429 responses return retryable=True with safe diagnostic message."""
    mock_res = MagicMock()
    mock_res.status_code = 429
    mock_res.headers = {"Retry-After": "15"}

    with patch("backend.providers.graph.requests.get", return_value=mock_res):
        graph = pm = provider_manager.graph_provider
        with patch.object(graph, "get_access_token", return_value="mock_token"):
            res = graph.validate_connection("kinlawb@outlook.com")
            assert res.success is False
            assert res.error_code == "THROTTLED_429"
            assert res.retryable is True
            assert "15s" in res.safe_message

def test_failed_move_operation_returns_failure():
    """Verifies that failed move operations return success=False and do not report false positive."""
    mock_res = MagicMock()
    mock_res.status_code = 404
    mock_res.text = "Folder not found"

    with patch("backend.providers.graph.requests.post", return_value=mock_res):
        graph = provider_manager.graph_provider
        with patch.object(graph, "get_access_token", return_value="mock_token"):
            res = graph.move_message("kinlawb@outlook.com", "MICROSOFT_GRAPH::kinlawb@outlook.com::msg_99", "non_existent_folder")
            assert res.success is False
            assert res.error_code == "HTTP_404"


def test_save_draft_primary_account_token_resolves_to_composite_owner():
    """Verifies that save-draft resolves owner from composite ID when account_id is 'primary' or omitted."""
    from fastapi.testclient import TestClient
    from backend.main import app, CACHED_EMAILS
    from backend.auth import get_local_session_token
    from backend.providers.base import ProviderOperationResult

    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}

    msg_id = "MICROSOFT_GRAPH::kinlawb%40outlook.com::msg_composite_test_1"
    test_msg = EmailMessage(
        id=msg_id,
        account_id="primary",
        subject="AI Leadership Opportunity",
        sender_name="Ibrahim S A K",
        sender_email="recruiter@example.com",
        body_text="Reachout regarding Solutions Architecture"
    )
    CACHED_EMAILS[msg_id] = test_msg

    with patch("backend.main.provider_manager.save_draft_reply") as mock_save:
        mock_save.return_value = ProviderOperationResult(
            success=True,
            provider="MICROSOFT_GRAPH",
            account_id="kinlawb@outlook.com",
            operation="CREATE_DRAFT",
            safe_message="Draft staged successfully",
            remote_object_id="draft_cloud_composite_1"
        )
        res = client.post(
            f"/api/emails/{msg_id}/save-draft",
            headers=headers,
            json={"reply_body": "Thank you for reaching out."}
        )
        assert res.status_code == 200
        data = res.json()
        assert data["success"] is True
        # Verify provider_manager was invoked with the resolved owner account, not literal 'primary'
        mock_save.assert_called_once()
        assert mock_save.call_args.kwargs["account_id"] == "kinlawb@outlook.com"


def test_save_draft_account_mismatch_fails_closed():
    """Verifies that an explicit mismatch between requested account and message owner fails closed with 403."""
    from fastapi.testclient import TestClient
    from backend.main import app, CACHED_EMAILS
    from backend.auth import get_local_session_token

    client = TestClient(app)
    headers = {"X-Aura-Session-Token": get_local_session_token()}

    msg_id = "MICROSOFT_GRAPH::kinlawb%40outlook.com::msg_composite_test_2"
    test_msg = EmailMessage(
        id=msg_id,
        account_id="kinlawb@outlook.com",
        subject="Architecture Opportunity",
        sender_name="Recruiter",
        sender_email="rec@example.com",
        body_text="Reachout"
    )
    CACHED_EMAILS[msg_id] = test_msg

    # Request with a different active account
    res = client.post(
        f"/api/emails/{msg_id}/save-draft",
        headers=headers,
        json={
            "reply_body": "Thank you for reaching out.",
            "account_id": "brian@mavencode.com"
        }
    )
    assert res.status_code == 403
    assert "Account context mismatch" in res.json()["detail"]
