"""
Unit and Integration Tests for Localhost API Trust Boundary & Auth Hardening (Phase 2).
Verifies CORS allowlist enforcement, request authorization requirements on privileged
endpoints, malformed authorization rejection, and OAuth exemption handling.
"""

import pytest
from fastapi.testclient import TestClient
from backend.main import app, ALLOWED_ORIGINS
from backend.auth import (
    get_local_session_token,
    get_auth_headers,
    verify_local_token,
    reset_local_session_token
)

# Unauthenticated client
unauth_client = TestClient(app)

# Authenticated client
auth_client = TestClient(app)
auth_client.headers.update(get_auth_headers())


# --- CORS Security Tests ---

def test_cors_wildcard_removed():
    """Verifies that allow_origins=['*'] wildcard is completely removed."""
    assert "*" not in ALLOWED_ORIGINS
    assert len(ALLOWED_ORIGINS) > 0


def test_cors_approved_origins_accepted():
    """Verifies that legitimate localhost, 127.0.0.1, and Outlook add-in origins are permitted."""
    approved_origins = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://outlook.office.com",
        "https://outlook.office365.com",
        "https://appsforoffice.microsoft.com",
        "null"
    ]
    for origin in approved_origins:
        response = unauth_client.options(
            "/api/status",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        # FastApi CORSMiddleware returns 200 on preflight for allowed origins
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == origin


def test_cors_unknown_origins_rejected():
    """Verifies that unauthorized or malicious origins are rejected by CORS."""
    malicious_origins = [
        "https://evil-attacker.com",
        "http://malicious-site.org",
        "https://phishing-aura.net",
        "http://attacker.local:9999"
    ]
    for origin in malicious_origins:
        response = unauth_client.options(
            "/api/status",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        # Unauthorized origin does not receive Access-Control-Allow-Origin matching its origin
        assert response.headers.get("access-control-allow-origin") != origin


# --- Request Authorization on Privileged Endpoints ---

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
    ("/api/auth/submit-code", {"code": "123"}),
    ("/api/auth/google/submit-code", {"code": "123"}),
    ("/api/auth/imap", {"email": "a@b.com", "imap_server": "mail.example.com"}),
]


@pytest.mark.parametrize("path,payload", PRIVILEGED_POST_ENDPOINTS)
def test_privileged_endpoints_reject_missing_authorization(path, payload):
    """
    SECURITY INVARIANT:
    Verifies that state-changing or privileged operations require authorization
    and reject unauthenticated requests with 401 Unauthorized.
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
    """Verifies that incorrect / forged tokens fail with 403 Forbidden."""
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


def test_session_token_bootstrap_and_authenticated_request_success():
    """
    Verifies that the legitimate local frontend / add-in can bootstrap its
    session token from /api/auth/session and successfully invoke protected endpoints.
    """
    # 1. Bootstrap session token
    session_res = unauth_client.get("/api/auth/session")
    assert session_res.status_code == 200
    data = session_res.json()
    assert data["status"] == "SUCCESS"
    token = data["session_token"]
    assert len(token) >= 32

    # 2. Invoke privileged endpoint using Bearer token
    avail_res = unauth_client.post(
        "/api/calendar/availability",
        json={"days_ahead": 3},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert avail_res.status_code == 200
    assert avail_res.json()["status"] == "SUCCESS"

    # 3. Invoke privileged endpoint using X-Aura-Session-Token
    avail_res2 = unauth_client.post(
        "/api/calendar/availability",
        json={"days_ahead": 3},
        headers={"X-Aura-Session-Token": token}
    )
    assert avail_res2.status_code == 200


def test_oauth_endpoints_remain_accessible_without_bearer_token():
    """
    Verifies that external OAuth redirect callbacks and URL generation endpoints
    remain accessible to top-level browser identity flows without requiring Bearer headers.
    """
    # MSAL OAuth URL
    msal_url_res = unauth_client.get("/api/auth/msal/url")
    assert msal_url_res.status_code in [200, 400]  # 400 only if client ID not configured, but NOT 401/403

    # Google OAuth URL
    google_url_res = unauth_client.get("/api/auth/google/url")
    assert google_url_res.status_code in [200, 400]  # 400 only if client ID not configured, but NOT 401/403

    # MSAL OAuth Callback (browser redirect)
    msal_cb_res = unauth_client.get("/api/auth/callback?error=access_denied", follow_redirects=False)
    assert msal_cb_res.status_code == 307  # Redirects to /?auth_error=access_denied

    # Google OAuth Callback (browser redirect)
    google_cb_res = unauth_client.get("/api/auth/google/callback?error=access_denied", follow_redirects=False)
    assert google_cb_res.status_code == 307  # Redirects to /?auth_error=access_denied


def test_read_only_and_static_routes_remain_accessible():
    """Verifies that public system status, safety policy, and static assets remain accessible."""
    assert unauth_client.get("/api/status").status_code == 200
    assert unauth_client.get("/api/safety-policy").status_code == 200
    assert unauth_client.get("/add-in/taskpane.html").status_code == 200
    assert unauth_client.get("/static/icon-64.png").status_code == 200
