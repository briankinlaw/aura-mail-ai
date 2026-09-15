"""
Aura Mail AI - Phase 6 Approved Local-Desktop Threat-Model Enforcement Test Suite.

Comprehensive adversarial and regression tests covering:
A. Threat-model documentation and boundary statements.
B. Loopback peer socket enforcement & anti-spoofing.
C. Strict Host header validation.
D. Canonical immutable CORS origin policy.
E. Server-side browser context and Fetch Metadata verification.
F. Multi-header credential parsing and conflict rejection.
G. OAuth state transaction lifecycle (entropy, binding, TTL, replay defense, atomicity).
H. Strict canonical redirect URI enforcement.
I. FastAPI route table authorization inventory and public route allowlist.
J. Token-bearing response cache & security headers.
K. Inherited Phase 5 grounding, recovery, and transmission invariants.
Adversarial Matrix: 11-row matrix verifying handler side-effect prevention across peer/host/origin/auth permutations.
"""

import os
import time
import inspect
import threading
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from starlette.testclient import TestClient

from backend.main import app, ALLOWED_HOSTS
from backend.auth import (
    ALLOWED_ORIGINS,
    get_local_session_token,
    get_auth_headers,
    reset_local_session_token,
    verify_local_token,
    LoopbackPeerMiddleware,
)
from backend.oauth_state import (
    OAuthStateManager,
    OAUTH_STATE_MANAGER,
    OAUTH_STATE_LIFETIME_SECONDS,
    MAX_ACTIVE_OAUTH_STATES,
)
from backend.config import CANONICAL_ORIGIN, GRAPH_SCOPES
from backend.providers.gmail import GMAIL_SCOPES

CANONICAL_HEADERS = {
    "Authorization": f"Bearer {get_local_session_token()}",
    "Origin": "https://localhost:8000",
}


# ==============================================================================
# A. THREAT-MODEL DOCUMENTATION & BOUNDARY STATEMENTS
# ==============================================================================

def test_section_a_threat_model_documentation_invariants():
    """
    Verifies that THREAT_MODEL.md exists and accurately details the approved
    local-desktop threat model without overstating protections.
    """
    doc_path = Path(__file__).resolve().parent.parent.parent / "THREAT_MODEL.md"
    assert doc_path.is_file(), "THREAT_MODEL.md must exist in the repository root"
    content = doc_path.read_text(encoding="utf-8")

    # In-scope threats documented
    assert "In-Scope Threats" in content
    assert "malicious website" in content.lower()
    assert "cross-origin" in content.lower()
    assert "csrf" in content.lower()
    assert "dns rebinding" in content.lower()
    assert "loopback" in content.lower()

    # Out-of-scope boundaries accurately stated
    assert "Out-of-Scope Threats" in content
    assert "same-user" in content.lower() or "same user" in content.lower()
    assert "xss" in content.lower()
    assert "root" in content.lower()

    # Critical security truth statements
    assert "CORS is Not Authentication" in content or "cors is not authentication" in content.lower()
    assert "Session Token is Not an OS Boundary" in content or "not an operating-system" in content.lower()
    assert "Offline Recovery is a Separate Boundary" in content or "offline recovery" in content.lower()


# ==============================================================================
# B. LOOPBACK PEER ENFORCEMENT & ANTI-SPOOFING (FINDING B)
# ==============================================================================

def test_section_b_loopback_peer_ipv4_and_ipv6_accepted():
    """Verifies that IPv4 and IPv6 loopback socket peers are accepted."""
    loopback_peers = [
        ("127.0.0.1", 50000),
        ("127.0.0.2", 50001),
        ("127.1.2.3", 50002),
        ("::1", 50000),
    ]
    for peer in loopback_peers:
        client = TestClient(app, base_url="https://localhost:8000", client=peer)
        res = client.get("/api/safety-policy")
        assert res.status_code == 200, f"Loopback peer {peer} should be accepted"


def test_section_b_loopback_peer_non_loopback_rejected():
    """Verifies that private LAN, link-local, public, and malformed peers are rejected."""
    rejected_peers = [
        ("192.168.1.50", 50000),
        ("10.0.0.25", 50000),
        ("172.16.0.1", 50000),
        ("169.254.1.1", 50000),
        ("8.8.8.8", 50000),
        ("1.1.1.1", 50000),
        ("evil.com", 50000),
        ("localhost", 50000),
        ("not-an-ip", 50000),
    ]
    for peer in rejected_peers:
        client = TestClient(app, base_url="https://localhost:8000", client=peer)
        res = client.get("/api/safety-policy")
        assert res.status_code == 403, f"Non-loopback peer {peer} must be rejected with 403"
        assert "Non-loopback peer address rejected" in res.text or "rejected" in res.text


def test_section_b_loopback_peer_forwarded_headers_cannot_spoof_origin():
    """Verifies that X-Forwarded-For or Forwarded headers cannot bypass peer validation."""
    client = TestClient(app, base_url="https://localhost:8000", client=("192.168.1.100", 50000))
    spoofed_headers = [
        {"X-Forwarded-For": "127.0.0.1"},
        {"X-Forwarded-For": "::1"},
        {"Forwarded": "for=127.0.0.1;proto=https"},
        {"X-Real-IP": "127.0.0.1"},
    ]
    for h in spoofed_headers:
        res = client.get("/api/safety-policy", headers=h)
        assert res.status_code == 403, f"Spoofed header {h} must not bypass peer enforcement"


def test_section_b_remote_preflight_rejections_and_peer_enforcement():
    """
    SECTION 7.5: Remote preflight tests with explicit ASGI client peer identities.
    Proves that OPTIONS requests from non-loopback, malformed, or missing peers are
    rejected by peer enforcement (403) before CORS can process them.
    """
    remote_peers = [
        ("192.168.1.50", 50000),
        ("10.0.0.25", 50000),
        ("169.254.1.1", 50000),
        ("8.8.8.8", 50000),
        ("evil.com", 50000),
        ("not-an-ip", 50000),
        None,  # Missing peer
    ]

    origin_variations = [
        [("Origin", "https://localhost:8000"), ("Access-Control-Request-Method", "GET")],
        [("Origin", "https://evil.example"), ("Access-Control-Request-Method", "GET")],
        [("Origin", "null"), ("Access-Control-Request-Method", "GET")],
        [("Access-Control-Request-Method", "GET")],  # Missing Origin
    ]

    for peer in remote_peers:
        client = TestClient(app, base_url="https://localhost:8000", client=peer)
        for headers_list in origin_variations:
            res = client.options("/api/safety-policy", headers=headers_list)
            assert res.status_code == 403, (
                f"Remote preflight from peer={peer} with headers={headers_list} "
                f"must be rejected with 403 by peer enforcement, got {res.status_code}"
            )
            assert "Access forbidden" in res.text

            # Also verify spoofed forwarding headers cannot bypass peer enforcement on preflights
            spoofed_headers = list(headers_list) + [("X-Forwarded-For", "127.0.0.1"), ("Forwarded", "for=127.0.0.1")]
            res_spoofed = client.options("/api/safety-policy", headers=spoofed_headers)
            assert res_spoofed.status_code == 403, f"Spoofed preflight from peer={peer} must return 403"


def test_section_b_middleware_order_regression_proves_loopback_outermost():
    """
    SECTION 7.8: Middleware order regression test.
    Behaviorally proves LoopbackPeerMiddleware is outermost and executes before CORSMiddleware.
    If CORSMiddleware executed first, a canonical-origin preflight from a remote peer
    would return 200 OK with Access-Control-Allow-Origin: https://localhost:8000.
    Under correct ordering, LoopbackPeerMiddleware returns 403 immediately.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("192.168.1.5", 50000))
    res = client.options(
        "/api/safety-policy",
        headers=[
            ("Origin", "https://localhost:8000"),
            ("Access-Control-Request-Method", "GET"),
            ("Host", "localhost")
        ]
    )
    assert res.status_code == 403, f"Outer middleware must reject remote preflight before CORS, got {res.status_code}"
    assert "Non-loopback peer address rejected" in res.text
    assert "access-control-allow-origin" not in res.headers


# ==============================================================================
# C. STRICT HOST VALIDATION
# ==============================================================================

def test_section_c_strict_host_validation_accepted():
    """Verifies that exactly approved loopback hosts (localhost, 127.0.0.1) are accepted."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    for host in ["localhost", "127.0.0.1", "localhost:8000", "127.0.0.1:8000"]:
        res = client.get("/api/safety-policy", headers={"Host": host})
        assert res.status_code == 200, f"Host {host} should be accepted"


def test_section_c_strict_host_validation_rejected():
    """Verifies that wildcard localhost, testserver, DNS rebinding, and lookalikes are rejected."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    rejected_hosts = [
        "evil.example",
        "localhost.evil.example",
        "evil.localhost",
        "foo.localhost",
        "localhost.example",
        "127.0.0.1.evil.example",
        "192.168.1.50",
        "10.0.0.25",
        "testserver",
        "testserver:8000",
        "localhost.attacker.com",
    ]
    for host in rejected_hosts:
        res = client.get("/api/safety-policy", headers={"Host": host})
        assert res.status_code == 400, f"Host {host} must be rejected by TrustedHostMiddleware"
        assert "Invalid host header" in res.text


def test_section_c_duplicate_host_rejected():
    """
    Verifies that repeated Host headers (RFC 9112 Section 7.2) are rejected with 400 Bad Request
    before downstream host or routing processing.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    duplicate_host_cases = [
        [("Host", "localhost"), ("Host", "evil.com")],
        [("Host", "evil.com"), ("Host", "localhost")],
        [("Host", "localhost"), ("Host", "localhost")],
        [("Host", "127.0.0.1"), ("Host", "127.0.0.1")],
    ]
    for headers_list in duplicate_host_cases:
        res = client.get("/api/safety-policy", headers=headers_list)
        assert res.status_code == 400, f"Duplicate Host headers {headers_list} must return 400"
        assert "Invalid host header" in res.text


# ==============================================================================
# D. IMMUTABLE CANONICAL CORS & PREFLIGHT
# ==============================================================================

def test_section_d_cors_immutable_canonical_origin():
    """Verifies that production CORS allowlist is strictly ['https://localhost:8000']."""
    assert ALLOWED_ORIGINS == ["https://localhost:8000"]
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    # Preflight from canonical origin succeeds
    res = client.options(
        "/api/safety-policy",
        headers={
            "Origin": "https://localhost:8000",
            "Access-Control-Request-Method": "GET"
        }
    )
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == "https://localhost:8000"

    # All non-canonical origins rejected
    rejected_origins = [
        "*",
        "null",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "https://127.0.0.1:8000",
        "http://localhost:3000",
        "https://localhost:3000",
        "https://evil.example",
        "https://outlook.office.com",
        "https://outlook.office365.com",
    ]
    for origin in rejected_origins:
        res = client.options(
            "/api/safety-policy",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET"
            }
        )
        assert res.headers.get("access-control-allow-origin") != origin


def test_section_d_accepted_loopback_preflight_regression():
    """
    SECTION 7.6: Accepted preflight regression.
    Proves that legitimate loopback peers (127.0.0.1 and ::1) can perform canonical preflights.
    """
    loopback_peers = [("127.0.0.1", 50000), ("::1", 50000)]
    methods = ["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD"]

    for peer in loopback_peers:
        client = TestClient(app, base_url="https://localhost:8000", client=peer)
        for method in methods:
            res = client.options(
                "/api/safety-policy",
                headers=[
                    ("Host", "localhost"),
                    ("Origin", "https://localhost:8000"),
                    ("Access-Control-Request-Method", method)
                ]
            )
            assert res.status_code == 200, f"Preflight for {method} from peer {peer} failed: {res.status_code}"
            assert res.headers.get("access-control-allow-origin") == "https://localhost:8000"


# ==============================================================================
# E. SERVER-SIDE BROWSER CONTEXT & FETCH METADATA (FINDING A)
# ==============================================================================

def test_section_e_server_side_origin_verification():
    """Verifies that privileged endpoints reject unauthorized/null Origin even with a valid token."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # Valid token + unauthorized Origin -> 403
    unauthorized_origins = [
        "https://evil.example",
        "null",
        "http://localhost:8000",
        "https://127.0.0.1:8000",
        "https://localhost:8000.attacker.com",
    ]
    for origin in unauthorized_origins:
        res = client.get(
            "/api/status",
            headers={
                "Authorization": f"Bearer {token}",
                "Origin": origin
            }
        )
        assert res.status_code == 403
        assert "Origin verification failed" in res.json().get("detail", "")


def test_section_e_actual_duplicate_origin_rejections():
    """
    SECTION 7.3: Actual duplicate Origin tests using raw header lists.
    Tests both orders and malformed/repeated representations.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    duplicate_origin_cases = [
        # (Header tuples, description)
        ([("Origin", "https://localhost:8000"), ("Origin", "https://evil.example")], "canonical then evil"),
        ([("Origin", "https://evil.example"), ("Origin", "https://localhost:8000")], "evil then canonical"),
        ([("Origin", "https://localhost:8000"), ("Origin", "https://localhost:8000")], "two canonical origins"),
        ([("Origin", "https://localhost:8000"), ("Origin", "null")], "canonical + null origin"),
        ([("Origin", "https://localhost:8000"), ("Origin", "")], "canonical + empty origin"),
        ([("Origin", "https://localhost:8000, https://evil.example")], "comma-joined origin"),
        ([("Origin", " https://localhost:8000 ")], "whitespace-obfuscated origin"),
        ([("Origin", "https://localhost:8000@evil.com")], "userinfo spoofed origin"),
    ]

    for headers_tuples, desc in duplicate_origin_cases:
        full_headers = [("Host", "localhost"), ("Authorization", f"Bearer {token}")] + headers_tuples
        res = client.get("/api/status", headers=full_headers)
        assert res.status_code == 403, f"Duplicate Origin case '{desc}' expected 403, got {res.status_code}"
        assert "Origin verification failed" in res.json().get("detail", "")


def test_section_e_fetch_metadata_cross_site_rejected():
    """Verifies that Sec-Fetch-Site: cross-site is rejected."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # Sec-Fetch-Site: cross-site rejected even with canonical Origin and valid token
    res = client.get(
        "/api/status",
        headers={
            "Authorization": f"Bearer {token}",
            "Origin": "https://localhost:8000",
            "Sec-Fetch-Site": "cross-site",
        }
    )
    assert res.status_code == 403
    assert "Browser context verification failed" in res.json().get("detail", "")


def test_section_e_fetch_metadata_ambiguity_and_conflict_rejections():
    """
    SECTION 7.4: Fetch Metadata ambiguity and conflict tests.
    Verifies duplicate, empty, comma-joined, and conflicting Sec-Fetch-Site fields fail closed.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    sec_fetch_cases = [
        ([("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "same-origin")], "two Sec-Fetch-Site fields"),
        ([("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")], "same-origin + cross-site duplicates"),
        ([("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "same-origin")], "cross-site + same-origin duplicates"),
        ([("Sec-Fetch-Site", "")], "empty Sec-Fetch-Site"),
        ([("Sec-Fetch-Site", "   ")], "whitespace Sec-Fetch-Site"),
        ([("Sec-Fetch-Site", "same-origin,cross-site")], "comma-joined Sec-Fetch-Site"),
        ([("Sec-Fetch-Site", "invalid-value")], "unrecognized Sec-Fetch-Site"),
        ([("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")], "canonical Origin + cross-site"),
    ]

    for headers_tuples, desc in sec_fetch_cases:
        full_headers = [("Host", "localhost"), ("Authorization", f"Bearer {token}")] + headers_tuples
        res = client.get("/api/status", headers=full_headers)
        assert res.status_code == 403, f"Sec-Fetch-Site case '{desc}' expected 403, got {res.status_code}"
        assert "Browser context verification failed" in res.json().get("detail", "")


def test_section_e_authenticated_non_browser_loopback_accepted():
    """Verifies that authenticated non-browser requests without Origin header succeed."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    res = client.get(
        "/api/status",
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert "status" in res.json()


# ==============================================================================
# F. CREDENTIAL PARSING & CONFLICT REJECTION (FINDING A)
# ==============================================================================

def test_section_f_credential_parsing_rejections():
    """Verifies rejection of missing, empty, malformed, unsupported, or conflicting credentials."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    valid_token = get_local_session_token()
    wrong_token = "0" * 64

    # 1. Missing credentials -> 401
    res = client.get("/api/status")
    assert res.status_code == 401

    # 2. Empty Bearer -> 403
    res = client.get("/api/status", headers={"Authorization": "Bearer "})
    assert res.status_code == 403

    # 3. Malformed scheme -> 403
    res = client.get("/api/status", headers={"Authorization": f"Basic {valid_token}"})
    assert res.status_code == 403

    # 4. Invalid token -> 403
    res = client.get("/api/status", headers={"Authorization": f"Bearer {wrong_token}"})
    assert res.status_code == 403

    # 5. Comma-joined / duplicate tokens in Bearer -> 403
    res = client.get("/api/status", headers={"Authorization": f"Bearer {valid_token},{valid_token}"})
    assert res.status_code == 403

    # 6. Malformed Authorization paired with valid X-Aura-Session-Token -> 403 (fail closed)
    res = client.get(
        "/api/status",
        headers={
            "Authorization": "Basic invalid",
            "X-Aura-Session-Token": valid_token,
        }
    )
    assert res.status_code == 403

    # 7. Conflicting credential headers -> 403
    res = client.get(
        "/api/status",
        headers={
            "Authorization": f"Bearer {valid_token}",
            "X-Aura-Session-Token": wrong_token,
        }
    )
    assert res.status_code == 403
    assert "Conflicting credential headers" in res.json().get("detail", "")

    # 8. Identical valid credential headers -> 200
    res = client.get(
        "/api/status",
        headers={
            "Authorization": f"Bearer {valid_token}",
            "X-Aura-Session-Token": valid_token,
        }
    )
    assert res.status_code == 200


def test_section_f_actual_duplicate_credential_rejections():
    """
    SECTION 7.1: Actual duplicate credential tests using ordered header tuples.
    Verifies that duplicate occurrences of the same credential header name are
    rejected even when both values are identical.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    valid_tok = get_local_session_token()
    wrong_tok = "0" * 64

    duplicate_credential_cases = [
        # Authorization duplicates
        ([("Authorization", f"Bearer {valid_tok}"), ("Authorization", f"Bearer {wrong_tok}")], "Auth valid + Auth invalid"),
        ([("Authorization", f"Bearer {wrong_tok}"), ("Authorization", f"Bearer {valid_tok}")], "Auth invalid + Auth valid"),
        ([("Authorization", f"Bearer {valid_tok}"), ("Authorization", f"Bearer {valid_tok}")], "Auth valid + Auth valid (identical)"),
        ([("Authorization", ""), ("Authorization", f"Bearer {valid_tok}")], "Auth empty + Auth valid"),
        ([("Authorization", f"Bearer {valid_tok}"), ("Authorization", "")], "Auth valid + Auth empty"),
        ([("Authorization", f"Bearer {valid_tok}"), ("Authorization", f"Basic {valid_tok}")], "Auth Bearer + Auth Basic"),

        # X-Aura-Session-Token duplicates
        ([("X-Aura-Session-Token", valid_tok), ("X-Aura-Session-Token", wrong_tok)], "SessionToken valid + SessionToken invalid"),
        ([("X-Aura-Session-Token", wrong_tok), ("X-Aura-Session-Token", valid_tok)], "SessionToken invalid + SessionToken valid"),
        ([("X-Aura-Session-Token", valid_tok), ("X-Aura-Session-Token", valid_tok)], "SessionToken valid + SessionToken valid (identical)"),
        ([("X-Aura-Session-Token", ""), ("X-Aura-Session-Token", valid_tok)], "SessionToken empty + SessionToken valid"),
        ([("X-Aura-Session-Token", valid_tok), ("X-Aura-Session-Token", "")], "SessionToken valid + SessionToken empty"),

        # X-Aura-Token duplicates
        ([("X-Aura-Token", valid_tok), ("X-Aura-Token", wrong_tok)], "XToken valid + XToken invalid"),
        ([("X-Aura-Token", wrong_tok), ("X-Aura-Token", valid_tok)], "XToken invalid + XToken valid"),
        ([("X-Aura-Token", valid_tok), ("X-Aura-Token", valid_tok)], "XToken valid + XToken valid (identical)"),
        ([("X-Aura-Token", ""), ("X-Aura-Token", valid_tok)], "XToken empty + XToken valid"),
        ([("X-Aura-Token", valid_tok), ("X-Aura-Token", "")], "XToken valid + XToken empty"),
    ]

    for headers_tuples, desc in duplicate_credential_cases:
        full_headers = [("Host", "localhost")] + headers_tuples
        res = client.get("/api/status", headers=full_headers)
        assert res.status_code == 403, f"Duplicate credential case '{desc}' expected 403, got {res.status_code}"
        assert "Authentication failed" in res.json().get("detail", "")


def test_section_f_cross_mechanism_credential_rules():
    """
    SECTION 7.2: Cross-mechanism credential rules.
    Tests simultaneous presentation of distinct headers, conflict rejection, and compatibility policy.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    valid_tok = get_local_session_token()
    wrong_tok = "0" * 64

    # 1. Authorization valid + X-Aura-Session-Token same valid value -> 200 (documented compatibility)
    res1 = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {valid_tok}"),
            ("X-Aura-Session-Token", valid_tok),
        ]
    )
    assert res1.status_code == 200

    # 2. Authorization valid + X-Aura-Session-Token conflicting value -> 403
    res2 = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {valid_tok}"),
            ("X-Aura-Session-Token", wrong_tok),
        ]
    )
    assert res2.status_code == 403
    assert "Conflicting credential headers" in res2.json().get("detail", "")

    # 3. Authorization malformed + X-Aura-Session-Token valid -> 403 (fail closed)
    res3 = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Basic {valid_tok}"),
            ("X-Aura-Session-Token", valid_tok),
        ]
    )
    assert res3.status_code == 403

    # 4. Authorization valid + X-Aura-Token conflicting value -> 403
    res4 = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {valid_tok}"),
            ("X-Aura-Token", wrong_tok),
        ]
    )
    assert res4.status_code == 403
    assert "Conflicting credential headers" in res4.json().get("detail", "")

    # 5. All three mechanisms present and identical -> 200
    res5 = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {valid_tok}"),
            ("X-Aura-Session-Token", valid_tok),
            ("X-Aura-Token", valid_tok),
        ]
    )
    assert res5.status_code == 200

    # 6. All three mechanisms present with one conflict -> 403
    res6 = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {valid_tok}"),
            ("X-Aura-Session-Token", valid_tok),
            ("X-Aura-Token", wrong_tok),
        ]
    )
    assert res6.status_code == 403
    assert "Conflicting credential headers" in res6.json().get("detail", "")


def test_section_f_side_effect_prevention_on_mutating_settings():
    """
    SECTION 7.7: Side-effect prevention on state-mutating POST /api/settings route.
    Proves that rejected duplicate, malformed, conflicting, remote-peer, Host, Origin,
    or Fetch Metadata requests never invoke the mutation handler save_settings.
    """
    valid_tok = get_local_session_token()
    wrong_tok = "0" * 64

    mutation_cases = [
        # (Peer, Headers tuples, expected_status, description)
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Authorization", f"Bearer {wrong_tok}")], 403, "Duplicate Authorization"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Authorization", f"Bearer {valid_tok}")], 403, "Identical duplicate Authorization"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Origin", "https://localhost:8000"), ("Origin", "https://evil.example")], 403, "Duplicate Origin (canonical + evil)"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Origin", "https://evil.example"), ("Origin", "https://localhost:8000")], 403, "Duplicate Origin (evil + canonical)"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Origin", "https://localhost:8000"), ("Origin", "https://localhost:8000")], 403, "Duplicate canonical Origin"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Origin", "https://evil.example")], 403, "Hostile Origin"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Sec-Fetch-Site", "cross-site")], 403, "Sec-Fetch-Site cross-site"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")], 403, "Duplicate Sec-Fetch-Site"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}"), ("X-Aura-Session-Token", wrong_tok)], 403, "Conflicting session token"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Authorization", "Bearer ")], 403, "Empty Bearer token"),
        (("127.0.0.1", 50000), [("Host", "localhost")], 401, "Missing credential"),
        (("127.0.0.1", 50000), [("Host", "localhost"), ("Host", "evil.com"), ("Authorization", f"Bearer {valid_tok}")], 400, "Duplicate Host"),
        (("127.0.0.1", 50000), [("Host", "evil.example"), ("Authorization", f"Bearer {valid_tok}")], 400, "Untrusted Host"),
        (("192.168.1.50", 50000), [("Host", "localhost"), ("Authorization", f"Bearer {valid_tok}")], 403, "Remote socket peer"),
    ]

    for peer, headers_tuples, expected_status, desc in mutation_cases:
        client = TestClient(app, base_url="https://localhost:8000", client=peer)
        with patch("backend.main.save_settings") as mock_save:
            res = client.post(
                "/api/settings",
                json={"ai_provider": "GEMINI"},
                headers=headers_tuples
            )
            assert res.status_code == expected_status, f"Mutation case '{desc}' expected status {expected_status}, got {res.status_code}"
            assert not mock_save.called, f"Mutation handler save_settings MUST NOT be called for case '{desc}'"


# ==============================================================================
# G. OAUTH STATE TRANSACTIONS & LIFECYCLE
# ==============================================================================

def test_section_g_oauth_state_manager_unit_lifecycle():
    """Unit tests for OAuthStateManager verifying entropy, bindings, TTL, single-use, replay, capacity."""
    mock_clock = [1000.0]
    manager = OAuthStateManager(lifetime_seconds=300, max_entries=5, time_func=lambda: mock_clock[0])

    # 1. State creation generates distinct high-entropy tokens
    s1 = manager.create_state(provider="MICROSOFT_GRAPH", redirect_uri="https://localhost:8000/api/auth/callback")
    s2 = manager.create_state(provider="GMAIL", redirect_uri="https://localhost:8000/api/auth/google/callback", account_id="user@gmail.com")
    assert s1 != s2
    assert len(s1) >= 32

    # 2. Purpose binding: MSAL state fails when consumed as GMAIL
    s_wrong = manager.create_state(provider="MICROSOFT_GRAPH", redirect_uri="https://localhost:8000/api/auth/callback")
    assert manager.validate_and_consume(s_wrong, expected_provider="GMAIL") is None

    # 3. Correct consumption works and returns record
    rec1 = manager.validate_and_consume(s1, expected_provider="MICROSOFT_GRAPH", expected_redirect_uri="https://localhost:8000/api/auth/callback")
    assert rec1 is not None
    assert rec1.provider == "MICROSOFT_GRAPH"

    # 4. Replay rejected (consumed state cannot be used again)
    assert manager.validate_and_consume(s1, expected_provider="MICROSOFT_GRAPH") is None

    # 5. Expiration handling
    s3 = manager.create_state(provider="MICROSOFT_GRAPH", redirect_uri="https://localhost:8000/api/auth/callback")
    mock_clock[0] += 301.0  # Advance past 300s TTL
    assert manager.validate_and_consume(s3, expected_provider="MICROSOFT_GRAPH") is None

    # 6. Bounded capacity enforcement
    manager.reset()
    for i in range(5):
        manager.create_state(provider="MICROSOFT_GRAPH", redirect_uri="https://localhost:8000/api/auth/callback")
    with pytest.raises(RuntimeError, match="OAuth state capacity exceeded"):
        manager.create_state(provider="MICROSOFT_GRAPH", redirect_uri="https://localhost:8000/api/auth/callback")


def test_section_g_oauth_state_concurrent_consumption_race():
    """Verifies that simultaneous concurrent callback attempts allow exactly one successful exchange."""
    manager = OAuthStateManager(lifetime_seconds=300, max_entries=50)
    state = manager.create_state(provider="MICROSOFT_GRAPH", redirect_uri="https://localhost:8000/api/auth/callback")

    results = []

    def try_consume():
        rec = manager.validate_and_consume(state, expected_provider="MICROSOFT_GRAPH")
        results.append(rec is not None)

    threads = [threading.Thread(target=try_consume) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one thread must have succeeded
    assert results.count(True) == 1
    assert results.count(False) == 9


def test_section_g_oauth_initiation_and_callback_integration():
    """Integration test: OAuth initiation requires auth; callbacks require valid state."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # 1. Unauthenticated initiation fails
    assert client.get("/api/auth/msal/url").status_code == 401
    assert client.get("/api/auth/google/url").status_code == 401

    # 2. Authenticated initiation succeeds and creates server state
    with patch("backend.main.provider_manager.graph_provider.client_id", "mock-msal-client-id"), \
         patch("backend.main.provider_manager.gmail_provider.client_id", "mock-google-client-id"):
        res_msal = client.get("/api/auth/msal/url", headers={"Authorization": f"Bearer {token}"})
        assert res_msal.status_code == 200
        auth_url_msal = res_msal.json().get("auth_url", "")
        assert "state=" in auth_url_msal

        res_google = client.get("/api/auth/google/url", headers={"Authorization": f"Bearer {token}"})
        assert res_google.status_code == 200
        auth_url_google = res_google.json().get("auth_url", "")
        assert "state=" in auth_url_google

    # 3. Callback with missing or invalid state fails closed
    cb_invalid = client.get("/api/auth/callback?code=mock_code&state=forged_state", follow_redirects=False)
    assert cb_invalid.status_code == 307
    assert "auth_error=invalid_state" in cb_invalid.headers["location"]

    cb_invalid_g = client.get("/api/auth/google/callback?code=mock_code&state=forged_state", follow_redirects=False)
    assert cb_invalid_g.status_code == 307
    assert "auth_error=invalid_state" in cb_invalid_g.headers["location"]


# ==============================================================================
# H. STRICT CANONICAL REDIRECT URI ENFORCEMENT
# ==============================================================================

def test_section_h_canonical_redirect_uri_enforcement():
    """Verifies that OAuth initiation and code exchange strictly force canonical redirect URIs."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # Manual submit endpoints force canonical redirect URI
    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_graph_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_graph_ex.return_value = MagicMock(success=True, model_dump=lambda: {"success": True})
        client.post(
            "/api/auth/submit-code",
            json={"code": "mock_code", "redirect_uri": "https://attacker.example/cb"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert mock_graph_ex.called
        assert mock_graph_ex.call_args.kwargs["redirect_uri"] == "https://localhost:8000/api/auth/callback"

    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_gmail_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_gmail_ex.return_value = MagicMock(success=True, model_dump=lambda: {"success": True})
        client.post(
            "/api/auth/google/submit-code",
            json={"code": "mock_code", "redirect_uri": "https://attacker.example/cb"},
            headers={"Authorization": f"Bearer {token}"}
        )
        assert mock_gmail_ex.called
        assert mock_gmail_ex.call_args.kwargs["redirect_uri"] == "https://localhost:8000/api/auth/google/callback"


# ==============================================================================
# I. ROUTE AUTHORIZATION INVENTORY
# ==============================================================================

PUBLIC_ROUTE_ALLOWLIST = {
    ("/", "GET"),
    ("/", "HEAD"),
    ("/add-in/taskpane.html", "GET"),
    ("/add-in/taskpane.html", "HEAD"),
    ("/api/safety-policy", "GET"),
    ("/api/safety-policy", "HEAD"),
    ("/api/auth/callback", "GET"),
    ("/api/auth/callback", "HEAD"),
    ("/api/auth/google/callback", "GET"),
    ("/api/auth/google/callback", "HEAD"),
}

def test_section_i_route_authorization_inventory():
    """
    Inspects FastAPI route table and verifies every route outside the explicit
    public allowlist requires authentication.
    """
    for route in app.routes:
        if hasattr(route, "path") and hasattr(route, "methods"):
            path = route.path
            # Skip static mount points
            if path in ["/static", "/add-in"] or path.startswith("/static/") or path.startswith("/add-in/"):
                continue

            for method in route.methods:
                if method == "OPTIONS":
                    continue
                if (path, method) in PUBLIC_ROUTE_ALLOWLIST:
                    continue

                # Must have require_local_auth dependency
                endpoint = route.endpoint
                route_deps = getattr(route, "dependencies", []) or []
                dep_callables = [d.dependency for d in route_deps if hasattr(d, "dependency")]

                # Also check endpoint parameters
                sig = inspect.signature(endpoint)
                param_deps = [
                    param.default.dependency for param in sig.parameters.values()
                    if hasattr(param.default, "dependency")
                ]
                all_deps = dep_callables + param_deps

                from backend.auth import require_local_auth
                assert require_local_auth in all_deps, (
                    f"Route ({method} {path}) is not in PUBLIC_ROUTE_ALLOWLIST and lacks require_local_auth!"
                )


# ==============================================================================
# J. TOKEN-BEARING RESPONSE CONTROLS
# ==============================================================================

def test_section_j_token_bearing_response_security_headers():
    """Verifies that token-bearing HTML pages serve strict cache and framing headers."""
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    # 1. Index page
    res_index = client.get("/")
    assert res_index.status_code == 200
    assert res_index.headers["Cache-Control"] == "no-store, max-age=0"
    assert res_index.headers["Pragma"] == "no-cache"
    assert res_index.headers["Referrer-Policy"] == "no-referrer"
    assert res_index.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in res_index.headers["Content-Security-Policy"]

    # 2. Add-in taskpane page
    res_taskpane = client.get("/add-in/taskpane.html")
    assert res_taskpane.status_code == 200
    assert res_taskpane.headers["Cache-Control"] == "no-store, max-age=0"
    assert res_taskpane.headers["Pragma"] == "no-cache"
    assert res_taskpane.headers["Referrer-Policy"] == "no-referrer"
    assert res_taskpane.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'self' https://outlook.office.com" in res_taskpane.headers["Content-Security-Policy"]


# ==============================================================================
# K. INHERITED FROZEN CONTROLS PRESERVATION
# ==============================================================================

def test_section_k_inherited_frozen_controls_preservation():
    """
    Verifies that all Phase 5 safety, grounding, offline recovery, and transmission controls
    remain completely unchanged and intact.
    """
    from backend.offline_recovery import run_offline_recovery
    # Parameterless signature
    sig = inspect.signature(run_offline_recovery)
    assert len(sig.parameters) == 0

    # No send scopes
    assert "Mail.Send" not in GRAPH_SCOPES
    assert "https://www.googleapis.com/auth/gmail.send" not in GMAIL_SCOPES

    # No send endpoint
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    res = client.post(
        "/api/emails/123/authorize-send",
        json={"reply_body": "test"},
        headers={"Authorization": f"Bearer {get_local_session_token()}"}
    )
    assert res.status_code == 404


# ==============================================================================
# ADVERSARIAL MATRIX: 11-ROW PERMUTATION VERIFICATION
# ==============================================================================

ADVERSARIAL_MATRIX = [
    # (Peer, Host, Origin, Credential, Expected Status, Description)
    (("127.0.0.1", 50000), "localhost", "https://localhost:8000", "VALID", 200, "Canonical loopback browser"),
    (("127.0.0.1", 50000), "localhost", "https://evil.example", "VALID", 403, "Malicious browser origin"),
    (("127.0.0.1", 50000), "localhost", "null", "VALID", 403, "Opaque null origin"),
    (("127.0.0.1", 50000), "localhost", "https://localhost:8000", "MISSING", 401, "Missing credential"),
    (("127.0.0.1", 50000), "localhost", "https://localhost:8000", "INVALID", 403, "Invalid credential"),
    (("127.0.0.1", 50000), "evil.example", "https://localhost:8000", "VALID", 400, "Evil host header"),
    (("192.168.1.50", 50000), "localhost", "https://localhost:8000", "VALID", 403, "Remote socket peer"),
    (("192.168.1.50", 50000), "localhost", "https://evil.example", "VALID", 403, "Remote peer + evil origin"),
    (("192.168.1.50", 50000), "localhost", "https://localhost:8000", "SPOOFED_XFF", 403, "Remote peer + spoofed XFF"),
    (("127.0.0.1", 50000), "localhost", None, "VALID", 200, "Local non-browser tool/script"),
    (("127.0.0.1", 50000), "localhost", "https://localhost:8000", "CONFLICTING", 403, "Conflicting credential headers"),
]

@pytest.mark.parametrize("peer,host,origin,cred_mode,expected_status,desc", ADVERSARIAL_MATRIX)
def test_adversarial_matrix_and_side_effect_prevention(peer, host, origin, cred_mode, expected_status, desc):
    """
    Executes the 11-row adversarial matrix against a privileged state-mutating route
    and proves downstream provider actions are NEVER invoked upon rejection.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=peer)
    valid_tok = get_local_session_token()
    wrong_tok = "0" * 64

    headers = [("Host", host)]
    if origin is not None:
        headers.append(("Origin", origin))

    if cred_mode == "VALID":
        headers.append(("Authorization", f"Bearer {valid_tok}"))
    elif cred_mode == "INVALID":
        headers.append(("Authorization", f"Bearer {wrong_tok}"))
    elif cred_mode == "CONFLICTING":
        headers.append(("Authorization", f"Bearer {valid_tok}"))
        headers.append(("X-Aura-Session-Token", wrong_tok))
    elif cred_mode == "SPOOFED_XFF":
        headers.append(("Authorization", f"Bearer {valid_tok}"))
        headers.append(("X-Forwarded-For", "127.0.0.1"))

    from backend.models import EmailMessage
    fake_msg = EmailMessage(
        id="msg_123",
        subject="Adversarial Test",
        sender_name="Sender",
        sender_email="sender@example.com",
        body_text="Body"
    )

    with patch.dict("backend.main.CACHED_EMAILS", {"msg_123": fake_msg}, clear=False), \
         patch("backend.main.provider_manager.send_reply") as mock_send, \
         patch("backend.main.provider_manager.delete_message") as mock_del:
        mock_del.return_value = MagicMock(success=True)
        res = client.post("/api/emails/msg_123/trash", json={}, headers=headers)
        assert res.status_code == expected_status, f"Case '{desc}' expected {expected_status}, got {res.status_code}"

        # If rejected, handler side effects must be strictly prevented
        if expected_status != 200:
            assert not mock_send.called
            assert not mock_del.called
        else:
            assert mock_del.called


# ==============================================================================
# PHASE 6.2: PRE-CORS BROWSER-CONTEXT REMEDIATION TESTS (SECTIONS 9.1 - 9.7)
# ==============================================================================

def test_phase6_2_section_9_1_duplicate_origin_preflight_matrix():
    """
    SECTION 9.1: Loopback duplicate-Origin preflight matrix against representative
    privileged route OPTIONS /api/settings.
    Proves that all duplicate, conflicting, malformed, non-canonical, or lookalike Origin
    preflight requests are rejected with 403 before CORS processing, and that
    Access-Control-Allow-Origin / Access-Control-Allow-Credentials are completely absent.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    origin_matrix_cases = [
        # (Origin headers tuples, description)
        ([("Origin", "https://localhost:8000"), ("Origin", "https://evil.example")], "canonical then hostile"),
        ([("Origin", "https://evil.example"), ("Origin", "https://localhost:8000")], "hostile then canonical"),
        ([("Origin", "https://localhost:8000"), ("Origin", "https://localhost:8000")], "canonical then canonical"),
        ([("Origin", "https://localhost:8000"), ("Origin", "null")], "canonical then null"),
        ([("Origin", "null"), ("Origin", "https://localhost:8000")], "null then canonical"),
        ([("Origin", "https://localhost:8000"), ("Origin", "")], "canonical then empty"),
        ([("Origin", ""), ("Origin", "https://localhost:8000")], "empty then canonical"),
        ([("Origin", "https://localhost:8000, https://evil.example")], "one comma-joined canonical/hostile value"),
        ([("Origin", " https://localhost:8000 ")], "one whitespace-obfuscated canonical value"),
        ([("Origin", "*")], "one wildcard Origin"),
        ([("Origin", "http://localhost:8000")], "one HTTP localhost Origin"),
        ([("Origin", "https://127.0.0.1:8000")], "one 127.0.0.1 Origin"),
        ([("Origin", "https://localhost:3000")], "one alternate-port Origin"),
        ([("Origin", "https://user:pass@localhost:8000")], "one userinfo-bearing Origin"),
        ([("Origin", "https://localhost:8000.evil.example")], "one lookalike Origin"),
    ]

    for origin_headers, desc in origin_matrix_cases:
        full_headers = [
            ("Host", "localhost"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "Authorization"),
        ] + origin_headers

        res = client.options("/api/settings", headers=full_headers)
        assert res.status_code == 403, (
            f"Preflight duplicate/malformed Origin case '{desc}' expected 403, got {res.status_code}"
        )
        assert "access-control-allow-origin" not in res.headers, (
            f"Access-Control-Allow-Origin MUST NOT be emitted on rejection for '{desc}'"
        )
        assert "access-control-allow-credentials" not in res.headers, (
            f"Access-Control-Allow-Credentials MUST NOT be emitted on rejection for '{desc}'"
        )


def test_phase6_2_section_9_2_fetch_metadata_preflight_matrix():
    """
    SECTION 9.2: Loopback Fetch Metadata preflight matrix using exactly one canonical Origin.
    Proves that cross-site, duplicate, empty, whitespace-only, comma-joined, unrecognized,
    or mixed-case duplicate Sec-Fetch-Site preflight requests are rejected with 403 before CORS.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    fetch_metadata_cases = [
        # (Sec-Fetch-Site headers tuples, description)
        ([("Sec-Fetch-Site", "cross-site")], "cross-site"),
        ([("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")], "same-origin then cross-site"),
        ([("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "same-origin")], "cross-site then same-origin"),
        ([("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "same-origin")], "same-origin then same-origin"),
        ([("Sec-Fetch-Site", "")], "empty"),
        ([("Sec-Fetch-Site", "   ")], "whitespace-only"),
        ([("Sec-Fetch-Site", " same-origin ")], "leading/trailing whitespace"),
        ([("Sec-Fetch-Site", "same-origin,cross-site")], "comma-joined values"),
        ([("Sec-Fetch-Site", "invalid-value")], "unrecognized value"),
        ([("sec-fetch-site", "same-origin"), ("Sec-Fetch-Site", "same-origin")], "mixed-case duplicate header names"),
        ([("SEC-FETCH-SITE", "cross-site"), ("sec-fetch-site", "same-origin")], "mixed-case conflicting duplicate header names"),
    ]

    for fetch_headers, desc in fetch_metadata_cases:
        full_headers = [
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "Authorization"),
        ] + fetch_headers

        res = client.options("/api/settings", headers=full_headers)
        assert res.status_code == 403, (
            f"Preflight Fetch Metadata case '{desc}' expected 403, got {res.status_code}"
        )
        assert "access-control-allow-origin" not in res.headers, (
            f"Access-Control-Allow-Origin MUST NOT be returned on rejection for '{desc}'"
        )
        assert "access-control-allow-credentials" not in res.headers


def test_phase6_2_section_9_3_legitimate_preflight_regression():
    """
    SECTION 9.3: Legitimate preflight regression.
    Proves that legitimate preflights from 127.0.0.1 and ::1 succeed with 200 OK and
    emit Access-Control-Allow-Origin: https://localhost:8000 without requiring an
    Authorization header.
    """
    loopback_peers = [("127.0.0.1", 50000), ("::1", 50000)]
    methods = ["GET", "POST"]

    for peer in loopback_peers:
        client = TestClient(app, base_url="https://localhost:8000", client=peer)
        for method in methods:
            res = client.options(
                "/api/settings",
                headers=[
                    ("Host", "localhost"),
                    ("Origin", "https://localhost:8000"),
                    ("Sec-Fetch-Site", "same-origin"),
                    ("Access-Control-Request-Method", method),
                    ("Access-Control-Request-Headers", "Authorization"),
                ]
            )
            assert res.status_code == 200, f"Legitimate preflight for {method} from {peer} failed: {res.status_code}"
            assert res.headers.get("access-control-allow-origin") == "https://localhost:8000"
            assert "authorization" not in [k.lower() for k, _ in res.headers.raw]


def test_phase6_2_section_9_4_non_browser_regression():
    """
    SECTION 9.4: Non-browser regression.
    Proves that an authenticated loopback non-browser request with no Origin and no
    Sec-Fetch-Site headers still succeeds without requiring browser headers.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    res = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {token}"),
        ]
    )
    assert res.status_code == 200
    assert res.json().get("status") == "ONLINE"


def test_phase6_2_section_9_5_remote_preflight_regression():
    """
    SECTION 9.5: Remote preflight regression.
    Proves that remote peers are rejected by LoopbackPeerMiddleware before Host validation,
    browser-context validation, or CORS processing can occur.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("192.168.1.5", 50000))

    remote_origin_cases = [
        [("Origin", "https://localhost:8000")],
        [("Origin", "https://evil.example")],
        [("Origin", "null")],
        [("Origin", "https://localhost:8000"), ("Origin", "https://evil.example")],
        [],  # missing Origin
    ]

    for origins in remote_origin_cases:
        full_headers = [
            ("Host", "localhost"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "Authorization"),
        ] + origins

        res = client.options("/api/settings", headers=full_headers)
        assert res.status_code == 403, f"Remote preflight with {origins} expected 403, got {res.status_code}"
        assert "Non-loopback peer address rejected" in res.text
        assert "access-control-allow-origin" not in res.headers


def test_phase6_2_section_9_6_routed_request_regression():
    """
    SECTION 9.6: Routed-request regression.
    Proves that actual duplicate or contradictory browser metadata is rejected on
    non-preflight privileged requests before state mutation (e.g. save_settings).
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    invalid_browser_cases = [
        ([("Origin", "https://localhost:8000"), ("Origin", "https://evil.example")], "Duplicate Origin"),
        ([("Sec-Fetch-Site", "same-origin"), ("Sec-Fetch-Site", "cross-site")], "Duplicate Sec-Fetch-Site"),
        ([("Sec-Fetch-Site", "cross-site")], "Cross-site Fetch Metadata"),
        ([("Origin", "null")], "Null Origin"),
        ([("Origin", "https://evil.example")], "Hostile Origin"),
    ]

    for headers_tuples, desc in invalid_browser_cases:
        full_headers = [
            ("Host", "localhost"),
            ("Authorization", f"Bearer {token}"),
        ] + headers_tuples

        with patch("backend.main.save_settings") as mock_save:
            res = client.post("/api/settings", json={"demo_mode": True}, headers=full_headers)
            assert res.status_code == 403, f"Routed request case '{desc}' expected 403, got {res.status_code}"
            assert not mock_save.called, f"save_settings MUST NOT be called on rejected case '{desc}'"


def test_phase6_2_section_9_7_behavioral_middleware_order_regression():
    """
    SECTION 9.7: Middleware-order regression.
    Behaviorally proves the exact execution order:
    1. Remote canonical preflight -> rejected by LoopbackPeerMiddleware (403, peer message)
    2. Loopback invalid Host preflight -> rejected by TrustedHostMiddleware (400, "Invalid host header")
    3. Loopback duplicate Origin preflight -> rejected by BrowserContextValidationMiddleware (403, "Origin verification failed", no ACAO)
    4. Loopback canonical preflight -> accepted by CORSMiddleware (200, ACAO = "https://localhost:8000")
    """
    # 1. Remote peer -> rejected by LoopbackPeerMiddleware
    client_remote = TestClient(app, base_url="https://localhost:8000", client=("192.168.1.5", 50000))
    res1 = client_remote.options(
        "/api/settings",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Access-Control-Request-Method", "POST"),
        ]
    )
    assert res1.status_code == 403
    assert "Non-loopback peer address rejected" in res1.text
    assert "access-control-allow-origin" not in res1.headers

    # 2. Loopback peer with invalid Host -> rejected by TrustedHostMiddleware
    client_loopback = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    res2 = client_loopback.options(
        "/api/settings",
        headers=[
            ("Host", "evil.example"),
            ("Origin", "https://localhost:8000"),
            ("Access-Control-Request-Method", "POST"),
        ]
    )
    assert res2.status_code == 400
    assert "Invalid host header" in res2.text

    # 3. Loopback peer with valid Host but duplicate Origin -> rejected by BrowserContextValidationMiddleware
    res3 = client_loopback.options(
        "/api/settings",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Origin", "https://evil.example"),
            ("Access-Control-Request-Method", "POST"),
        ]
    )
    assert res3.status_code == 403
    assert "Origin verification failed" in res3.text
    assert "access-control-allow-origin" not in res3.headers

    # 4. Loopback peer with valid Host and canonical Origin -> accepted by CORSMiddleware
    res4 = client_loopback.options(
        "/api/settings",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Sec-Fetch-Site", "same-origin"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "Authorization"),
        ]
    )
    assert res4.status_code == 200
    assert res4.headers.get("access-control-allow-origin") == "https://localhost:8000"


# ==============================================================================
# PHASE 6.3: ROUTE-PURPOSE-AWARE BROWSER-CONTEXT REMEDIATION TESTS (SECTIONS 10 & 11)
# ==============================================================================

def test_phase6_3_section_10_1_microsoft_oauth_callback_success():
    """
    SECTION 10.1: Microsoft OAuth callback success under cross-site navigation.
    Proves that GET /api/auth/callback with Sec-Fetch-Site: cross-site, valid server-created
    state, and loopback peer succeeds (307 redirect to success), calls provider exchange
    exactly once with canonical redirect URI, consumes state, and rejects replays.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    canonical_redirect = f"{CANONICAL_ORIGIN}/api/auth/callback"
    valid_state = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=canonical_redirect,
        account_id="user@outlook.com"
    )

    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)

        res = client.get(
            f"/api/auth/callback?code=mock_msal_code&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
            follow_redirects=False
        )

        assert res.status_code == 307
        assert res.headers["location"] == "/?auth=success&provider=microsoft"
        assert mock_ex.call_count == 1
        assert mock_ex.call_args.kwargs["redirect_uri"] == canonical_redirect
        assert mock_ex.call_args.kwargs["account_id"] == "user@outlook.com"
        assert mock_ex.call_args.kwargs["code"] == "mock_msal_code"

        # Replay rejected
        res_replay = client.get(
            f"/api/auth/callback?code=mock_msal_code&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
            follow_redirects=False
        )
        assert res_replay.status_code == 307
        assert "auth_error=invalid_state" in res_replay.headers["location"]
        assert mock_ex.call_count == 1  # No second exchange invocation


def test_phase6_3_section_10_2_google_oauth_callback_success():
    """
    SECTION 10.2: Google OAuth callback success under cross-site navigation.
    Proves that GET /api/auth/google/callback with Sec-Fetch-Site: cross-site, valid server-created
    state, and loopback peer succeeds (307 redirect to success), calls provider exchange
    exactly once with canonical redirect URI, consumes state, and rejects replays.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    canonical_redirect = f"{CANONICAL_ORIGIN}/api/auth/google/callback"
    valid_state = OAUTH_STATE_MANAGER.create_state(
        provider="GMAIL",
        redirect_uri=canonical_redirect,
        account_id="user@gmail.com"
    )

    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)

        res = client.get(
            f"/api/auth/google/callback?code=mock_google_code&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
            follow_redirects=False
        )

        assert res.status_code == 307
        assert res.headers["location"] == "/?auth=success&provider=google"
        assert mock_ex.call_count == 1
        assert mock_ex.call_args.kwargs["redirect_uri"] == canonical_redirect
        assert mock_ex.call_args.kwargs["account_id"] == "user@gmail.com"
        assert mock_ex.call_args.kwargs["code"] == "mock_google_code"

        # Replay rejected
        res_replay = client.get(
            f"/api/auth/google/callback?code=mock_google_code&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site"),
            ],
            follow_redirects=False
        )
        assert res_replay.status_code == 307
        assert "auth_error=invalid_state" in res_replay.headers["location"]
        assert mock_ex.call_count == 1


def test_phase6_3_section_10_3_invalid_oauth_state_remains_blocked():
    """
    SECTION 10.3: Invalid OAuth state remains blocked under cross-site navigation.
    Tests missing, empty, forged, expired, consumed, and wrong-provider states for both
    Microsoft and Google callbacks. Proves token exchange is never invoked and sanitized
    failure redirects are returned.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    # 1. State for Google tested on MSAL callback
    g_state = OAUTH_STATE_MANAGER.create_state(
        provider="GMAIL",
        redirect_uri=f"{CANONICAL_ORIGIN}/api/auth/google/callback"
    )

    # 2. State for MSAL tested on Google callback
    m_state = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=f"{CANONICAL_ORIGIN}/api/auth/callback"
    )

    test_matrix = [
        # (Path, query_params, expected_error)
        ("/api/auth/callback", "code=123", "invalid_state"),  # missing state
        ("/api/auth/callback", "code=123&state=", "invalid_state"),  # empty state
        ("/api/auth/callback", "code=123&state=forged_state_token", "invalid_state"),  # forged state
        ("/api/auth/callback", f"code=123&state={g_state}", "invalid_state"),  # wrong-provider state
        ("/api/auth/google/callback", "code=123", "invalid_state"),  # missing state
        ("/api/auth/google/callback", "code=123&state=", "invalid_state"),  # empty state
        ("/api/auth/google/callback", "code=123&state=forged_state_token", "invalid_state"),  # forged state
        ("/api/auth/google/callback", f"code=123&state={m_state}", "invalid_state"),  # wrong-provider state
    ]

    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_graph_ex, \
         patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_gmail_ex:

        for path, query, expected_err in test_matrix:
            res = client.get(
                f"{path}?{query}",
                headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
                follow_redirects=False
            )
            assert res.status_code == 307
            assert f"auth_error={expected_err}" in res.headers["location"]
            assert not mock_graph_ex.called
            assert not mock_gmail_ex.called


def test_phase6_3_section_10_4_provider_error_behavior():
    """
    SECTION 10.4: Provider error behavior under cross-site navigation.
    Submits callback with valid state and error parameter. Proves state is consumed,
    provider exchange is not called, sanitized failure is returned, and replay fails.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    # MSAL provider error
    msal_state = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=f"{CANONICAL_ORIGIN}/api/auth/callback"
    )
    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_graph_ex:
        res = client.get(
            f"/api/auth/callback?error=access_denied&error_description=User+cancelled&state={msal_state}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res.status_code == 307
        assert res.headers["location"] == "/?auth_error=provider_error"
        assert not mock_graph_ex.called

        # Replay fails (state was consumed)
        res_replay = client.get(
            f"/api/auth/callback?code=mock_code&state={msal_state}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res_replay.status_code == 307
        assert "auth_error=invalid_state" in res_replay.headers["location"]

    # Google provider error
    google_state = OAUTH_STATE_MANAGER.create_state(
        provider="GMAIL",
        redirect_uri=f"{CANONICAL_ORIGIN}/api/auth/google/callback"
    )
    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_gmail_ex:
        res = client.get(
            f"/api/auth/google/callback?error=access_denied&error_description=User+cancelled&state={google_state}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res.status_code == 307
        assert res.headers["location"] == "/?auth_error=provider_error"
        assert not mock_gmail_ex.called

        # Replay fails
        res_replay = client.get(
            f"/api/auth/google/callback?code=mock_code&state={google_state}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res_replay.status_code == 307
        assert "auth_error=invalid_state" in res_replay.headers["location"]


def test_phase6_3_section_10_5_callback_structural_rejection():
    """
    SECTION 10.5: Callback structural rejections.
    Proves that hostile Origin, null Origin, duplicate Origin, duplicate Sec-Fetch-Site,
    comma-joined Sec-Fetch-Site, empty Sec-Fetch-Site, POST method, or OPTIONS preflight
    fail closed before provider exchange.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    msal_state = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=f"{CANONICAL_ORIGIN}/api/auth/callback"
    )

    structural_fail_cases = [
        ([("Origin", "https://evil.example"), ("Sec-Fetch-Site", "cross-site")], 403, "hostile Origin"),
        ([("Origin", "null"), ("Sec-Fetch-Site", "cross-site")], 403, "null Origin"),
        ([("Origin", "https://localhost:8000"), ("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")], 403, "duplicate Origin"),
        ([("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "cross-site")], 403, "duplicate Sec-Fetch-Site"),
        ([("Sec-Fetch-Site", "cross-site,same-origin")], 403, "comma-joined Sec-Fetch-Site"),
        ([("Sec-Fetch-Site", "")], 403, "empty Sec-Fetch-Site"),
    ]

    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_graph_ex:
        for headers_tuples, expected_status, desc in structural_fail_cases:
            full_headers = [("Host", "localhost")] + headers_tuples
            res = client.get(f"/api/auth/callback?code=123&state={msal_state}", headers=full_headers, follow_redirects=False)
            assert res.status_code == expected_status, f"Structural case '{desc}' expected {expected_status}, got {res.status_code}"
            assert not mock_graph_ex.called

        # POST method instead of GET -> rejected (401 or 403 or 405)
        res_post = client.post(
            f"/api/auth/callback?code=123&state={msal_state}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")]
        )
        assert res_post.status_code in [401, 403, 405]
        assert not mock_graph_ex.called

        # OPTIONS preflight shape on callback -> rejected with 403 (no navigation exception for preflights)
        res_options = client.options(
            "/api/auth/callback",
            headers=[
                ("Host", "localhost"),
                ("Origin", "https://localhost:8000"),
                ("Sec-Fetch-Site", "cross-site"),
                ("Access-Control-Request-Method", "GET"),
            ]
        )
        assert res_options.status_code == 403
        assert "access-control-allow-origin" not in res_options.headers
        assert not mock_graph_ex.called


def test_phase6_3_section_10_6_outlook_taskpane_navigation():
    """
    SECTION 10.6: Outlook taskpane cross-site framed navigation success.
    Proves that GET /add-in/taskpane.html with Sec-Fetch-Site: cross-site returns 200 OK,
    serves strict cache-control: no-store, nosniff, no-referrer, and approved frame-ancestors CSP,
    and preserves canonical API CORS allowlist ['https://localhost:8000'].
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # GET request
    res = client.get(
        "/add-in/taskpane.html",
        headers=[
            ("Host", "localhost"),
            ("Sec-Fetch-Site", "cross-site"),
        ]
    )
    assert res.status_code == 200
    assert f'window.__AURA_SESSION_TOKEN__ = "{token}";' in res.text
    assert res.headers["Cache-Control"] == "no-store, max-age=0"
    assert res.headers["Pragma"] == "no-cache"
    assert res.headers["Referrer-Policy"] == "no-referrer"
    assert res.headers["X-Content-Type-Options"] == "nosniff"
    csp = res.headers["Content-Security-Policy"]
    assert "frame-ancestors" in csp
    assert "https://outlook.office.com" in csp
    assert "https://outlook.office365.com" in csp

    # HEAD request
    res_head = client.head(
        "/add-in/taskpane.html",
        headers=[
            ("Host", "localhost"),
            ("Sec-Fetch-Site", "cross-site"),
        ]
    )
    assert res_head.status_code == 200

    # Verify API CORS remains strictly canonical
    assert ALLOWED_ORIGINS == ["https://localhost:8000"]


def test_phase6_3_section_10_7_taskpane_negative_cases():
    """
    SECTION 10.7: Taskpane negative cases.
    Proves that cross-site requests to non-taskpane endpoints (/add-in/taskpane.js,
    /add-in/taskpane.css, /), POST to taskpane.html, or taskpane with hostile Origin
    are strictly rejected.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    negative_cases = [
        ("GET", "/add-in/taskpane.html", [("Origin", "https://evil.example"), ("Sec-Fetch-Site", "cross-site")], 403, "hostile Origin"),
        ("GET", "/add-in/taskpane.html", [("Origin", "null"), ("Sec-Fetch-Site", "cross-site")], 403, "null Origin"),
        ("GET", "/add-in/taskpane.html", [("Origin", "https://localhost:8000"), ("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")], 403, "duplicate Origin"),
        ("GET", "/add-in/taskpane.html", [("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "cross-site")], 403, "duplicate Sec-Fetch-Site"),
        ("GET", "/add-in/taskpane.html", [("Sec-Fetch-Site", "cross-site,same-origin")], 403, "comma-joined Sec-Fetch-Site"),
        ("POST", "/add-in/taskpane.html", [("Sec-Fetch-Site", "cross-site")], 405, "POST taskpane"),
        ("GET", "/add-in/taskpane.js", [("Sec-Fetch-Site", "cross-site")], 403, "cross-site taskpane.js"),
        ("GET", "/add-in/taskpane.css", [("Sec-Fetch-Site", "cross-site")], 403, "cross-site taskpane.css"),
        ("GET", "/add-in/other-file.html", [("Sec-Fetch-Site", "cross-site")], 403, "cross-site other add-in file"),
        ("GET", "/", [("Sec-Fetch-Site", "cross-site")], 403, "cross-site root index"),
    ]

    for method, path, headers_tuples, expected_status, desc in negative_cases:
        full_headers = [("Host", "localhost")] + headers_tuples
        res = client.request(method, path, headers=full_headers)
        assert res.status_code in [expected_status, 403, 405], f"Taskpane negative case '{desc}' expected {expected_status}, got {res.status_code}"


def test_phase6_3_section_10_8_privileged_routes_remain_protected():
    """
    SECTION 10.8: Privileged routes remain protected from Sec-Fetch-Site: cross-site.
    Proves that authenticated API endpoints reject cross-site requests with 403 and
    execute zero side effects / mutations.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    protected_endpoints = [
        ("GET", "/api/status", None),
        ("POST", "/api/settings", {"demo_mode": True}),
        ("GET", "/api/auth/msal/url", None),
        ("GET", "/api/auth/google/url", None),
        ("GET", "/api/profile", None),
        ("GET", "/api/accounts", None),
    ]

    with patch("backend.main.save_settings") as mock_save:
        for method, path, payload in protected_endpoints:
            headers = [
                ("Host", "localhost"),
                ("Authorization", f"Bearer {token}"),
                ("Sec-Fetch-Site", "cross-site"),
            ]
            res = client.request(method, path, json=payload, headers=headers)
            assert res.status_code == 403, f"Protected endpoint {method} {path} with cross-site expected 403, got {res.status_code}"
            assert not mock_save.called


def test_phase6_3_section_11_comprehensive_behavioral_middleware_order_proof():
    """
    SECTION 11: Behavioral middleware-order proof.
    Behaviorally proves the end-to-end security pipeline:
    1. Remote request -> rejected by LoopbackPeerMiddleware (403, peer message)
    2. Loopback request with invalid Host -> rejected by TrustedHostMiddleware (400, "Invalid host header")
    3. Loopback malformed browser context -> rejected by BrowserContextValidationMiddleware (403, "Origin verification failed")
    4. Loopback valid canonical preflight -> accepted by CORSMiddleware (200, ACAO = "https://localhost:8000")
    5. Loopback privileged route -> unauthenticated 401, authenticated 200
    6. Valid cross-site OAuth navigation -> passes middleware, reaches OAuth state validation (307)
    7. Valid cross-site Outlook taskpane navigation -> passes middleware, returns secure taskpane HTML (200)
    """
    token = get_local_session_token()

    # 1. Remote request
    client_remote = TestClient(app, base_url="https://localhost:8000", client=("192.168.1.5", 50000))
    res1 = client_remote.get("/api/safety-policy")
    assert res1.status_code == 403
    assert "Non-loopback peer address rejected" in res1.text

    # 2. Loopback with invalid Host
    client_loopback = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    res2 = client_loopback.get("/api/safety-policy", headers=[("Host", "evil.example")])
    assert res2.status_code == 400
    assert "Invalid host header" in res2.text

    # 3. Loopback with malformed browser context
    res3 = client_loopback.options(
        "/api/settings",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Origin", "https://evil.example"),
            ("Access-Control-Request-Method", "POST"),
        ]
    )
    assert res3.status_code == 403
    assert "Origin verification failed" in res3.text
    assert "access-control-allow-origin" not in res3.headers

    # 4. Loopback valid canonical preflight
    res4 = client_loopback.options(
        "/api/settings",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Sec-Fetch-Site", "same-origin"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "Authorization"),
        ]
    )
    assert res4.status_code == 200
    assert res4.headers.get("access-control-allow-origin") == "https://localhost:8000"

    # 5. Loopback privileged route
    res5_unauth = client_loopback.get("/api/status", headers=[("Host", "localhost")])
    assert res5_unauth.status_code == 401
    res5_auth = client_loopback.get("/api/status", headers=[("Host", "localhost"), ("Authorization", f"Bearer {token}")])
    assert res5_auth.status_code == 200

    # 6. Valid cross-site OAuth navigation
    msal_state = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=f"{CANONICAL_ORIGIN}/api/auth/callback"
    )
    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)
        res6 = client_loopback.get(
            f"/api/auth/callback?code=mock_code&state={msal_state}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res6.status_code == 307
        assert res6.headers["location"] == "/?auth=success&provider=microsoft"

    # 7. Valid cross-site Outlook taskpane navigation
    res7 = client_loopback.get(
        "/add-in/taskpane.html",
        headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")]
    )
    assert res7.status_code == 200
    assert "frame-ancestors" in res7.headers["Content-Security-Policy"]


# ==============================================================================
# PHASE 6.4: TIGHTENED CROSS-SITE NAVIGATION PREDICATE TESTS (SECTION 8)
# ==============================================================================

def test_phase6_4_microsoft_callback_requires_origin_absence():
    """
    SECTION 8.1: Microsoft callback matrix.
    Proves that GET /api/auth/callback allows Sec-Fetch-Site: cross-site ONLY when Origin
    is absent. Canonical Origin, hostile Origin, null Origin, or mixed-case Fetch Metadata
    tokens fail closed with 403 and zero exchange calls.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    canonical_redirect = f"{CANONICAL_ORIGIN}/api/auth/callback"

    # 1. Origin absent + exact cross-site -> 307 success, 1 exchange call
    valid_state_1 = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=canonical_redirect,
        account_id="user@outlook.com"
    )
    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)
        res1 = client.get(
            f"/api/auth/callback?code=code_ok&state={valid_state_1}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res1.status_code == 307
        assert res1.headers["location"] == "/?auth=success&provider=microsoft"
        assert mock_ex.call_count == 1

    # 2. Rejection matrix with valid state: must return 403 with 0 exchange calls
    rejection_matrix = [
        ([("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")], "canonical Origin + cross-site"),
        ([("Origin", "https://evil.example"), ("Sec-Fetch-Site", "cross-site")], "hostile Origin + cross-site"),
        ([("Origin", "null"), ("Sec-Fetch-Site", "cross-site")], "null Origin + cross-site"),
        ([("Sec-Fetch-Site", "CrOsS-SiTe")], "mixed-case CrOsS-SiTe"),
        ([("Sec-Fetch-Site", "CROSS-SITE")], "uppercase CROSS-SITE"),
        ([("Sec-Fetch-Site", "cross-site ")], "trailing whitespace cross-site"),
        ([("Sec-Fetch-Site", " cross-site")], "leading whitespace cross-site"),
        ([("Sec-Fetch-Site", "cross-site"), ("Sec-Fetch-Site", "cross-site")], "duplicate cross-site"),
        ([("Sec-Fetch-Site", "cross-site,same-origin")], "comma-joined cross-site"),
    ]

    for headers_tuples, desc in rejection_matrix:
        state_rej = OAUTH_STATE_MANAGER.create_state(
            provider="MICROSOFT_GRAPH",
            redirect_uri=canonical_redirect,
            account_id="user@outlook.com"
        )
        with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_ex:
            full_headers = [("Host", "localhost")] + headers_tuples
            res_rej = client.get(
                f"/api/auth/callback?code=code_test&state={state_rej}",
                headers=full_headers,
                follow_redirects=False
            )
            assert res_rej.status_code == 403, f"Case '{desc}' expected 403, got {res_rej.status_code}"
            assert not mock_ex.called, f"Exchange MUST NOT be called for case '{desc}'"


def test_phase6_4_google_callback_requires_origin_absence():
    """
    SECTION 8.2: Google callback matrix.
    Proves that GET /api/auth/google/callback allows Sec-Fetch-Site: cross-site ONLY when Origin
    is absent. Canonical Origin, hostile Origin, or mixed-case Fetch Metadata tokens fail closed.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    canonical_redirect = f"{CANONICAL_ORIGIN}/api/auth/google/callback"

    # 1. Valid Origin-absent exact-cross-site -> 307 success
    valid_state_g = OAUTH_STATE_MANAGER.create_state(
        provider="GMAIL",
        redirect_uri=canonical_redirect,
        account_id="user@gmail.com"
    )
    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)
        res = client.get(
            f"/api/auth/google/callback?code=code_g&state={valid_state_g}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res.status_code == 307
        assert res.headers["location"] == "/?auth=success&provider=google"
        assert mock_ex.call_count == 1

        # Replay rejected
        res_rep = client.get(
            f"/api/auth/google/callback?code=code_g&state={valid_state_g}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res_rep.status_code == 307
        assert "auth_error=invalid_state" in res_rep.headers["location"]
        assert mock_ex.call_count == 1

    # 2. Canonical Origin + cross-site -> 403
    state_can = OAUTH_STATE_MANAGER.create_state(provider="GMAIL", redirect_uri=canonical_redirect)
    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_ex:
        res_can = client.get(
            f"/api/auth/google/callback?code=code_can&state={state_can}",
            headers=[("Host", "localhost"), ("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")],
            follow_redirects=False
        )
        assert res_can.status_code == 403
        assert not mock_ex.called

    # 3. Mixed-case cross-site -> 403
    state_mix = OAUTH_STATE_MANAGER.create_state(provider="GMAIL", redirect_uri=canonical_redirect)
    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_ex:
        res_mix = client.get(
            f"/api/auth/google/callback?code=code_mix&state={state_mix}",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", "CrOsS-SiTe")],
            follow_redirects=False
        )
        assert res_mix.status_code == 403
        assert not mock_ex.called


def test_phase6_4_taskpane_requires_origin_absence():
    """
    SECTION 8.3: Outlook taskpane matrix.
    Proves that GET/HEAD /add-in/taskpane.html requires Origin absence for cross-site framing.
    Canonical Origin, hostile Origin, or mixed-case Fetch Metadata tokens fail closed with 403.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # 1. Valid Origin-absent exact-cross-site GET and HEAD -> 200 OK
    res_get = client.get("/add-in/taskpane.html", headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")])
    assert res_get.status_code == 200
    assert res_get.headers["Cache-Control"] == "no-store, max-age=0"
    assert "frame-ancestors" in res_get.headers["Content-Security-Policy"]

    res_head = client.head("/add-in/taskpane.html", headers=[("Host", "localhost"), ("Sec-Fetch-Site", "cross-site")])
    assert res_head.status_code == 200

    # 2. Canonical Origin + cross-site -> 403
    res_can_get = client.get(
        "/add-in/taskpane.html",
        headers=[("Host", "localhost"), ("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")]
    )
    assert res_can_get.status_code == 403
    assert "access-control-allow-origin" not in res_can_get.headers

    res_can_head = client.head(
        "/add-in/taskpane.html",
        headers=[("Host", "localhost"), ("Origin", "https://localhost:8000"), ("Sec-Fetch-Site", "cross-site")]
    )
    assert res_can_head.status_code == 403
    assert "access-control-allow-origin" not in res_can_head.headers

    # 3. Hostile Origin + cross-site -> 403
    res_hostile = client.get(
        "/add-in/taskpane.html",
        headers=[("Host", "localhost"), ("Origin", "https://evil.example"), ("Sec-Fetch-Site", "cross-site")]
    )
    assert res_hostile.status_code == 403
    assert "access-control-allow-origin" not in res_hostile.headers

    # 4. Mixed-case Fetch Metadata tokens -> 403
    for mixed_val in ["CrOsS-SiTe", "CROSS-SITE", "cross-site ", "Cross-Site"]:
        res_m = client.get(
            "/add-in/taskpane.html",
            headers=[("Host", "localhost"), ("Sec-Fetch-Site", mixed_val)]
        )
        assert res_m.status_code == 403
        assert "access-control-allow-origin" not in res_m.headers


def test_phase6_4_fetch_metadata_values_are_exact_case_sensitive_tokens():
    """
    SECTION 8.4: Fetch Metadata values are exact case-sensitive protocol tokens.
    Proves that mixed-case or capitalized variants of same-origin, same-site, none,
    or cross-site fail closed as malformed.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    invalid_token_values = [
        "Same-Origin",
        "SAME-ORIGIN",
        "Same-Site",
        "SAME-SITE",
        "None",
        "NONE",
        "CrOsS-SiTe",
        "CROSS-SITE",
        "same_origin",
        "cross_site",
    ]

    for val in invalid_token_values:
        # Privileged route
        res = client.get(
            "/api/status",
            headers=[
                ("Host", "localhost"),
                ("Authorization", f"Bearer {token}"),
                ("Sec-Fetch-Site", val)
            ]
        )
        assert res.status_code == 403, f"Token value '{val}' expected 403, got {res.status_code}"
        assert "Malformed Sec-Fetch-Site value rejected" in res.json().get("detail", "")

        # Preflight
        res_opt = client.options(
            "/api/settings",
            headers=[
                ("Host", "localhost"),
                ("Origin", "https://localhost:8000"),
                ("Access-Control-Request-Method", "POST"),
                ("Sec-Fetch-Site", val)
            ]
        )
        assert res_opt.status_code == 403
        assert "access-control-allow-origin" not in res_opt.headers


def test_phase6_4_rejected_callback_does_not_consume_oauth_state():
    """
    SECTION 8.1 & 8.5: Rejected callback does not consume OAuth state.
    Proves that a request rejected at the pre-CORS browser-context boundary (e.g. Canonical Origin
    + cross-site) leaves valid OAuth state unconsumed, so a subsequent valid request can succeed.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    canonical_redirect = f"{CANONICAL_ORIGIN}/api/auth/callback"

    valid_state = OAUTH_STATE_MANAGER.create_state(
        provider="MICROSOFT_GRAPH",
        redirect_uri=canonical_redirect,
        account_id="user@outlook.com"
    )

    # 1. First attempt: rejected by middleware due to canonical Origin + cross-site
    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_ex:
        res_rej = client.get(
            f"/api/auth/callback?code=code_1&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Origin", "https://localhost:8000"),
                ("Sec-Fetch-Site", "cross-site")
            ],
            follow_redirects=False
        )
        assert res_rej.status_code == 403
        assert not mock_ex.called

    # 2. Second attempt: valid Origin-absent cross-site request with same state succeeds
    with patch("backend.main.provider_manager.graph_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)
        res_ok = client.get(
            f"/api/auth/callback?code=code_1&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site")
            ],
            follow_redirects=False
        )
        assert res_ok.status_code == 307
        assert res_ok.headers["location"] == "/?auth=success&provider=microsoft"
        assert mock_ex.call_count == 1


def test_phase6_4_cross_site_preflights_remain_blocked():
    """
    SECTION 8.4: Cross-site preflights remain blocked before CORS.
    Proves that OPTIONS preflights carrying Sec-Fetch-Site: cross-site receive no navigation
    exception and fail closed with 403 and zero CORS response headers.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    preflight_paths = [
        "/api/settings",
        "/api/auth/callback",
        "/api/auth/google/callback",
        "/add-in/taskpane.html",
    ]

    for path in preflight_paths:
        res = client.options(
            path,
            headers=[
                ("Host", "localhost"),
                ("Origin", "https://localhost:8000"),
                ("Access-Control-Request-Method", "POST"),
                ("Sec-Fetch-Site", "cross-site"),
            ]
        )
        assert res.status_code == 403, f"Preflight on {path} with cross-site expected 403, got {res.status_code}"
        assert "access-control-allow-origin" not in res.headers
        assert "access-control-allow-credentials" not in res.headers


def test_phase6_4_protected_routes_remain_blocked():
    """
    SECTION 8.4: Protected routes remain blocked from cross-site requests even with valid token.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    protected_cases = [
        ("GET", "/api/status", None),
        ("POST", "/api/settings", {"demo_mode": True}),
        ("GET", "/api/auth/msal/url", None),
        ("GET", "/api/auth/google/url", None),
        ("GET", "/api/profile", None),
        ("GET", "/api/accounts", None),
    ]

    with patch("backend.main.save_settings") as mock_save:
        for method, path, payload in protected_cases:
            # Exact cross-site
            res = client.request(
                method,
                path,
                json=payload,
                headers=[
                    ("Host", "localhost"),
                    ("Authorization", f"Bearer {token}"),
                    ("Sec-Fetch-Site", "cross-site")
                ]
            )
            assert res.status_code == 403
            assert not mock_save.called

            # Mixed-case cross-site
            res_mix = client.request(
                method,
                path,
                json=payload,
                headers=[
                    ("Host", "localhost"),
                    ("Authorization", f"Bearer {token}"),
                    ("Sec-Fetch-Site", "CrOsS-SiTe")
                ]
            )
            assert res_mix.status_code == 403
            assert not mock_save.called


def test_phase6_4_valid_navigation_and_nonbrowser_regressions():
    """
    SECTION 8.5: Valid navigations, same-origin preflights, and non-browser requests regressions.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    token = get_local_session_token()

    # 1. Legitimate same-origin preflight
    res_preflight = client.options(
        "/api/settings",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Sec-Fetch-Site", "same-origin"),
            ("Access-Control-Request-Method", "POST"),
            ("Access-Control-Request-Headers", "Authorization"),
        ]
    )
    assert res_preflight.status_code == 200
    assert res_preflight.headers.get("access-control-allow-origin") == "https://localhost:8000"

    # 2. Authenticated non-browser request
    res_non_browser = client.get(
        "/api/status",
        headers=[
            ("Host", "localhost"),
            ("Authorization", f"Bearer {token}"),
        ]
    )
    assert res_non_browser.status_code == 200
    assert res_non_browser.json().get("status") == "ONLINE"


# ==============================================================================
# PHASE 6.5: TESTS-ONLY CORRECTIVE REMEDIATIONS
# ==============================================================================


def test_phase6_5_rejected_google_callback_does_not_consume_oauth_state():
    """
    SECTION 5: Proves that a Google OAuth callback rejected by browser-context middleware
    (e.g., canonical Origin + cross-site Fetch Metadata) does not consume the server-side
    OAuth state, allowing a subsequent conforming Origin-absent request with the same state
    to succeed, and confirming that a third replay request is rejected as consumed.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))
    canonical_redirect = f"{CANONICAL_ORIGIN}/api/auth/google/callback"
    test_account = "user@gmail.com"
    test_code = "mock_google_code_p65"

    valid_state = OAUTH_STATE_MANAGER.create_state(
        provider="GMAIL",
        redirect_uri=canonical_redirect,
        account_id=test_account
    )

    # 1. First attempt: rejected by browser-context middleware due to canonical Origin + cross-site
    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_ex:
        res_rej = client.get(
            f"/api/auth/google/callback?code={test_code}&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Origin", "https://localhost:8000"),
                ("Sec-Fetch-Site", "cross-site")
            ],
            follow_redirects=False
        )
        assert res_rej.status_code == 403
        assert "access-control-allow-origin" not in res_rej.headers
        assert not mock_ex.called

    # 2. Second attempt: conforming Origin-absent cross-site request with the same state succeeds
    with patch("backend.main.provider_manager.gmail_provider.exchange_code_for_token") as mock_ex, \
         patch("backend.main.sync_and_triage_inbox"):
        mock_ex.return_value = MagicMock(success=True)
        res_ok = client.get(
            f"/api/auth/google/callback?code={test_code}&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site")
            ],
            follow_redirects=False
        )
        assert res_ok.status_code == 307
        assert res_ok.headers["location"] == "/?auth=success&provider=google"
        assert mock_ex.call_count == 1
        assert mock_ex.call_args.kwargs["code"] == test_code
        assert mock_ex.call_args.kwargs["redirect_uri"] == canonical_redirect
        assert mock_ex.call_args.kwargs["account_id"] == test_account

        # 3. Third attempt: replay with already consumed state fails
        res_replay = client.get(
            f"/api/auth/google/callback?code={test_code}&state={valid_state}",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", "cross-site")
            ],
            follow_redirects=False
        )
        assert res_replay.status_code == 307
        assert "auth_error=invalid_state" in res_replay.headers["location"]
        assert mock_ex.call_count == 1  # No additional exchange on replay


def test_phase6_5_taskpane_head_rejects_mixed_case_fetch_metadata():
    """
    SECTION 6: Proves that HEAD /add-in/taskpane.html fails closed with 403 on mixed-case
    Fetch Metadata tokens (CrOsS-SiTe, CROSS-SITE, Cross-Site) without ACAO/ACAC headers,
    while reaffirming that valid lowercase Sec-Fetch-Site: cross-site returns 200
    and canonical Origin + cross-site returns 403.
    """
    client = TestClient(app, base_url="https://localhost:8000", client=("127.0.0.1", 50000))

    mixed_case_tokens = ["CrOsS-SiTe", "CROSS-SITE", "Cross-Site"]
    for token_val in mixed_case_tokens:
        res = client.head(
            "/add-in/taskpane.html",
            headers=[
                ("Host", "localhost"),
                ("Sec-Fetch-Site", token_val)
            ]
        )
        assert res.status_code == 403, f"HEAD taskpane with '{token_val}' expected 403, got {res.status_code}"
        assert "access-control-allow-origin" not in res.headers
        assert "access-control-allow-credentials" not in res.headers

    # Preserved valid HEAD behavior
    res_valid = client.head(
        "/add-in/taskpane.html",
        headers=[
            ("Host", "localhost"),
            ("Sec-Fetch-Site", "cross-site")
        ]
    )
    assert res_valid.status_code == 200
    assert "access-control-allow-origin" not in res_valid.headers

    # Preserved canonical Origin + cross-site HEAD rejection
    res_canonical = client.head(
        "/add-in/taskpane.html",
        headers=[
            ("Host", "localhost"),
            ("Origin", "https://localhost:8000"),
            ("Sec-Fetch-Site", "cross-site")
        ]
    )
    assert res_canonical.status_code == 403
    assert "access-control-allow-origin" not in res_canonical.headers
