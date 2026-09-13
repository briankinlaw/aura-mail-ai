"""
Unit tests for Gemini Risk Sentinel and Second Opinion Evaluator.
"""

from fastapi.testclient import TestClient
from backend.main import app
from backend.models import EmailMessage
from backend.radar.risk_evaluator import (
    evaluate_second_opinion_risk,
    analyze_risk_heuristics,
    RiskSeverity,
    RiskCategory
)
from backend.auth import get_auth_headers

client = TestClient(app)
client.headers.update(get_auth_headers())

def test_safe_grounded_interaction():
    """Tests that a standard, strictly grounded interaction is evaluated as SAFE."""
    email = EmailMessage(
        id="risk_test_safe",
        subject="Senior Solutions Architect Opportunity",
        sender_name="Alex Recruiter",
        sender_email="alex@legitfirm.com",
        body_text="Hi Brian, we have an opening for an Enterprise Architect at our firm. Could you send your resume?"
    )
    draft = (
        "Hi Alex,\n\n"
        "Thank you for reaching out. Over my career, I have influenced and delivered $100M+ in enterprise revenue, "
        "including influencing $8M in new Google Cloud revenue.\n\n"
        "I have attached my updated resume. Let me know if you would like to connect for 15 minutes."
    )
    result = analyze_risk_heuristics(email.body_text, draft)
    assert result.severity == RiskSeverity.SAFE
    assert result.is_flagged is False
    assert result.recommended_action == "PROCEED"


def test_unverified_metric_flagged():
    """Tests that an unapproved metric or phrase ('generated $8M' or '$80M') triggers an UNVERIFIED_CAREER_CLAIM flag."""
    email = EmailMessage(
        id="risk_test_unverified",
        subject="Staff Architect Role",
        sender_name="Alex",
        sender_email="alex@firm.com",
        body_text="Looking for a cloud leader."
    )
    # Violates approved phrasing ('generated $8M' instead of 'influenced $8M')
    draft = "I generated $8M in new revenue single-handedly."
    result = analyze_risk_heuristics(email.body_text, draft)
    assert result.is_flagged is True
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in result.detected_categories
    assert result.severity in [RiskSeverity.CAUTION, RiskSeverity.HIGH_RISK]


def test_suspicious_phishing_link_flagged():
    """Tests that phishing links or shortened URLs in inbound emails trigger SUSPICIOUS_LINK_OR_SPOOFING."""
    email_text = "Click here to view the job spec: http://bit.ly/fake-malware-link"
    draft_text = "Thank you for the note."
    result = analyze_risk_heuristics(email_text, draft_text)
    assert result.is_flagged is True
    assert RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in result.detected_categories
    assert result.severity == RiskSeverity.HIGH_RISK


def test_premature_compensation_commitment_flagged():
    """Tests that premature contractual or binding salary commitments in drafts trigger CONTRACT_LEGAL_COMMITMENT."""
    email_text = "What is your rate?"
    draft_text = "I accept this offer and I will sign for $250k right now."
    result = analyze_risk_heuristics(email_text, draft_text)
    assert result.is_flagged is True
    assert RiskCategory.CONTRACT_LEGAL_COMMITMENT in result.detected_categories


def test_risk_check_api_endpoint():
    """Tests the /api/radar/risk-check endpoint integration."""
    payload = {
        "subject": "Executive Architect Search",
        "body": "Hi Brian, are you open to discussing an executive role?",
        "sender_name": "Jordan Lee",
        "sender_email": "jordan@talentexec.com",
        "draft_reply": "Thank you for reaching out. I have influenced and delivered $100M+ across my career.",
        "proposed_action": "DRAFT"
    }
    res = client.post("/api/radar/risk-check", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "severity" in data
    assert "second_opinion_summary" in data
    assert "detected_categories" in data
    assert data["severity"] in ["SAFE", "CAUTION", "HIGH_RISK"]
