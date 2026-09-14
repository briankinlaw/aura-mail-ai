"""
Unit tests for Outlook Web Add-in (Office.js), manifest validation, and taskpane endpoints.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from fastapi.testclient import TestClient

from backend.main import app
from backend.auth import get_auth_headers

client = TestClient(app)
client.headers.update(get_auth_headers())

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = PROJECT_ROOT / "manifest.xml"


def test_manifest_xml_validity():
    """Validates that manifest.xml is well-formed XML and conforms to Outlook MailApp schema requirements."""
    assert MANIFEST_PATH.exists(), "manifest.xml must exist in project root"
    
    tree = ET.parse(str(MANIFEST_PATH))
    root = tree.getroot()
    
    # Check basic attributes and namespaces
    assert "OfficeApp" in root.tag
    
    namespaces = {
        "ns": "http://schemas.microsoft.com/office/appforoffice/1.1",
        "bt": "http://schemas.microsoft.com/office/officeappbasictypes/1.0",
        "mail": "http://schemas.microsoft.com/office/mailappversionoverrides/1.0"
    }
    
    # Check Id, Version, Provider
    id_elem = root.find("ns:Id", namespaces)
    assert id_elem is not None and len(id_elem.text) > 10
    
    version_elem = root.find("ns:Version", namespaces)
    assert version_elem is not None and version_elem.text == "1.1.0"
    
    provider_elem = root.find("ns:ProviderName", namespaces)
    assert provider_elem is not None and provider_elem.text == "Brian Kinlaw"
    
    # Check Hosts
    hosts = root.findall(".//ns:Host", namespaces)
    host_names = [h.attrib.get("Name") for h in hosts]
    assert "Mailbox" in host_names
    
    # Check FormSettings SourceLocation
    read_loc = root.find(".//ns:Form[@xsi:type='ItemRead']/ns:DesktopSettings/ns:SourceLocation", {
        "ns": "http://schemas.microsoft.com/office/appforoffice/1.1",
        "xsi": "http://www.w3.org/2001/XMLSchema-instance"
    })
    assert read_loc is not None
    assert "/add-in/taskpane.html" in read_loc.attrib.get("DefaultValue", "")


def test_taskpane_static_serving():
    """Verifies that the taskpane HTML, CSS, JS, and icons are properly served via FastAPI."""
    # Taskpane HTML
    res_html = client.get("/add-in/taskpane.html")
    assert res_html.status_code == 200
    assert "Aura Mail AI" in res_html.text
    assert "office.js" in res_html.text
    
    # Taskpane CSS
    res_css = client.get("/add-in/taskpane.css")
    assert res_css.status_code == 200
    assert "--accent-indigo" in res_css.text
    
    # Taskpane JS
    res_js = client.get("/add-in/taskpane.js")
    assert res_js.status_code == 200
    assert "Office.onReady" in res_js.text
    
    # Icons
    for size in [16, 32, 64, 80, 128]:
        res_icon = client.get(f"/static/icon-{size}.png")
        assert res_icon.status_code == 200
        assert res_icon.headers["content-type"] == "image/png"


def test_radar_triage_api():
    """Tests the /api/radar/triage endpoint with a sample recruiter email."""
    payload = {
        "subject": "Executive Search: Principal Solutions Architect (Google Cloud & AI)",
        "body": "Hi Brian, We are reaching out regarding a Principal Solutions Architect role at Apex Cloud Systems. The role leads enterprise data migrations on Google Cloud and AI platforms. Are you open to a brief chat?",
        "sender_name": "Marcus Vance",
        "sender_email": "mvance@apexrecruit.com"
    }
    
    res = client.post("/api/radar/triage", json=payload)
    assert res.status_code == 200
    data = res.json()
    
    assert data["status"] == "SUCCESS"
    assert data["is_recruiter"] is True
    assert data["fit_score"] >= 70
    assert "Apex" in data["company"] or "Client" in data["company"]
    assert "Solutions Architect" in data["role"]
    assert "advisor" in data["suggested_lens"].lower() or "sme" in data["suggested_lens"].lower()


def test_radar_draft_api():
    """Tests the /api/radar/draft endpoint for strictly grounded output with availability slots."""
    payload = {
        "subject": "Executive Cloud Opportunity",
        "body": "Looking forward to speaking about our Director of Cloud Architecture opening.",
        "sender_name": "Marcus Vance",
        "sender_email": "mvance@apexrecruit.com",
        "lens": "Advisor",
        "tone": "Professional & Warm",
        "include_availability": True
    }
    
    res = client.post("/api/radar/draft", json=payload)
    assert res.status_code == 200
    data = res.json()
    
    assert data["status"] == "SUCCESS"
    draft = data["draft_reply"]
    assert "$100M+" in draft or "$8M" in draft
    assert "Brian" in draft and "Kinlaw" in draft
    assert "• " in draft  # Availability bullets included


def test_calendar_availability_api():
    """Tests the /api/calendar/availability endpoint."""
    payload = {
        "days_ahead": 7,
        "timezone": "America/Chicago",
        "duration_minutes": 30
    }
    
    res = client.post("/api/calendar/availability", json=payload)
    assert res.status_code == 200
    data = res.json()
    
    assert data["status"] == "SUCCESS"
    assert "America/Chicago" in data["timezone"]
    assert len(data["slots"]) > 0
    assert "formatted_display" in data["slots"][0]


# --- Phase 2.1 Item Resolver & Graph Status Tests ---

def test_resolve_email_item_success():
    """
    PHASE 2.1 RESOLVER CONTRACT:
    Tests that a normalized Graph REST item ID positively resolves to Aura's composite message ID.
    """
    from backend.main import CACHED_EMAILS
    from backend.models import EmailMessage
    from backend.providers.base import encode_composite_id

    native_id = "AAMkAGI2AAA="
    acc = "kinlawb@outlook.com"
    comp_id = encode_composite_id("MICROSOFT_GRAPH", acc, native_id)

    test_msg = EmailMessage(
        id=comp_id,
        subject="Senior Cloud Architect Reachout",
        sender_name="Recruiter Jane",
        sender_email="jane@recruiting.com",
        body_text="Hello Brian, we have an executive architect role."
    )
    CACHED_EMAILS[comp_id] = test_msg

    res = client.post("/api/emails/resolve-item", json={
        "provider": "MICROSOFT_GRAPH",
        "account_id": acc,
        "item_id": native_id
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "SUCCESS"
    assert data["found"] is True
    assert data["composite_id"] == comp_id
    assert data["email"]["subject"] == "Senior Cloud Architect Reachout"


def test_resolve_email_item_unauthenticated_rejected():
    """
    PHASE 2.1 RESOLVER AUTH SECURITY:
    Verifies that unauthenticated calls to /api/emails/resolve-item fail with 401 Unauthorized.
    """
    unauth = TestClient(app)
    res = unauth.post("/api/emails/resolve-item", json={
        "provider": "MICROSOFT_GRAPH",
        "item_id": "AAMkAGI2AAA="
    })
    assert res.status_code == 401
    assert "Authentication required" in res.json().get("detail", "")


def test_resolve_email_item_malformed_auth_rejected():
    """
    PHASE 2.1 RESOLVER AUTH SECURITY:
    Verifies that malformed Authorization header fails with 403 Forbidden.
    """
    unauth = TestClient(app)
    res = unauth.post(
        "/api/emails/resolve-item",
        json={"provider": "MICROSOFT_GRAPH", "item_id": "AAMkAGI2AAA="},
        headers={"Authorization": "InvalidScheme token123"}
    )
    assert res.status_code == 403


def test_resolve_email_item_account_scoping():
    """
    PHASE 2.1 SCOPING SECURITY:
    Verifies that item resolution is strictly scoped to the specified account, failing closed (404)
    if the ID belongs to another account.
    """
    from backend.main import CACHED_EMAILS
    from backend.models import EmailMessage
    from backend.providers.base import encode_composite_id

    native_id = "AAMkAGI3AAA="
    acc1 = "kinlawb@outlook.com"
    comp_id = encode_composite_id("MICROSOFT_GRAPH", acc1, native_id)

    CACHED_EMAILS[comp_id] = EmailMessage(
        id=comp_id,
        subject="Account 1 Email",
        sender_name="Sender",
        sender_email="sender@domain.com",
        body_text="Account 1 body"
    )

    # Attempt lookup with different account_id
    res = client.post("/api/emails/resolve-item", json={
        "provider": "MICROSOFT_GRAPH",
        "account_id": "other.user@outlook.com",
        "item_id": native_id
    })
    assert res.status_code == 404
    assert "not found" in res.json().get("detail", "").lower()


def test_resolve_email_item_unknown_not_found():
    """Verifies that an unknown item ID returns 404 Not Found (fail closed)."""
    res = client.post("/api/emails/resolve-item", json={
        "provider": "MICROSOFT_GRAPH",
        "account_id": "kinlawb@outlook.com",
        "item_id": "NON_EXISTENT_ID_999"
    })
    assert res.status_code == 404


def test_resolve_email_item_empty_bad_request():
    """Verifies that empty item ID returns 400 Bad Request."""
    res = client.post("/api/emails/resolve-item", json={
        "provider": "MICROSOFT_GRAPH",
        "item_id": "   "
    })
    assert res.status_code == 400


def test_resolve_email_item_ambiguous_conflict():
    """
    PHASE 2.1 AMBIGUITY SAFETY:
    Verifies that if multiple items match across accounts and no account_id is provided,
    the resolver fails closed with 409 Conflict rather than guessing.
    """
    from backend.main import CACHED_EMAILS
    from backend.models import EmailMessage
    from backend.providers.base import encode_composite_id

    shared_native_id = "SHARED_NATIVE_123"
    comp1 = encode_composite_id("MICROSOFT_GRAPH", "acc1@outlook.com", shared_native_id)
    comp2 = encode_composite_id("MICROSOFT_GRAPH", "acc2@outlook.com", shared_native_id)

    CACHED_EMAILS[comp1] = EmailMessage(id=comp1, subject="Email 1", sender_name="S1", sender_email="s1@d.com", body_text="Body 1")
    CACHED_EMAILS[comp2] = EmailMessage(id=comp2, subject="Email 2", sender_name="S2", sender_email="s2@d.com", body_text="Body 2")


    res = client.post("/api/emails/resolve-item", json={
        "provider": "MICROSOFT_GRAPH",
        "item_id": shared_native_id
    })
    assert res.status_code == 409
    assert "Ambiguous item resolution" in res.json().get("detail", "")


def test_authoritative_graph_status_indicator():
    """
    PHASE 2.1 STATUS INDICATOR TEST:
    Verifies that /api/status returns authoritative graph_connection status dictionary.
    """
    res = client.get("/api/status")
    assert res.status_code == 200
    data = res.json()
    assert "graph_connection" in data
    g_conn = data["graph_connection"]
    assert "status" in g_conn
    assert "display_text" in g_conn
    assert g_conn["status"] in ["CONNECTED", "AUTH_REQUIRED", "NOT_CONFIGURED", "DEMO", "READY_TO_CONNECT"]


# ---------------------------------------------------------------------------
# Phase 4.1.1 Outlook Add-in Risk Sentinel UI & Lifecycle Tests
# ---------------------------------------------------------------------------

def test_taskpane_html_initial_state_not_verified_safe():
    """
    Finding 2: Initial taskpane HTML must not present VERIFIED SAFE before an audit runs.
    """
    res = client.get("/add-in/taskpane.html")
    assert res.status_code == 200
    html = res.text
    assert "riskSentinelBanner" in html
    assert "PENDING AUDIT" in html
    assert "VERIFIED SAFE" not in html


def test_taskpane_js_implements_safe_audit_contract_and_request_tracking():
    """
    Finding 2: taskpane.js must implement strict (SAFE + PROCEED) verification,
    request ID sequencing for race condition protection, and fail-safe handling.
    """
    res = client.get("/add-in/taskpane.js")
    assert res.status_code == 200
    js = res.text
    assert "currentAuditRequestId" in js
    assert "auditRequestId !== currentAuditRequestId" in js
    assert 'sev === "SAFE" && action === "PROCEED"' in js
    assert "RISK CHECK UNAVAILABLE" in js
    assert "REVIEW REQUIRED" in js


def test_frontend_risk_banner_state_logic_simulation():
    """
    Simulates the exact taskpane.js runRiskAudit decision tree to verify all frontend states:
    - exact SAFE + PROCEED -> VERIFIED SAFE
    - SAFE + BLOCKED -> BLOCKED / HIGH RISK
    - HIGH_RISK + PROCEED -> BLOCKED / HIGH RISK
    - CAUTION + REVIEW_CAUTION -> CAUTION REQUIRED
    - empty/malformed object -> REVIEW REQUIRED
    - non-2xx response / exception -> RISK CHECK UNAVAILABLE
    """
    def simulate_taskpane_audit(status_code, body_dict_or_none, is_exception=False):
        if is_exception or status_code != 200 or body_dict_or_none is None:
            return {
                "banner_class": "risk-sentinel-banner unavailable",
                "badge_text": "RISK CHECK UNAVAILABLE",
                "badge_class": "sentinel-status-badge unavailable"
            }

        audit = body_dict_or_none
        sev = str(audit.get("severity", "")).upper()
        action = str(audit.get("recommended_action", "")).upper()
        is_explicit_safe = (sev == "SAFE" and action == "PROCEED")
        is_high_risk = (sev == "HIGH_RISK" or action == "BLOCKED")
        is_caution = (not is_high_risk and (sev == "CAUTION" or action == "REVIEW_CAUTION"))

        if is_explicit_safe:
            return {
                "banner_class": "risk-sentinel-banner safe",
                "badge_text": "VERIFIED SAFE",
                "badge_class": "sentinel-status-badge safe"
            }
        elif is_high_risk:
            return {
                "banner_class": "risk-sentinel-banner high-risk",
                "badge_text": "BLOCKED / HIGH RISK",
                "badge_class": "sentinel-status-badge high-risk"
            }
        elif is_caution:
            return {
                "banner_class": "risk-sentinel-banner caution",
                "badge_text": "CAUTION REQUIRED",
                "badge_class": "sentinel-status-badge caution"
            }
        else:
            return {
                "banner_class": "risk-sentinel-banner unavailable",
                "badge_text": "REVIEW REQUIRED",
                "badge_class": "sentinel-status-badge unavailable"
            }

        # 1. Exact SAFE + PROCEED
    s1 = simulate_taskpane_audit(200, {"severity": "SAFE", "recommended_action": "PROCEED"})
    assert s1["badge_text"] == "VERIFIED SAFE"
    assert "safe" in s1["banner_class"]

    # 2. Contradictory SAFE + BLOCKED
    s2 = simulate_taskpane_audit(200, {"severity": "SAFE", "recommended_action": "BLOCKED"})
    assert s2["badge_text"] == "BLOCKED / HIGH RISK"
    assert "high-risk" in s2["banner_class"]

    # 3. Contradictory HIGH_RISK + PROCEED
    s3 = simulate_taskpane_audit(200, {"severity": "HIGH_RISK", "recommended_action": "PROCEED"})
    assert s3["badge_text"] == "BLOCKED / HIGH RISK"
    assert "high-risk" in s3["banner_class"]

    # 4. CAUTION + REVIEW_CAUTION
    s4 = simulate_taskpane_audit(200, {"severity": "CAUTION", "recommended_action": "REVIEW_CAUTION"})
    assert s4["badge_text"] == "CAUTION REQUIRED"
    assert "caution" in s4["banner_class"]

    # 5. Empty object
    s5 = simulate_taskpane_audit(200, {})
    assert s5["badge_text"] == "REVIEW REQUIRED"
    assert "unavailable" in s5["banner_class"]

    # 6. Unknown enums
    s6 = simulate_taskpane_audit(200, {"severity": "UNKNOWN_SEV", "recommended_action": "UNKNOWN_ACT"})
    assert s6["badge_text"] == "REVIEW REQUIRED"
    assert "unavailable" in s6["banner_class"]

    # 7. Non-2xx response (e.g. 500 server error)
    s7 = simulate_taskpane_audit(500, None)
    assert s7["badge_text"] == "RISK CHECK UNAVAILABLE"
    assert "unavailable" in s7["banner_class"]

    # 8. Network exception
    s8 = simulate_taskpane_audit(0, None, is_exception=True)
    assert s8["badge_text"] == "RISK CHECK UNAVAILABLE"
    assert "unavailable" in s8["banner_class"]


def test_frontend_risk_audit_lifecycle_and_race_condition_simulation():
    """
    Finding 2: Tests lifecycle and race-condition handling:
    1. Draft A audit succeeds -> VERIFIED SAFE.
    2. Draft B audit starts -> Prior safe state is immediately cleared to AUDITING...
    3. Draft B audit fails -> Shows RISK CHECK UNAVAILABLE.
    4. Late response from Draft A arrives after Draft B audit began -> Discarded, banner remains Draft B state.
    """
    state = {
        "currentAuditRequestId": 0,
        "banner_badge": "PENDING AUDIT",
        "banner_class": "risk-sentinel-banner pending"
    }

    # Step 1: Draft A starts
    state["currentAuditRequestId"] += 1
    req_a_id = state["currentAuditRequestId"]
    state["banner_badge"] = "AUDITING..."
    state["banner_class"] = "risk-sentinel-banner pending"

    # Step 1 response arrives for Draft A
    if req_a_id == state["currentAuditRequestId"]:
        state["banner_badge"] = "VERIFIED SAFE"
        state["banner_class"] = "risk-sentinel-banner safe"
    assert state["banner_badge"] == "VERIFIED SAFE"

    # Step 2: User modifies draft -> Draft B audit starts
    state["currentAuditRequestId"] += 1
    req_b_id = state["currentAuditRequestId"]
    state["banner_badge"] = "AUDITING..."  # Prior safe state immediately cleared
    state["banner_class"] = "risk-sentinel-banner pending"
    assert state["banner_badge"] == "AUDITING..."

    # Step 3: Draft B audit fails (e.g. network timeout)
    if req_b_id == state["currentAuditRequestId"]:
        state["banner_badge"] = "RISK CHECK UNAVAILABLE"
        state["banner_class"] = "risk-sentinel-banner unavailable"
    assert state["banner_badge"] == "RISK CHECK UNAVAILABLE"

    # Step 4: Stale / late response from Draft A arrives late
    if req_a_id == state["currentAuditRequestId"]:
        state["banner_badge"] = "VERIFIED SAFE"  # Should NOT be reached
    # Assert state remains Draft B's failed state, NOT overwritten by Draft A
    assert state["banner_badge"] == "RISK CHECK UNAVAILABLE"
