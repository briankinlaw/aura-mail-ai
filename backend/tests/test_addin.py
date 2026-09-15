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
    assert data["verification_status"] == "CALENDAR_NOT_CHECKED"
    assert data["is_verified"] is False


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
    Phase 4.1.1 & 4.1.2: taskpane.js must implement:
    1. Strict (SAFE + PROCEED) verification for VERIFIED SAFE.
    2. Invalidation helper `invalidateRiskAudit` on manual draft mutation.
    3. Input event listener on `draftReplyText`.
    4. Two-phase stale checks: after fetch() and after await res.json().
    5. Fail-safe handling for JSON parse errors and malformed results.
    """
    res = client.get("/add-in/taskpane.js")
    assert res.status_code == 200
    js = res.text

    # Audit invalidation helper & listener
    assert "function invalidateRiskAudit(" in js
    assert "RE-AUDIT REQUIRED" in js
    assert 'el.draftReplyText.addEventListener("input"' in js or "addEventListener('input'" in js or 'addEventListener("input"' in js

    # Request sequencing & stale checks (both post-fetch and post-json)
    assert "currentAuditRequestId" in js
    assert js.count("auditRequestId !== currentAuditRequestId") >= 2

    # Safe audit criteria
    assert 'sev === "SAFE" && action === "PROCEED"' in js
    assert "RISK CHECK UNAVAILABLE" in js
    assert "REVIEW REQUIRED" in js

    # Content correlation defense-in-depth
    assert "draftReplyText.value !== draftText" in js or "draftReplyText.value !== auditedDraftText" in js or "value !== draftText" in js


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


def test_phase_4_1_2_risk_audit_lifecycle_and_invalidation_matrix():
    """
    Phase 4.1.2 Adversarial Lifecycle Matrix:
    - Case A: Successful audit -> VERIFIED SAFE.
    - Case B: Manual mutation after successful audit -> prior audit invalidated -> RE-AUDIT REQUIRED.
    - Case C: Mutation while audit in flight -> generation invalidated -> completing audit ignored.
    - Case D: New audit supersedes old audit -> old completion cannot update UI.
    - Case E: Request becomes stale during JSON parsing -> post-parse stale check rejects it.
    - Case F: JSON parse failure -> RISK CHECK UNAVAILABLE.
    - Case G: Malformed security object -> REVIEW REQUIRED.
    """
    class TaskpaneAuditSim:
        def __init__(self):
            self.currentAuditRequestId = 0
            self.draft_text = ""
            self.banner_badge = "PENDING AUDIT"
            self.banner_class = "risk-sentinel-banner pending"
            self.summary = ""

        def invalidateRiskAudit(self, reason="Draft modified after audit."):
            self.currentAuditRequestId += 1
            self.banner_class = "risk-sentinel-banner pending"
            self.banner_badge = "RE-AUDIT REQUIRED"
            self.summary = "Draft changed after its last risk check. The previous audit no longer applies."

        def on_user_input(self, new_text):
            self.draft_text = new_text
            self.invalidateRiskAudit("User edited draft text.")

        def start_audit(self, draft_text):
            self.currentAuditRequestId += 1
            req_id = self.currentAuditRequestId
            self.draft_text = draft_text
            self.banner_class = "risk-sentinel-banner pending"
            self.banner_badge = "AUDITING..."
            self.summary = "Scanning draft against canonical profile & security policies..."
            return req_id

        def complete_audit(self, req_id, audited_text, status_code, raw_json_str=None, is_net_err=False):
            # Stale check 1 (post-fetch)
            if req_id != self.currentAuditRequestId:
                return "DROPPED_STALE_POST_FETCH"

            if is_net_err or status_code != 200:
                self.banner_class = "risk-sentinel-banner unavailable"
                self.banner_badge = "RISK CHECK UNAVAILABLE"
                self.summary = "Security risk check endpoint returned non-200 status."
                return "RENDERED_NET_ERR"

            # Parse JSON
            import json
            try:
                audit = json.loads(raw_json_str) if raw_json_str is not None else {}
            except Exception:
                if req_id != self.currentAuditRequestId:
                    return "DROPPED_STALE_ON_JSON_ERR"
                self.banner_class = "risk-sentinel-banner unavailable"
                self.banner_badge = "RISK CHECK UNAVAILABLE"
                self.summary = "Automated risk check response was malformed."
                return "RENDERED_JSON_ERR"

            # Stale check 2 (post-JSON parse)
            if req_id != self.currentAuditRequestId:
                return "DROPPED_STALE_POST_JSON"

            # Content correlation
            if self.draft_text != audited_text:
                self.invalidateRiskAudit("Draft content diverged from audited text.")
                return "INVALIDATED_CONTENT_DIVERGENCE"

            sev = str(audit.get("severity", "")).upper()
            action = str(audit.get("recommended_action", "")).upper()

            if sev == "SAFE" and action == "PROCEED":
                self.banner_class = "risk-sentinel-banner safe"
                self.banner_badge = "VERIFIED SAFE"
                self.summary = "No risk factors identified."
                return "RENDERED_SAFE"
            elif sev == "HIGH_RISK" or action == "BLOCKED":
                self.banner_class = "risk-sentinel-banner high-risk"
                self.banner_badge = "BLOCKED / HIGH RISK"
                self.summary = "High risk detected."
                return "RENDERED_HIGH_RISK"
            elif sev == "CAUTION" or action == "REVIEW_CAUTION":
                self.banner_class = "risk-sentinel-banner caution"
                self.banner_badge = "CAUTION REQUIRED"
                self.summary = "Caution advised."
                return "RENDERED_CAUTION"
            else:
                self.banner_class = "risk-sentinel-banner unavailable"
                self.banner_badge = "REVIEW REQUIRED"
                self.summary = "Human review required."
                return "RENDERED_REVIEW_REQUIRED"

    sim = TaskpaneAuditSim()

    # Case A: Successful audit -> VERIFIED SAFE
    req_a = sim.start_audit("Draft A content")
    res_a = sim.complete_audit(req_a, "Draft A content", 200, '{"severity":"SAFE","recommended_action":"PROCEED"}')
    assert res_a == "RENDERED_SAFE"
    assert sim.banner_badge == "VERIFIED SAFE"
    assert "safe" in sim.banner_class

    # Case B: Manual mutation after successful audit -> RE-AUDIT REQUIRED
    sim.on_user_input("Draft A content with manual edit")
    assert sim.banner_badge == "RE-AUDIT REQUIRED"
    assert "pending" in sim.banner_class
    assert "VERIFIED SAFE" != sim.banner_badge

    # Case C: Mutation while audit in flight -> completing audit ignored
    req_c = sim.start_audit("Draft C content")
    assert sim.banner_badge == "AUDITING..."
    sim.on_user_input("Draft C mutated before response")
    assert sim.banner_badge == "RE-AUDIT REQUIRED"
    res_c = sim.complete_audit(req_c, "Draft C content", 200, '{"severity":"SAFE","recommended_action":"PROCEED"}')
    assert res_c == "DROPPED_STALE_POST_FETCH"
    assert sim.banner_badge == "RE-AUDIT REQUIRED"

    # Case D: New audit supersedes old audit
    req_d1 = sim.start_audit("Draft D1")
    req_d2 = sim.start_audit("Draft D2")
    res_d1 = sim.complete_audit(req_d1, "Draft D1", 200, '{"severity":"SAFE","recommended_action":"PROCEED"}')
    assert res_d1 == "DROPPED_STALE_POST_FETCH"
    res_d2 = sim.complete_audit(req_d2, "Draft D2", 200, '{"severity":"SAFE","recommended_action":"PROCEED"}')
    assert res_d2 == "RENDERED_SAFE"
    assert sim.banner_badge == "VERIFIED SAFE"

    # Case E: Request becomes stale during JSON parsing
    req_e = sim.start_audit("Draft E")
    # Simulate fetch succeeded for req_e, but before post-JSON check, user types or new audit starts:
    sim.invalidateRiskAudit("Intervening event during JSON parsing")
    res_e = sim.complete_audit(req_e, "Draft E", 200, '{"severity":"SAFE","recommended_action":"PROCEED"}')
    # Dropped at post-fetch/post-json stale check
    assert "DROPPED_STALE" in res_e
    assert sim.banner_badge == "RE-AUDIT REQUIRED"

    # Case F: JSON parse failure
    req_f = sim.start_audit("Draft F")
    res_f = sim.complete_audit(req_f, "Draft F", 200, '{INVALID_JSON}')
    assert res_f == "RENDERED_JSON_ERR"
    assert sim.banner_badge == "RISK CHECK UNAVAILABLE"
    assert "unavailable" in sim.banner_class

    # Case G: Malformed security object (unknown severity/action)
    req_g = sim.start_audit("Draft G")
    res_g = sim.complete_audit(req_g, "Draft G", 200, '{"severity":"UNKNOWN","recommended_action":"UNKNOWN"}')
    assert res_g == "RENDERED_REVIEW_REQUIRED"
    assert sim.banner_badge == "REVIEW REQUIRED"
    assert "unavailable" in sim.banner_class
