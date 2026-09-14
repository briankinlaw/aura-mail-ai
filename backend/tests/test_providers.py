"""Aura Mail AI - Automated Mock Tests for Cloud Email Providers.

Tests MicrosoftGraphProvider, GmailProvider, ImapProvider, and DemoProvider
with 100% mocked network calls and zero live network/credential dependencies.
"""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime

from backend.providers.base import (
    ProviderType,
    AccountIdentity,
    ProviderOperationResult,
    encode_composite_id,
    decode_composite_id
)
from backend.providers.demo import DemoProvider
from backend.providers.graph import MicrosoftGraphProvider
from backend.providers.gmail import GmailProvider
from backend.providers.imap import ImapProvider

# --- Composite ID Codec Tests ---

def test_composite_id_codec():
    comp_id = encode_composite_id("MICROSOFT_GRAPH", "kinlawb@outlook.com", "AAMkAGI2AAAB")
    assert "MICROSOFT_GRAPH::kinlawb%40outlook.com::AAMkAGI2AAAB" == comp_id
    
    provider, account_id, native_id = decode_composite_id(comp_id)
    assert provider == "MICROSOFT_GRAPH"
    assert account_id == "kinlawb@outlook.com"
    assert native_id == "AAMkAGI2AAAB"

def test_composite_id_backward_compatibility():
    # Legacy Graph prefix
    p, a, n = decode_composite_id("graph_12345")
    assert p == "MICROSOFT_GRAPH"
    assert n == "12345"

    # Legacy IMAP prefix
    p, a, n = decode_composite_id("imap_9988")
    assert p == "IMAP"
    assert n == "9988"

    # Legacy Demo prefix
    p, a, n = decode_composite_id("msg_rec_01")
    assert p == "DEMO"
    assert n == "msg_rec_01"

# --- Demo Provider Tests ---

def test_demo_provider_operations():
    demo = DemoProvider()
    val = demo.validate_connection("demo@auramail.local")
    assert val.success is True
    assert val.provider == "DEMO"

    msgs, err = demo.fetch_inbox_messages("demo@auramail.local")
    assert err is None
    assert len(msgs) > 0
    assert "[DEMO]" in msgs[0].subject

    draft_res = demo.create_reply_draft(
        account_id="demo@auramail.local",
        message_id=msgs[0].id,
        reply_body="Hi Sarah, thank you for reaching out.",
        resume_filename="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
    )
    assert draft_res.success is True
    assert "[DEMO]" in draft_res.safe_message

    move_res = demo.move_message("demo@auramail.local", msgs[1].id, "AI Cleaned - Noise")
    assert move_res.success is True

# --- Microsoft Graph Provider (Mocked) Tests ---

@patch("backend.providers.graph.requests.get")
def test_graph_validation_success(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "displayName": "Brian Kinlaw",
        "mail": "kinlawb@outlook.com",
        "userPrincipalName": "kinlawb@outlook.com"
    }

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch.object(graph, "get_access_token", return_value="mock_valid_token"):
        res = graph.validate_connection("kinlawb@outlook.com")
        assert res.success is True
        assert res.provider == "MICROSOFT_GRAPH"
        assert "Brian Kinlaw" in res.safe_message

@patch("backend.providers.graph.requests.get")
def test_graph_validation_expired_token(mock_get):
    mock_get.return_value.status_code = 401

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch.object(graph, "get_access_token", return_value="mock_expired_token"):
        res = graph.validate_connection("kinlawb@outlook.com")
        assert res.success is False
        assert res.error_code == "AUTH_EXPIRED"

@patch("backend.providers.graph.requests.get")
def test_graph_pagination(mock_get):
    # Page 1 returns 1 message with nextLink
    page1_response = MagicMock()
    page1_response.status_code = 200
    page1_response.json.return_value = {
        "value": [{
            "id": "graph_msg_01",
            "conversationId": "conv_01",
            "subject": "Role 1",
            "from": {"emailAddress": {"name": "Recruiter 1", "address": "rec1@talent.com"}},
            "receivedDateTime": "2026-09-10T10:00:00Z",
            "bodyPreview": "Preview 1",
            "body": {"content": "Body 1", "contentType": "text"}
        }],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages?$skiptoken=page2"
    }

    # Page 2 returns 1 message without nextLink
    page2_response = MagicMock()
    page2_response.status_code = 200
    page2_response.json.return_value = {
        "value": [{
            "id": "graph_msg_02",
            "conversationId": "conv_02",
            "subject": "Role 2",
            "from": {"emailAddress": {"name": "Recruiter 2", "address": "rec2@talent.com"}},
            "receivedDateTime": "2026-09-10T09:00:00Z",
            "bodyPreview": "Preview 2",
            "body": {"content": "Body 2", "contentType": "text"}
        }]
    }

    mock_get.side_effect = [page1_response, page2_response]

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch.object(graph, "get_access_token", return_value="mock_token"):
        messages, err = graph.fetch_inbox_messages("kinlawb@outlook.com", limit=2)
        assert err is None
        assert len(messages) == 2
        assert messages[0].subject == "Role 1"
        assert messages[1].subject == "Role 2"

@patch("backend.providers.graph.requests.post")
def test_graph_threaded_reply_draft_success(mock_post):
    # Mock createReply (POST 1) and attachFile (POST 2)
    draft_response = MagicMock()
    draft_response.status_code = 201
    draft_response.json.return_value = {"id": "created_draft_id_123"}

    attach_response = MagicMock()
    attach_response.status_code = 201
    attach_response.json.return_value = {"id": "attachment_id_456"}

    mock_post.side_effect = [draft_response, attach_response]

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch.object(graph, "get_access_token", return_value="mock_token"):
        with patch("backend.canonical_engine.resolve_resume_file", return_value=Path(__file__)):
            res = graph.create_reply_draft(
                account_id="kinlawb@outlook.com",
                message_id="MICROSOFT_GRAPH::kinlawb@outlook.com::orig_msg_789",
                reply_body="Thank you for reaching out.",
                resume_filename="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
            )
            assert res.success is True
            assert res.remote_object_id == "created_draft_id_123"

@patch("backend.providers.graph.requests.post")
def test_graph_attachment_failure_returns_partial_error(mock_post):
    # Mock createReply success, but attachment upload HTTP 500
    draft_response = MagicMock()
    draft_response.status_code = 201
    draft_response.json.return_value = {"id": "created_draft_id_123"}

    attach_response = MagicMock()
    attach_response.status_code = 500
    attach_response.text = "Attachment service unavailable"

    mock_post.side_effect = [draft_response, attach_response]

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch.object(graph, "get_access_token", return_value="mock_token"):
        with patch("backend.canonical_engine.resolve_resume_file", return_value=Path(__file__)):
            res = graph.create_reply_draft(
                account_id="kinlawb@outlook.com",
                message_id="MICROSOFT_GRAPH::kinlawb@outlook.com::orig_msg_789",
                reply_body="Thank you for reaching out.",
                resume_filename="Brian_Kinlaw_2026-09-08_Advisor_Canonical_current.docx"
            )
            # Must return success=False when attachment fails
            assert res.success is False
            assert res.error_code == "ATTACHMENT_FAILED"
            assert "attaching" in res.safe_message.lower()

# --- Gmail Provider (Mocked) Tests ---

@patch("backend.providers.gmail.requests.get")
def test_gmail_validation(mock_get):
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"emailAddress": "briankkinlaw@gmail.com"}

    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
    with patch.object(gmail, "get_access_token", return_value="mock_gmail_token"):
        res = gmail.validate_connection("briankkinlaw@gmail.com")
        assert res.success is True
        assert res.provider == "GMAIL"

@patch("backend.providers.gmail.requests.get")
@patch("backend.providers.gmail.requests.post")
def test_gmail_create_draft(mock_post, mock_get):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"id": "gmail_draft_999"}
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "id": "gmail_thread_111",
        "threadId": "thread_123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Re: Opportunity"},
                {"name": "From", "value": "recruiter@example.com"},
                {"name": "Message-ID", "value": "<msg123@example.com>"}
            ]
        }
    }

    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
    with patch.object(gmail, "get_access_token", return_value="mock_gmail_token"):
        with patch("backend.canonical_engine.resolve_resume_file", return_value=Path(__file__)):
            res = gmail.create_reply_draft(
                account_id="briankkinlaw@gmail.com",
                message_id="GMAIL::briankkinlaw@gmail.com::gmail_thread_111",
                reply_body="Hi recruiter, here is my resume.",
                resume_filename="test_resume.docx"
            )
            assert res.success is True
            assert res.remote_object_id == "gmail_draft_999"


def test_gmail_auth_url():
    gmail = GmailProvider(client_id="test-client-id", client_secret="test-secret")
    url = gmail.get_auth_url()
    assert url is not None
    assert "accounts.google.com" in url
    assert "test-client-id" in url

@patch("backend.providers.gmail.requests.post")
@patch("backend.providers.gmail.requests.get")
def test_gmail_token_exchange(mock_get, mock_post):
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {
        "access_token": "mock_google_access",
        "refresh_token": "mock_google_refresh"
    }
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"emailAddress": "briankkinlaw@gmail.com"}

    gmail = GmailProvider(client_id="test-client-id", client_secret="test-secret")
    with patch("backend.providers.gmail.set_secret") as mock_set:
        res = gmail.exchange_code_for_token("mock_code_123")
        assert res.success is True
        assert res.account_id == "briankkinlaw@gmail.com"
        assert mock_set.called

# --- IMAP Provider (Mocked) Tests ---

def test_imap_rfc6154_folder_discovery():
    imap = ImapProvider()
    mock_client = MagicMock()
    mock_client.list.return_value = ("OK", [
        b'(\\HasNoChildren) "/" "INBOX"',
        b'(\\HasNoChildren \\Drafts) "/" "Borradores"',
        b'(\\HasNoChildren \\Sent) "/" "Enviados"',
        b'(\\HasNoChildren \\Trash) "/" "Papelera"'
    ])

    folders = imap._discover_folders(mock_client, "cbkinlaw@satx.rr.com")
    assert folders["drafts"] == "Borradores"
    assert folders["sent"] == "Enviados"
    assert folders["trash"] == "Papelera"


# --- Least-Privilege OAuth Scope Tests (Phase 3.1) ---

def test_graph_scopes_least_privilege():
    """
    CRITICAL LEAST-PRIVILEGE INVARIANT:
    Verifies that Microsoft Graph OAuth scopes strictly exclude Mail.Send.
    Only User.Read and Mail.ReadWrite are requested for draft staging and mailbox sync.
    """
    from backend.config import GRAPH_SCOPES
    assert "Mail.Send" not in GRAPH_SCOPES
    assert "mail.send" not in [s.lower() for s in GRAPH_SCOPES]
    assert "User.Read" in GRAPH_SCOPES
    assert "Mail.ReadWrite" in GRAPH_SCOPES

    graph = MicrosoftGraphProvider(client_id="mock-id")
    assert "Mail.Send" not in graph.scopes
    assert "mail.send" not in [s.lower() for s in graph.scopes]


def test_gmail_scopes_least_privilege():
    """
    CRITICAL LEAST-PRIVILEGE INVARIANT:
    Verifies that Gmail OAuth scopes strictly exclude explicit gmail.send,
    and consolidate to the single minimum justified scope (gmail.modify)
    covering message reading, draft creation, and label quarantine.
    """
    from backend.providers.gmail import GMAIL_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" not in GMAIL_SCOPES
    assert not any("gmail.send" in s.lower() for s in GMAIL_SCOPES)
    assert GMAIL_SCOPES == ["https://www.googleapis.com/auth/gmail.modify"]


def test_imap_provider_has_no_smtplib_dependency():
    """
    LEAST-PRIVILEGE AUDIT:
    Verifies that ImapProvider does not import or expose smtplib.
    """
    import backend.providers.imap as imap_module
    assert not hasattr(imap_module, "smtplib")
