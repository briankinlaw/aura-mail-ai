"""
Unit and Integration Tests for Localhost API Browser-Origin Defense & Auth Hardening (Phase 2).

Approved Threat Model:
  - In-Scope: Unauthorized browser origins, cross-site request attacks (CSRF), sandboxed/null
    origins, DNS-rebinding Host abuse, and accidental unauthenticated API access.
  - Out-of-Scope: Malicious software already running as the logged-in macOS user ($UID),
    same-user filesystem access, or root compromise.

Verifies:
  - Removal of wildcard CORS and null origin allowlists.
  - Rejection of unauthorized and lookalike origins via CORS preflight and server-side Origin checks.
  - Host header validation against DNS rebinding attacks via TrustedHostMiddleware.
  - Absence of unauthenticated credential bootstrap endpoints (/api/auth/session).
  - Strict enforcement of request authorization on all privileged endpoints with zero side effects.
  - Proper handling of malformed and invalid tokens.
  - Server-rendered same-origin token delivery for legitimate local UI and add-in.
  - Absence of session token in unrelated API responses and static assets.
  - Functional preservation of external OAuth browser redirects.
"""

import io
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app, ALLOWED_ORIGINS, ALLOWED_HOSTS
from backend.auth import (
    get_local_session_token,
    get_auth_headers,
    verify_local_token,
    reset_local_session_token
)

unauth_client = TestClient(app)
auth_client = TestClient(app)
auth_client.headers.update(get_auth_headers())


# --- 1. CORS & Browser-Origin Security Tests ---

def test_cors_wildcard_and_null_removed():
    """
    CRITICAL SECURITY INVARIANT:
    Verifies that wildcard '*' and opaque 'null' origins are completely removed from CORS allowlist.
    """
    assert "*" not in ALLOWED_ORIGINS
    assert "null" not in ALLOWED_ORIGINS
    assert len(ALLOWED_ORIGINS) > 0


def test_cors_approved_origins_accepted():
    """Verifies that legitimate localhost, 127.0.0.1, and local development origins are permitted."""
    for origin in ALLOWED_ORIGINS:
        response = unauth_client.options(
            "/api/status",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin


def test_cors_null_origin_rejected():
    """
    SECURITY INVARIANT:
    Verifies that preflight requests presenting 'Origin: null' (sandboxed iframes, opaque contexts) are rejected.
    """
    response = unauth_client.options(
        "/api/status",
        headers={
            "Origin": "null",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert response.headers.get("access-control-allow-origin") != "null"


def test_cors_unknown_and_lookalike_origins_rejected():
    """
    SECURITY INVARIANT:
    Verifies that arbitrary external origins, lookalikes, and subdomain spoofing are rejected during preflight.
    """
    malicious_origins = [
        "https://evil-attacker.com",
        "http://malicious-site.org",
        "https://phishing-aura.net",
        "http://localhost.evil.com",
        "http://localhost:8000.attacker.com",
        "http://127.0.0.1.attacker.com",
        "http://localhost:9999",
        "http://127.0.0.1:8080"
    ]
    for origin in malicious_origins:
        response = unauth_client.options(
            "/api/status",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert response.headers.get("access-control-allow-origin") != origin


# --- 2. Host Validation & DNS-Rebinding Defense ---

def test_host_validation_dns_rebinding_rejected():
    """
    DNS-REBINDING DEFENSE:
    Verifies that requests arriving with untrusted Host headers (e.g. attacker domains in DNS rebinding)
    are rejected with 400 Bad Request by TrustedHostMiddleware.
    """
    untrusted_hosts = [
        "evil-attacker.com",
        "malicious-rebind.net",
        "attacker.com:8000",
        "192.168.1.50:8000"
    ]
    for host in untrusted_hosts:
        res = unauth_client.get("/api/status", headers={"Host": host})
        assert res.status_code == 400
        assert "Invalid host header" in res.text


def test_host_validation_legitimate_hosts_accepted():
    """Verifies that legitimate loopback hosts (localhost, 127.0.0.1, testserver) are accepted."""
    trusted_hosts = ["localhost", "127.0.0.1", "testserver"]
    for host in trusted_hosts:
        res = unauth_client.get("/api/status", headers={"Host": host})
        assert res.status_code == 200


# --- 3. Server-Side Origin Verification (Defense in Depth) ---

def test_server_side_origin_rejection_on_privileged_endpoints():
    """
    DEFENSE IN DEPTH:
    Verifies that even if an attacker supplies a valid token, an unauthorized browser Origin
    (or Origin: null) is rejected with 403 Forbidden by server-side verification.
    """
    token = get_local_session_token()
    disallowed_origins = [
        "https://evil-attacker.com",
        "null",
        "http://localhost.attacker.com",
        "http://127.0.0.1.attacker.com",
    ]
    for bad_origin in disallowed_origins:
        res = unauth_client.post(
            "/api/calendar/availability",
            json={"days_ahead": 3},
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": bad_origin
            }
        )
        assert res.status_code == 403
        assert "Origin verification failed" in res.json().get("detail", "")


# --- 4. Absence of Unauthenticated Credential Bootstrap Endpoints ---

def test_no_unauthenticated_session_credential_disclosure_endpoint():
    """
    CRITICAL SECURITY INVARIANT:
    Verifies that no unauthenticated JSON API endpoint (/api/auth/session) exists
    to disclose the session token.
    """
    response = unauth_client.get("/api/auth/session")
    assert response.status_code in [404, 405]


# --- 5. Request Authorization on Privileged Endpoints ---

PRIVILEGED_POST_ENDPOINTS = [
    ("/api/settings", {"demo_mode": True}),
    ("/api/profile", {"full_name": "Test User", "primary_role": "Architect"}),
    ("/api/accounts/test@outlook.com/test", {}),
    ("/api/accounts/test@outlook.com/disconnect", {}),
    ("/api/emails/sync", {}),
    ("/api/emails/test_id/generate-reply", {"tone": "Professional"}),
    ("/api/emails/test_id/save-draft", {"reply_body": "test"}),
    ("/api/emails/test_id/send-reply", {"reply_body": "test"}),
    ("/api/emails/clean-noise", {}),
    ("/api/emails/test_id/trash", {}),
    ("/api/daemon/run-now", {}),
    ("/api/radar/triage", {"subject": "Test", "body": "Test body"}),
    ("/api/radar/draft", {"subject": "Test", "body": "Test body"}),
    ("/api/calendar/availability", {}),
    ("/api/radar/risk-check", {"subject": "Test", "body": "Test", "draft_reply": "Test"}),
    ("/api/canonical/match", {"job_title": "Architect"}),
    ("/api/auth/msal/device-code", {}),
    ("/api/auth/msal/device-code/poll", {}),
    ("/api/auth/submit-code", {"code": "123"}),
    ("/api/auth/google/submit-code", {"code": "123"}),
    ("/api/auth/imap", {"email": "a@b.com", "imap_server": "mail.example.com"}),
    ("/api/emails/resolve-item", {"item_id": "test_item_id"}),
]



@pytest.mark.parametrize("path,payload", PRIVILEGED_POST_ENDPOINTS)
def test_all_privileged_endpoints_reject_unauthenticated_request(path, payload):
    """
    SECURITY INVARIANT:
    Verifies that every privileged, state-changing endpoint rejects unauthenticated
    requests with 401 Unauthorized.
    """
    response = unauth_client.post(path, json=payload)
    assert response.status_code == 401
    assert "Authentication required" in response.json().get("detail", "")


def test_unauthenticated_upload_resume_rejected():
    """Verifies that multipart file upload to /api/profile/upload-resume rejects unauthenticated callers."""
    fake_file = io.BytesIO(b"Fake resume content")
    response = unauth_client.post(
        "/api/profile/upload-resume",
        files={"file": ("test_resume.docx", fake_file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert response.status_code == 401
    assert "Authentication required" in response.json().get("detail", "")


def test_privileged_endpoints_reject_malformed_authorization():
    """Verifies that non-Bearer or malformed authorization schemes return 403 Forbidden."""
    malformed_headers = [
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Token secret123"},
        {"Authorization": "InvalidScheme token"},
    ]
    for headers in malformed_headers:
        response = unauth_client.post(
            "/api/calendar/availability",
            json={},
            headers=headers
        )
        assert response.status_code == 403
        assert "Malformed authorization header" in response.json().get("detail", "")


def test_privileged_endpoints_reject_empty_or_whitespace_bearer():
    """Verifies that empty Bearer headers fail with 401 Unauthorized or 403 Forbidden."""
    response = unauth_client.post(
        "/api/calendar/availability",
        json={},
        headers={"Authorization": "Bearer "}
    )
    assert response.status_code in [401, 403]


def test_privileged_endpoints_reject_invalid_token():
    """Verifies that incorrect or forged tokens fail with 403 Forbidden."""
    fake_token = "0000000000000000000000000000000000000000000000000000000000000000"

    # Bearer header
    res1 = unauth_client.post(
        "/api/calendar/availability",
        json={},
        headers={"Authorization": f"Bearer {fake_token}"}
    )
    assert res1.status_code == 403
    assert "Invalid local authorization token" in res1.json().get("detail", "")

    # X-Aura-Session-Token header
    res2 = unauth_client.post(
        "/api/calendar/availability",
        json={},
        headers={"X-Aura-Session-Token": fake_token}
    )
    assert res2.status_code == 403

    # X-Aura-Token header
    res3 = unauth_client.post(
        "/api/calendar/availability",
        json={},
        headers={"X-Aura-Token": fake_token}
    )
    assert res3.status_code == 403


# --- 6. Side-Effect Prevention Verification ---

def test_unauthenticated_send_reply_executes_no_side_effects():
    """Verifies that rejected unauthenticated requests to send-reply trigger zero provider actions."""
    with patch("backend.main.provider_manager.send_reply") as mock_send:
        res = unauth_client.post("/api/emails/test_id/send-reply", json={"reply_body": "unauthorized"})
        assert res.status_code == 401
        assert not mock_send.called


def test_unauthenticated_clean_noise_executes_no_side_effects():
    """Verifies that rejected unauthenticated requests to clean-noise trigger zero provider actions."""
    with patch("backend.main.provider_manager.move_message") as mock_move:
        res = unauth_client.post("/api/emails/clean-noise", json={})
        assert res.status_code == 401
        assert not mock_move.called


def test_unauthenticated_trash_executes_no_side_effects():
    """Verifies that rejected unauthenticated requests to trash trigger zero provider actions."""
    with patch("backend.main.provider_manager.delete_message") as mock_delete:
        res = unauth_client.post("/api/emails/test_id/trash", json={})
        assert res.status_code == 401
        assert not mock_delete.called


# --- 7. Legitimate Authenticated Access & Same-Origin Delivery ---

def test_authenticated_requests_succeed_with_token():
    """Verifies that legitimate requests with valid authorization token succeed."""
    token = get_local_session_token()

    # Via Bearer header with canonical HTTPS origin
    res1 = unauth_client.post(
        "/api/calendar/availability",
        json={"days_ahead": 3},
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://localhost:8000"
        }
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "SUCCESS"

    # Via X-Aura-Session-Token header with canonical HTTPS origin
    res2 = unauth_client.post(
        "/api/calendar/availability",
        json={"days_ahead": 3},
        headers={
            "X-Aura-Session-Token": token,
            "Origin": "https://localhost:8000"
        }
    )
    assert res2.status_code == 200


def test_server_rendered_html_injects_token_for_same_origin():
    """
    SAME-ORIGIN BOOTSTRAP:
    Verifies that server-rendered same-origin HTML pages (/ and /add-in/taskpane.html)
    contain the injected session token runtime configuration for same-origin browser contexts
    (protected from third-party sites by the browser's Same-Origin Policy).
    """
    token = get_local_session_token()

    # Index page
    index_res = unauth_client.get("/")
    assert index_res.status_code == 200
    assert f'window.__AURA_SESSION_TOKEN__ = "{token}";' in index_res.text

    # Add-in taskpane page
    taskpane_res = unauth_client.get("/add-in/taskpane.html")
    assert taskpane_res.status_code == 200
    assert f'window.__AURA_SESSION_TOKEN__ = "{token}";' in taskpane_res.text


# --- 8. Token Disclosure Scope & Public Endpoint Invariants ---

def test_session_token_not_exposed_in_unrelated_api_responses_or_static_assets():
    """
    TOKEN EXPOSURE BOUNDARY TEST:
    Verifies that the session token is NOT leaked in unrelated JSON API endpoints,
    diagnostic endpoints, or static CSS/JS files.
    """
    token = get_local_session_token()
    public_endpoints = [
        "/api/status",
        "/api/safety-policy",
        "/api/accounts",
        "/api/settings",
        "/api/profile",
        "/api/resumes",
        "/api/canonical/resumes",
        "/api/canonical/catalog",
        "/api/canonical/ledger",
        "/api/emails",
        "/api/analytics/kpis",
        "/api/analytics/funnel",
        "/api/analytics/compensation",
        "/api/analytics/resumes-roi",
        "/api/analytics/events",
        "/api/analytics/export",
        "/api/stats",
        "/api/daemon/status",
        "/static/icon-64.png",
    ]
    with patch("backend.provider_manager.provider_manager.list_all_accounts", return_value=[]):
        for endpoint in public_endpoints:
            res = unauth_client.get(endpoint)
            assert res.status_code == 200, f"Public endpoint {endpoint} failed to return 200"
            assert token not in res.text, f"Token disclosed in response from {endpoint}!"
            assert "AURA_SESSION_TOKEN" not in res.text



# --- 9. OAuth Special Endpoints & Public Assets ---

def test_oauth_endpoints_remain_accessible_without_bearer_token():
    """
    Verifies that external OAuth redirect callbacks and URL generation endpoints
    remain accessible to top-level browser identity flows without requiring Bearer headers.
    """
    # MSAL OAuth URL
    msal_url_res = unauth_client.get("/api/auth/msal/url")
    assert msal_url_res.status_code in [200, 400]

    # Google OAuth URL
    google_url_res = unauth_client.get("/api/auth/google/url")
    assert google_url_res.status_code in [200, 400]

    # MSAL OAuth Callback (browser redirect)
    msal_cb_res = unauth_client.get("/api/auth/callback?error=access_denied", follow_redirects=False)
    assert msal_cb_res.status_code == 307

    # Google OAuth Callback (browser redirect)
    google_cb_res = unauth_client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert google_cb_res.status_code == 307


def test_public_read_only_and_static_routes_remain_accessible():
    """Verifies that public system status, safety policy, and static assets remain accessible."""
    assert unauth_client.get("/api/status").status_code == 200
    assert unauth_client.get("/api/safety-policy").status_code == 200
    assert unauth_client.get("/static/icon-64.png").status_code == 200


# --- 10. Phase 2.1 Integration Hardening Security Invariants ---

def test_microsoft_parent_origins_not_granted_api_cors():
    """
    PHASE 2.1 REGRESSION TEST:
    Verifies that Microsoft parent host domains (e.g. outlook.office.com, appsforoffice.microsoft.com)
    are NOT included in API CORS allowlist.
    Iframe/webview framing is handled separately via CSP frame-ancestors.
    """
    microsoft_origins = [
        "https://outlook.office.com",
        "https://appsforoffice.microsoft.com",
        "https://outlook.office365.com",
        "https://outlook.live.com",
    ]
    for ms_origin in microsoft_origins:
        assert ms_origin not in ALLOWED_ORIGINS
        # Preflight check rejected
        res = unauth_client.options(
            "/api/status",
            headers={
                "Origin": ms_origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert res.headers.get("access-control-allow-origin") != ms_origin


def test_taskpane_csp_frame_ancestors_configured():
    """
    PHASE 2.1 FRAMING SECURITY:
    Verifies that /add-in/taskpane.html serves a Content-Security-Policy with frame-ancestors
    permitting Outlook web embedding without widening API CORS.
    """
    res = unauth_client.get("/add-in/taskpane.html")
    assert res.status_code == 200
    csp = res.headers.get("content-security-policy", "")
    assert "frame-ancestors" in csp
    assert "https://outlook.office.com" in csp
    assert "https://outlook.office365.com" in csp


def test_canonical_cors_strict_allowlist():
    """
    PHASE 2.1 FINDING 3 REGRESSION TEST:
    Verifies that the default production/local-desktop CORS allowlist strictly contains ONLY
    canonical 'https://localhost:8000'.
    HTTP localhost origins, 127.0.0.1 origins, and Microsoft parent origins are strictly rejected.
    """
    assert ALLOWED_ORIGINS == ["https://localhost:8000"]

    rejected_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://127.0.0.1:8000",
        "https://outlook.office.com",
        "https://appsforoffice.microsoft.com",
        "https://localhost:8000.attacker.com",
    ]
    for origin in rejected_origins:
        res = unauth_client.options(
            "/api/status",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert res.headers.get("access-control-allow-origin") != origin


def test_tls_fail_closed_on_missing_certificate(tmp_path, monkeypatch):
    """
    PHASE 2.1 FINDING 1 REGRESSION TEST:
    Verifies that require_ssl_context_paths() refuses startup and raises RuntimeError when:
    - certificate is missing
    - private key is missing
    - both are missing
    Ensures HTTP fallback is strictly prohibited.
    """
    from backend.config import require_ssl_context_paths

    # Scenario A: Neither file exists
    missing_cert = tmp_path / "nonexistent_cert.pem"
    missing_key = tmp_path / "nonexistent_key.pem"
    monkeypatch.setenv("AURA_SSL_CERT", str(missing_cert))
    monkeypatch.setenv("AURA_SSL_KEY", str(missing_key))
    with pytest.raises(RuntimeError, match="FATAL: Missing local TLS certificate or private key"):
        require_ssl_context_paths()

    # Scenario B: Certificate exists but private key missing
    real_cert = tmp_path / "real_cert.pem"
    real_cert.write_text("CERT")
    monkeypatch.setenv("AURA_SSL_CERT", str(real_cert))
    monkeypatch.setenv("AURA_SSL_KEY", str(missing_key))
    with pytest.raises(RuntimeError, match="FATAL: Missing local TLS certificate or private key"):
        require_ssl_context_paths()

    # Scenario C: Private key exists but certificate missing
    real_key = tmp_path / "real_key.pem"
    real_key.write_text("KEY")
    monkeypatch.setenv("AURA_SSL_CERT", str(missing_cert))
    monkeypatch.setenv("AURA_SSL_KEY", str(real_key))
    with pytest.raises(RuntimeError, match="FATAL: Missing local TLS certificate or private key"):
        require_ssl_context_paths()


def test_tls_success_configuration(tmp_path, monkeypatch):
    """
    PHASE 2.1 TLS SUCCESS CONFIGURATION TEST:
    Verifies that require_ssl_context_paths() returns both cert and key when both exist.
    """
    from backend.config import require_ssl_context_paths

    fake_cert = tmp_path / "valid_cert.pem"
    fake_key = tmp_path / "valid_key.pem"
    fake_cert.write_text("VALID_CERT")
    fake_key.write_text("VALID_KEY")

    monkeypatch.setenv("AURA_SSL_CERT", str(fake_cert))
    monkeypatch.setenv("AURA_SSL_KEY", str(fake_key))
    cert_p, key_p = require_ssl_context_paths()
    assert cert_p == fake_cert
    assert key_p == fake_key


def test_menubar_server_launch_fails_closed_without_tls(tmp_path, monkeypatch):
    """
    PHASE 2.1 LAUNCH DEFENSE TEST:
    Verifies that ensure_server_running() in menubar_app fails closed with RuntimeError
    when local TLS certs are absent, rather than silently falling back to HTTP.
    """
    from backend.menubar_app import ensure_server_running

    missing_cert = tmp_path / "absent_cert.pem"
    missing_key = tmp_path / "absent_key.pem"
    monkeypatch.setenv("AURA_SSL_CERT", str(missing_cert))
    monkeypatch.setenv("AURA_SSL_KEY", str(missing_key))

    with patch("backend.menubar_app.is_server_running", return_value=False):
        with pytest.raises(RuntimeError, match="FATAL: Missing local TLS certificate or private key"):
            ensure_server_running()


def test_frontend_taskpane_authentication_contract():
    """
    PHASE 2.1 FINDING 2 STATIC CONTRACT TEST:
    Verifies that the taskpane frontend (frontend/add-in/taskpane.js):
    1. Defines getAuthHeaders helper attaching the session token.
    2. Uses getAuthHeaders() for /api/emails/resolve-item and other privileged API calls.
    3. Handles HTTP 401/403 authorization failures distinctly from 404 cache misses.
    """
    from backend.config import BASE_DIR
    taskpane_js_path = BASE_DIR / "frontend" / "add-in" / "taskpane.js"
    assert taskpane_js_path.is_file(), "taskpane.js must exist"

    content = taskpane_js_path.read_text(encoding="utf-8")

    # 1. getAuthHeaders definition
    assert "function getAuthHeaders" in content
    assert "Authorization" in content
    assert "X-Aura-Session-Token" in content

    # 2. Authenticated resolve-item invocation
    assert "/api/emails/resolve-item" in content
    assert "headers: getAuthHeaders()" in content

    # 3. Distinct authorization failure handling (401/403 vs 404)
    assert "status === 401" in content or "status === 403" in content
    assert "Resolver authorization failure" in content
    assert "status === 404" in content
