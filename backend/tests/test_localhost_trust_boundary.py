"""
Unit and Integration Tests for Localhost API Trust Boundary & Auth Hardening (Phase 2 Corrective).
Verifies:
  - Removal of wildcard CORS and null origin allowlists.
  - Rejection of unknown and lookalike origins.
  - Absence of unauthenticated credential disclosure endpoints (/api/auth/session).
  - Strict enforcement of request authorization on all privileged endpoints with zero side effects.
  - Proper handling of malformed and invalid tokens.
  - Same-origin runtime token delivery for legitimate local UI and add-in.
  - Functional preservation of external OAuth browser redirects.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app, ALLOWED_ORIGINS
from backend.auth import (
    get_local_session_token,
    get_auth_headers,
    verify_local_token,
    reset_local_session_token
)

unauth_client = TestClient(app)
auth_client = TestClient(app)
auth_client.headers.update(get_auth_headers())


# --- 1. CORS Security Tests ---

def test_cors_wildcard_and_null_removed():
    """
    CRITICAL SECURITY INVARIANT:
    Verifies that wildcard '*' and opaque 'null' origins are completely removed from CORS allowlist.
    """
    assert "*" not in ALLOWED_ORIGINS
    assert "null" not in ALLOWED_ORIGINS
    assert len(ALLOWED_ORIGINS) > 0


def test_cors_approved_origins_accepted():
    """Verifies that legitimate localhost, 127.0.0.1, and Microsoft Office add-in origins are permitted."""
    approved_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://localhost:8000",
        "https://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://localhost:3000",
        "https://127.0.0.1:3000",
        "https://outlook.office.com",
        "https://outlook.office365.com",
        "https://appsforoffice.microsoft.com",
    ]
    for origin in approved_origins:
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
    Verifies that requests presenting 'Origin: null' (sandboxed iframes, opaque contexts) are rejected.
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
    Verifies that arbitrary external origins, lookalikes, and subdomain spoofing are rejected.
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


# --- 2. Absence of Unauthenticated Credential Disclosure ---

def test_no_unauthenticated_session_credential_disclosure_endpoint():
    """
    CRITICAL SECURITY INVARIANT (Finding 1 Correction):
    Verifies that no unauthenticated JSON API endpoint (/api/auth/session) exists
    to disclose the local bearer token to arbitrary callers.
    """
    response = unauth_client.get("/api/auth/session")
    assert response.status_code in [404, 405]


# --- 3. Request Authorization on Privileged Endpoints ---

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


# --- 4. Side-Effect Prevention Verification ---

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


# --- 5. Legitimate Authenticated Access & Same-Origin Delivery ---

def test_authenticated_requests_succeed_with_token():
    """Verifies that legitimate requests with valid authorization token succeed."""
    token = get_local_session_token()

    # Via Bearer header
    res1 = unauth_client.post(
        "/api/calendar/availability",
        json={"days_ahead": 3},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res1.status_code == 200
    assert res1.json()["status"] == "SUCCESS"

    # Via X-Aura-Session-Token header
    res2 = unauth_client.post(
        "/api/calendar/availability",
        json={"days_ahead": 3},
        headers={"X-Aura-Session-Token": token}
    )
    assert res2.status_code == 200


def test_server_rendered_html_injects_token_for_same_origin():
    """
    Verifies that server-rendered same-origin HTML pages (/ and /add-in/taskpane.html)
    contain the injected session token runtime configuration.
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


# --- 6. OAuth Special Endpoints & Public Assets ---

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


# --- 7. Adversarial Verification Tests (Step 7 Requirements) ---

def test_credential_discovery_through_all_public_endpoints():
    """
    STEP 7.C ADVERSARIAL TEST:
    Attempts to discover or scrape the privileged session credential through all
    public read-only JSON API endpoints.
    Expected: No privileged credential or unmasked secret is disclosed.
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
    ]
    for endpoint in public_endpoints:
        res = unauth_client.get(endpoint)
        assert res.status_code == 200, f"Public endpoint {endpoint} failed to return 200"
        body_text = res.text
        # Assert active token is NEVER returned in any JSON response
        assert token not in body_text, f"Token disclosed in response from {endpoint}!"
        # Assert raw unmasked secrets are not disclosed
        assert "AURA_SESSION_TOKEN" not in body_text


def test_forged_browser_metadata_alone_does_not_authorize():
    """
    STEP 7.D ADVERSARIAL TEST:
    Attempts privileged requests presenting forged browser metadata (Origin, Referer, User-Agent).
    These values alone must NOT confer privileged authorization.
    """
    forged_headers = {
        "Origin": "https://localhost:8000",
        "Referer": "https://localhost:8000/",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    privileged_targets = [
        ("/api/settings", {"demo_mode": True}),
        ("/api/emails/sync", {}),
        ("/api/daemon/run-now", {}),
        ("/api/calendar/availability", {}),
        ("/api/emails/test_id/send-reply", {"reply_body": "test"}),
    ]
    for path, payload in privileged_targets:
        res = unauth_client.post(path, json=payload, headers=forged_headers)
        assert res.status_code == 401, f"Forged metadata allowed unauthorized access to {path}"
        assert "Authentication required" in res.json().get("detail", "")


def test_null_origin_cannot_access_privileged_endpoints():
    """
    STEP 7.E ADVERSARIAL TEST:
    Verifies that requests presenting 'Origin: null' cannot access privileged endpoints.
    """
    headers = {
        "Origin": "null",
        "Referer": "",
        "User-Agent": "Mozilla/5.0 (Sandboxed Frame)",
    }
    res = unauth_client.post("/api/calendar/availability", json={}, headers=headers)
    assert res.status_code == 401
    assert "Authentication required" in res.json().get("detail", "")


def test_unauthenticated_upload_resume_rejected():
    """Verifies that multipart file upload to /api/profile/upload-resume rejects unauthenticated callers."""
    import io
    fake_file = io.BytesIO(b"Fake resume content")
    response = unauth_client.post(
        "/api/profile/upload-resume",
        files={"file": ("test_resume.docx", fake_file, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
    )
    assert response.status_code == 401
    assert "Authentication required" in response.json().get("detail", "")

