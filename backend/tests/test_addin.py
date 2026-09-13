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
