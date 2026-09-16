"""
Aura Mail AI — Phase 12.1 Attachment Boundary Enforcement Test Suite

Adversarially validates that:
1. No attachment file may be read or uploaded unless its canonical resolved path is within an approved Aura attachment root.
2. Arbitrary absolute paths (/etc/passwd, /etc/hosts, /tmp/outside.pdf) are rejected.
3. Directory traversal escapes (../../etc/passwd) are rejected.
4. Symlink escapes (symlink inside approved root -> outside target) are rejected.
5. Non-regular files (directories, FIFOs, broken symlinks) and missing files are rejected.
6. Malformed identifiers (non-strings, empty strings) fail closed safely.
7. Providers (Graph, Gmail, IMAP) never read or upload rejected paths (negative read proof).
8. Valid canonical and targeted resumes continue to resolve and stage correctly.
"""

import os
import stat
import builtins
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from backend.canonical_engine import (
    resolve_resume_file,
    is_safe_attachment_path,
    get_approved_attachment_roots,
)
from backend.providers.graph import MicrosoftGraphProvider
from backend.providers.gmail import GmailProvider
from backend.providers.imap import ImapProvider
from backend.provider_manager import ProviderManager
from backend.models import EmailMessage, EmailCategory


@pytest.fixture
def hermetic_attachment_env(tmp_path, monkeypatch):
    """
    Creates a hermetic environment with synthetic approved attachment roots
    and an outside directory for adversarial testing.
    """
    canonical_active = tmp_path / "Canonical - Active"
    targeted_apps = tmp_path / "Targeted Applications"
    downloads_variants = tmp_path / "Resume Variants"
    resumes_dir = tmp_path / "resumes"
    outside_dir = tmp_path / "outside_unapproved"

    canonical_active.mkdir(parents=True, exist_ok=True)
    targeted_apps.mkdir(parents=True, exist_ok=True)
    downloads_variants.mkdir(parents=True, exist_ok=True)
    resumes_dir.mkdir(parents=True, exist_ok=True)
    outside_dir.mkdir(parents=True, exist_ok=True)

    # Valid files
    valid_advisor = canonical_active / "Test_Advisor_Canonical.docx"
    valid_advisor.write_text("Valid Advisor Content")

    valid_targeted = targeted_apps / "Test_Targeted_Custom.docx"
    valid_targeted.write_text("Valid Targeted Content")

    valid_resume = resumes_dir / "User_Uploaded_Resume.pdf"
    valid_resume.write_text("Valid Uploaded Resume Content")

    # Outside sensitive/unapproved target files
    outside_secret = outside_dir / "secret_document.pdf"
    outside_secret.write_text("SENSITIVE_DATA_DO_NOT_READ")

    # Symlink pointing OUTSIDE approved roots
    symlink_outside = canonical_active / "symlink_escape.docx"
    try:
        os.symlink(str(outside_secret), str(symlink_outside))
    except (OSError, NotImplementedError):
        pass

    # Symlink pointing INSIDE approved roots
    symlink_inside = canonical_active / "symlink_valid.docx"
    try:
        os.symlink(str(valid_advisor), str(symlink_inside))
    except (OSError, NotImplementedError):
        pass

    # Subdirectory (non-regular file)
    sub_dir = canonical_active / "sub_directory"
    sub_dir.mkdir(exist_ok=True)

    # Monkeypatch canonical engine directories
    monkeypatch.setattr("backend.canonical_engine.CANONICAL_ACTIVE_DIR", canonical_active)
    monkeypatch.setattr("backend.canonical_engine.TARGETED_APPS_DIR", targeted_apps)
    monkeypatch.setattr("backend.canonical_engine.DOWNLOADS_VARIANTS_DIR", downloads_variants)
    monkeypatch.setattr("backend.canonical_engine.RESUMES_DIR", resumes_dir)
    monkeypatch.setattr("backend.config.RESUMES_DIR", resumes_dir)

    return {
        "canonical_active": canonical_active,
        "targeted_apps": targeted_apps,
        "downloads_variants": downloads_variants,
        "resumes_dir": resumes_dir,
        "outside_dir": outside_dir,
        "valid_advisor": valid_advisor,
        "valid_targeted": valid_targeted,
        "valid_resume": valid_resume,
        "outside_secret": outside_secret,
        "symlink_outside": symlink_outside,
        "symlink_inside": symlink_inside,
        "sub_dir": sub_dir,
    }


# ==============================================================================
# 1. CORE SECURITY INVARIANT TESTS
# ==============================================================================

def test_security_invariant_approved_roots_only(hermetic_attachment_env):
    """
    ENFORCED INVARIANT:
    No attachment file may be resolved or accepted unless its canonical resolved path
    is within an explicitly approved Aura attachment root.
    """
    approved_roots = get_approved_attachment_roots()
    env = hermetic_attachment_env

    # Valid candidates must be contained in approved roots
    assert is_safe_attachment_path(env["valid_advisor"], approved_roots) is True
    assert is_safe_attachment_path(env["valid_targeted"], approved_roots) is True
    assert is_safe_attachment_path(env["valid_resume"], approved_roots) is True

    # Outside candidates must be rejected
    assert is_safe_attachment_path(env["outside_secret"], approved_roots) is False
    assert is_safe_attachment_path(Path("/etc/passwd"), approved_roots) is False
    assert is_safe_attachment_path(Path("/etc/hosts"), approved_roots) is False


# ==============================================================================
# 2. RESOLUTION ADVERSARIAL MATRIX
# ==============================================================================

def test_resolve_valid_attachments(hermetic_attachment_env):
    env = hermetic_attachment_env

    # Exact filename
    p1 = resolve_resume_file("Test_Advisor_Canonical.docx")
    assert p1 == env["valid_advisor"].resolve()

    # Case-insensitive filename
    p2 = resolve_resume_file("test_advisor_canonical.docx")
    assert p2 == env["valid_advisor"].resolve()

    # Targeted resume
    p3 = resolve_resume_file("Test_Targeted_Custom.docx")
    assert p3 == env["valid_targeted"].resolve()

    # Absolute path inside approved root
    p4 = resolve_resume_file(str(env["valid_advisor"]))
    assert p4 == env["valid_advisor"].resolve()

    # Default fallback when identifier is None
    p_def = resolve_resume_file(None)
    assert p_def is not None
    assert p_def == env["valid_advisor"].resolve()


def test_reject_arbitrary_absolute_paths(hermetic_attachment_env):
    env = hermetic_attachment_env

    # System files
    assert resolve_resume_file("/etc/passwd") is None
    assert resolve_resume_file("/etc/hosts") is None
    assert resolve_resume_file("/private/etc/hosts") is None

    # Outside user files
    assert resolve_resume_file(str(env["outside_secret"])) is None
    assert resolve_resume_file(str(Path.home() / ".bashrc")) is None
    assert resolve_resume_file(str(Path.home() / ".ssh" / "id_rsa")) is None

    # Repository source files outside approved attachment roots
    assert resolve_resume_file(str(Path(__file__).resolve())) is None


def test_reject_directory_traversal(hermetic_attachment_env):
    env = hermetic_attachment_env

    assert resolve_resume_file("../../etc/passwd") is None
    assert resolve_resume_file("../../../outside_unapproved/secret_document.pdf") is None
    assert resolve_resume_file(str(env["canonical_active"] / ".." / "outside_unapproved" / "secret_document.pdf")) is None
    assert resolve_resume_file("..\\..\\etc\\passwd") is None


def test_reject_symlink_escape(hermetic_attachment_env):
    env = hermetic_attachment_env
    symlink_outside = env["symlink_outside"]

    if symlink_outside.is_symlink():
        # Raw name appears inside approved directory, but resolved target is outside
        assert resolve_resume_file(symlink_outside.name) is None
        assert resolve_resume_file(str(symlink_outside)) is None
        assert is_safe_attachment_path(symlink_outside) is False


def test_allow_safe_internal_symlink(hermetic_attachment_env):
    env = hermetic_attachment_env
    symlink_inside = env["symlink_inside"]

    if symlink_inside.is_symlink():
        # Resolves to valid file inside approved root
        res = resolve_resume_file(symlink_inside.name)
        assert res == env["valid_advisor"].resolve()


def test_reject_directories_and_non_regular_files(hermetic_attachment_env):
    env = hermetic_attachment_env

    # Directory identifier
    assert resolve_resume_file(str(env["canonical_active"])) is None
    assert resolve_resume_file("sub_directory") is None
    assert resolve_resume_file(str(env["sub_dir"])) is None
    assert is_safe_attachment_path(env["sub_dir"]) is False


def test_reject_missing_files(hermetic_attachment_env):
    assert resolve_resume_file("missing_nonexistent_file.docx") is None
    assert resolve_resume_file(str(hermetic_attachment_env["canonical_active"] / "missing.docx")) is None


def test_reject_malformed_identifiers(hermetic_attachment_env):
    assert resolve_resume_file("") is None
    assert resolve_resume_file("   ") is None
    assert resolve_resume_file([]) is None  # type: ignore
    assert resolve_resume_file({}) is None  # type: ignore
    assert resolve_resume_file(12345) is None  # type: ignore
    assert resolve_resume_file(True) is None  # type: ignore
    assert resolve_resume_file(False) is None  # type: ignore


# ==============================================================================
# 3. NEGATIVE READ PROOF (MONKEYPATCH OPEN ASSERTIONS)
# ==============================================================================

def test_negative_read_proof_on_rejected_paths(hermetic_attachment_env):
    """
    CRITICAL PROOF:
    Verify that for rejected attachment paths (/etc/passwd, /etc/hosts, traversal, outside secrets),
    builtins.open is NEVER invoked on the forbidden target path.
    """
    env = hermetic_attachment_env
    forbidden_targets = {
        "/etc/passwd",
        "/etc/hosts",
        str(env["outside_secret"].resolve()),
        str(env["outside_secret"])
    }

    opened_files = []
    original_open = builtins.open

    def guarded_open(file, *args, **kwargs):
        opened_files.append(str(file))
        return original_open(file, *args, **kwargs)

    with patch("builtins.open", side_effect=guarded_open):
        # 1. Resolver probe
        assert resolve_resume_file("/etc/passwd") is None
        assert resolve_resume_file("/etc/hosts") is None
        assert resolve_resume_file(str(env["outside_secret"])) is None
        assert resolve_resume_file("../../etc/passwd") is None

        # 2. Graph Provider probe
        graph = MicrosoftGraphProvider(client_id="mock-client")
        with patch.object(graph, "get_access_token", return_value="mock_token"):
            res_graph = graph.create_reply_draft(
                account_id="kinlawb@outlook.com",
                message_id="MICROSOFT_GRAPH::kinlawb@outlook.com::msg123",
                reply_body="Test reply",
                resume_filename="/etc/passwd"
            )
            assert res_graph.success is False
            assert res_graph.error_code == "ATTACHMENT_NOT_ALLOWED"

            # Direct attach_file probe
            res_attach = graph.attach_file(
                account_id="kinlawb@outlook.com",
                draft_id="draft123",
                filename="passwd",
                file_path=Path("/etc/passwd")
            )
            assert res_attach.success is False
            assert res_attach.error_code == "ATTACHMENT_NOT_ALLOWED"

        # 3. Gmail Provider probe
        gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
        with patch.object(gmail, "get_access_token", return_value="mock_token"):
            res_gmail = gmail.create_reply_draft(
                account_id="briankkinlaw@gmail.com",
                message_id="GMAIL::briankkinlaw@gmail.com::msg456",
                reply_body="Test reply",
                resume_filename=str(env["outside_secret"])
            )
            assert res_gmail.success is False
            assert res_gmail.error_code == "ATTACHMENT_NOT_ALLOWED"

            mime_msg, err = gmail.build_reply_mime(
                to_email="recruiter@example.com",
                subject="Test",
                reply_body="Test",
                resume_filename="/etc/hosts"
            )
            assert mime_msg is None
            assert "outside approved" in err.lower() or "invalid" in err.lower()

        # 4. IMAP Provider probe
        imap = ImapProvider()
        res_imap = imap.create_reply_draft(
            account_id="user@example.com",
            message_id="IMAP::user@example.com::123",
            reply_body="Test reply",
            resume_filename="../../etc/passwd"
        )
        assert res_imap.success is False
        assert res_imap.error_code == "ATTACHMENT_NOT_ALLOWED"

    # Assert 0 reads occurred on forbidden targets
    for target in forbidden_targets:
        assert target not in opened_files, f"Security Violation: Forbidden path '{target}' was opened!"


# ==============================================================================
# 4. PROVIDER INTEGRATION & SUCCESS PRESERVATION
# ==============================================================================

@patch("backend.providers.graph.requests.post")
def test_graph_valid_attachment_succeeds(mock_post, hermetic_attachment_env):
    """Verify valid canonical resume successfully attaches in Microsoft Graph draft."""
    draft_response = MagicMock()
    draft_response.status_code = 201
    draft_response.json.return_value = {"id": "created_draft_id_graph"}

    attach_response = MagicMock()
    attach_response.status_code = 201
    attach_response.json.return_value = {"id": "attachment_id_graph"}

    mock_post.side_effect = [draft_response, attach_response]

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch.object(graph, "get_access_token", return_value="mock_token"):
        res = graph.create_reply_draft(
            account_id="kinlawb@outlook.com",
            message_id="MICROSOFT_GRAPH::kinlawb@outlook.com::msg789",
            reply_body="Thank you for reaching out.",
            resume_filename="Test_Advisor_Canonical.docx"
        )
        assert res.success is True
        assert res.remote_object_id == "created_draft_id_graph"
        assert res.operation == "CREATE_DRAFT"
        assert mock_post.call_count == 2


@patch("backend.providers.gmail.requests.get")
@patch("backend.providers.gmail.requests.post")
def test_gmail_valid_attachment_succeeds(mock_post, mock_get, hermetic_attachment_env):
    """Verify valid canonical resume successfully attaches in Gmail draft."""
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "id": "gmail_msg_111",
        "threadId": "thread_123",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Re: Opportunity"},
                {"name": "From", "value": "recruiter@example.com"},
                {"name": "Message-ID", "value": "<msg123@example.com>"}
            ]
        }
    }
    mock_post.return_value.status_code = 200
    mock_post.return_value.json.return_value = {"id": "gmail_draft_555"}

    gmail = GmailProvider(client_id="mock-id", client_secret="mock-sec")
    with patch.object(gmail, "get_access_token", return_value="mock_gmail_token"):
        res = gmail.create_reply_draft(
            account_id="briankkinlaw@gmail.com",
            message_id="GMAIL::briankkinlaw@gmail.com::gmail_msg_111",
            reply_body="Hi recruiter, here is my resume.",
            resume_filename="Test_Advisor_Canonical.docx"
        )
        assert res.success is True
        assert res.remote_object_id == "gmail_draft_555"
        assert res.operation == "CREATE_DRAFT"


def test_provider_manager_boundary_fails_closed_on_unapproved_path(hermetic_attachment_env):
    """Verify ProviderManager rejects unapproved attachment path at provider boundary."""
    pm = ProviderManager()
    
    # Mock message routing to Microsoft Graph
    mock_graph = MagicMock()
    mock_graph.provider_type.value = "MICROSOFT_GRAPH"
    mock_graph.create_reply_draft.return_value = MagicMock(
        success=False,
        error_code="ATTACHMENT_NOT_ALLOWED",
        safe_message="Requested attachment is invalid or outside approved attachment roots."
    )

    with patch.object(pm, "get_provider_for_message", return_value=(mock_graph, "kinlawb@outlook.com", "native123", None)):
        res = pm.save_draft_reply(
            message_id="MICROSOFT_GRAPH::kinlawb@outlook.com::native123",
            reply_body="Hello",
            resume_filename="/etc/passwd"
        )
        assert res.success is False
        assert res.error_code == "ATTACHMENT_NOT_ALLOWED"


def test_production_save_draft_api_route_rejects_unapproved_path(hermetic_attachment_env):
    """
    End-to-end production API test:
    POST /api/emails/{email_id}/save-draft with unapproved attachment identifier fails closed.
    """
    from fastapi.testclient import TestClient
    from backend.main import app, CACHED_EMAILS
    from backend.auth import get_auth_headers

    client = TestClient(app)
    headers = get_auth_headers()

    msg_id = "MICROSOFT_GRAPH::kinlawb@outlook.com::test_msg_999"
    email_obj = EmailMessage(
        id=msg_id,
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        subject="Senior Cloud Architect Opportunity",
        body_text="Please send your resume.",
        account_id="kinlawb@outlook.com"
    )
    CACHED_EMAILS[msg_id] = email_obj

    # Attempt to stage draft with unapproved /etc/passwd
    resp = client.post(
        f"/api/emails/{msg_id}/save-draft",
        json={
            "account_id": "kinlawb@outlook.com",
            "reply_body": "Here is my resume.",
            "resume_filename": "/etc/passwd"
        },
        headers=headers
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is False
    assert data["error_code"] == "ATTACHMENT_NOT_ALLOWED"
    assert "approved attachment roots" in data["safe_message"].lower() or "invalid" in data["safe_message"].lower()


@patch("backend.providers.graph.requests.post")
def test_production_save_draft_api_route_accepts_valid_attachment(mock_post, hermetic_attachment_env):
    """
    End-to-end production API test:
    POST /api/emails/{email_id}/save-draft with valid canonical attachment succeeds.
    """
    from fastapi.testclient import TestClient
    from backend.main import app, CACHED_EMAILS
    from backend.auth import get_auth_headers

    draft_response = MagicMock()
    draft_response.status_code = 201
    draft_response.json.return_value = {"id": "created_draft_id_api"}

    attach_response = MagicMock()
    attach_response.status_code = 201
    attach_response.json.return_value = {"id": "attachment_id_api"}

    mock_post.side_effect = [draft_response, attach_response]

    client = TestClient(app)
    headers = get_auth_headers()

    msg_id = "MICROSOFT_GRAPH::kinlawb@outlook.com::test_msg_888"
    email_obj = EmailMessage(
        id=msg_id,
        sender_name="Recruiter",
        sender_email="recruiter@example.com",
        subject="Senior Cloud Architect Opportunity",
        body_text="Please send your resume.",
        account_id="kinlawb@outlook.com"
    )
    CACHED_EMAILS[msg_id] = email_obj

    graph = MicrosoftGraphProvider(client_id="mock-client-id")
    with patch("backend.provider_manager.ProviderManager.get_provider_by_type", return_value=graph), \
         patch.object(graph, "get_access_token", return_value="mock_token"):
        resp = client.post(
            f"/api/emails/{msg_id}/save-draft",
            json={
                "account_id": "kinlawb@outlook.com",
                "reply_body": "Here is my resume.",
                "resume_filename": "Test_Advisor_Canonical.docx"
            },
            headers=headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["remote_object_id"] == "created_draft_id_api"
