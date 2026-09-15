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
