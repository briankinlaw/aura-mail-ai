"""
Unit and integration tests for Gemini Risk Sentinel and Second Opinion Evaluator.
Phase 4: Monotonic Non-Downgradable Risk Architecture Verification.
"""

from unittest.mock import MagicMock, patch
import json
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import EmailMessage
from backend.safety_policy import MailAction, ExecutionContext
from backend.radar.risk_evaluator import (
    evaluate_second_opinion_risk,
    analyze_risk_heuristics,
    merge_risk_assessments,
    RiskSeverity,
    RiskCategory,
    RiskAssessmentResult
)
from backend.auth import get_auth_headers

client = TestClient(app)
client.headers.update(get_auth_headers())


# ---------------------------------------------------------------------------
# 1. Baseline Heuristic Tests
# ---------------------------------------------------------------------------

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
    result = analyze_risk_heuristics(email.body_text, draft, action="DRAFT")
    assert result.severity == RiskSeverity.SAFE
    assert result.is_flagged is False
    assert result.recommended_action == "PROCEED"
    assert result.detected_categories == [RiskCategory.CLEAN]


def test_legitimate_draft_generation_is_safe():
    """Tests that legitimate draft generation with safe staging actions passes cleanly."""
    email_text = "Subject: Introduction\nFrom: recruiter@example.com\n\nWe saw your background in cloud architecture."
    draft_text = "Thank you for reaching out. I would be happy to discuss further."
    result = analyze_risk_heuristics(
        email_text=email_text,
        draft_text=draft_text,
        action=MailAction.CREATE_DRAFT,
        execution_context=ExecutionContext.OUTLOOK_INTERACTIVE_USER
    )
    assert result.severity == RiskSeverity.SAFE
    assert result.recommended_action == "PROCEED"
    assert result.is_flagged is False
    assert RiskCategory.CLEAN in result.detected_categories


def test_unverified_metric_flagged():
    """Tests that an unapproved metric or phrase ('generated $8M' or '$80M') triggers an UNVERIFIED_CAREER_CLAIM flag."""
    email = EmailMessage(
        id="risk_test_unverified",
        subject="Staff Architect Role",
        sender_name="Alex",
        sender_email="alex@firm.com",
        body_text="Looking for a cloud leader."
    )
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
    assert result.recommended_action == "BLOCKED"


def test_premature_compensation_commitment_flagged():
    """Tests that premature contractual or binding salary commitments in drafts trigger CONTRACT_LEGAL_COMMITMENT."""
    email_text = "What is your rate?"
    draft_text = "I accept this offer and I will sign for $250k right now."
    result = analyze_risk_heuristics(email_text, draft_text)
    assert result.is_flagged is True
    assert RiskCategory.CONTRACT_LEGAL_COMMITMENT in result.detected_categories
    assert result.severity == RiskSeverity.HIGH_RISK
    assert result.recommended_action == "BLOCKED"


# ---------------------------------------------------------------------------
# 2. Autonomous-Send and Context-Based Policy Tests (No 'auto_pilot' string dependency)
# ---------------------------------------------------------------------------

def test_autonomous_send_detection_does_not_depend_on_string():
    """
    Tests that proposed transmission actions trigger AUTONOMOUS_SEND_POLICY
    WITHOUT requiring the literal string 'auto_pilot' anywhere in the content.
    """
    email_text = "Subject: Interview\nFrom: hr@company.com\n\nAre you available tomorrow?"
    draft_text = "Yes, I am available at 2 PM."

    # None of the texts contain 'auto_pilot'
    assert "auto_pilot" not in (email_text + draft_text).lower()

    # Sending with action='SEND'
    res1 = analyze_risk_heuristics(email_text, draft_text, action="SEND")
    assert res1.is_flagged is True
    assert RiskCategory.AUTONOMOUS_SEND_POLICY in res1.detected_categories
    assert res1.severity == RiskSeverity.HIGH_RISK
    assert res1.recommended_action == "BLOCKED"

    # Sending with MailAction.SEND_EMAIL enum
    res2 = analyze_risk_heuristics(email_text, draft_text, action=MailAction.SEND_EMAIL)
    assert res2.is_flagged is True
    assert RiskCategory.AUTONOMOUS_SEND_POLICY in res2.detected_categories
    assert res2.severity == RiskSeverity.HIGH_RISK
    assert res2.recommended_action == "BLOCKED"


def test_background_send_request_blocked():
    """Tests that a background execution context attempting SEND is blocked with context attribution."""
    email_text = "Subject: Status\n\nChecking status."
    draft_text = "Status update ready."
    result = analyze_risk_heuristics(
        email_text=email_text,
        draft_text=draft_text,
        action="SEND",
        execution_context=ExecutionContext.BACKGROUND_RADAR
    )
    assert result.is_flagged is True
    assert RiskCategory.AUTONOMOUS_SEND_POLICY in result.detected_categories
    assert result.severity == RiskSeverity.HIGH_RISK
    assert result.recommended_action == "BLOCKED"
    assert any("BACKGROUND_RADAR" in w for w in result.guardrail_warnings)


# ---------------------------------------------------------------------------
# 3. Monotonicity & Second-Opinion Non-Downgradable Architecture Tests
# ---------------------------------------------------------------------------

def test_monotonicity_heuristic_high_gemini_safe():
    """
    Security Invariant: Deterministic HIGH_RISK cannot be downgraded to SAFE by Gemini.
    """
    heuristic_res = RiskAssessmentResult(
        severity=RiskSeverity.HIGH_RISK,
        is_flagged=True,
        risk_score=85,
        detected_categories=[RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING],
        recommended_action="BLOCKED",
        guardrail_warnings=["Shortened URL detected."],
        second_opinion_summary="Heuristic flag."
    )

    gemini_res = RiskAssessmentResult(
        severity=RiskSeverity.SAFE,
        is_flagged=False,
        risk_score=0,
        detected_categories=[RiskCategory.CLEAN],
        recommended_action="PROCEED",
        guardrail_warnings=[],
        second_opinion_summary="Gemini claims everything is safe."
    )

    merged = merge_risk_assessments(heuristic_res, gemini_res)
    assert merged.severity == RiskSeverity.HIGH_RISK
    assert merged.recommended_action == "BLOCKED"
    assert merged.is_flagged is True
    assert merged.risk_score >= 85
    assert RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in merged.detected_categories
    assert RiskCategory.CLEAN not in merged.detected_categories
    assert "Shortened URL detected." in merged.guardrail_warnings


def test_monotonicity_heuristic_blocked_gemini_proceed():
    """
    Security Invariant: Deterministic BLOCKED action cannot be converted to PROCEED by Gemini.
    """
    heuristic_res = RiskAssessmentResult(
        severity=RiskSeverity.HIGH_RISK,
        is_flagged=True,
        risk_score=85,
        detected_categories=[RiskCategory.AUTONOMOUS_SEND_POLICY],
        recommended_action="BLOCKED",
        guardrail_warnings=["Direct send forbidden."]
    )

    gemini_res = RiskAssessmentResult(
        severity=RiskSeverity.SAFE,
        is_flagged=False,
        risk_score=5,
        detected_categories=[RiskCategory.CLEAN],
        recommended_action="PROCEED",
        guardrail_warnings=[]
    )

    merged = merge_risk_assessments(heuristic_res, gemini_res)
    assert merged.recommended_action == "BLOCKED"
    assert merged.severity == RiskSeverity.HIGH_RISK
    assert merged.is_flagged is True


def test_monotonicity_suspicious_link_never_cleared():
    """
    Security Invariant: An identified suspicious link finding is never converted to CLEAN.
    """
    heuristic_res = RiskAssessmentResult(
        severity=RiskSeverity.HIGH_RISK,
        is_flagged=True,
        risk_score=90,
        detected_categories=[RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING],
        recommended_action="BLOCKED",
        guardrail_warnings=["Malicious URL pattern bit.ly found."]
    )

    gemini_res = RiskAssessmentResult(
        severity=RiskSeverity.SAFE,
        is_flagged=False,
        risk_score=0,
        detected_categories=[RiskCategory.CLEAN],
        recommended_action="PROCEED",
        guardrail_warnings=[]
    )

    merged = merge_risk_assessments(heuristic_res, gemini_res)
    assert RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in merged.detected_categories
    assert RiskCategory.CLEAN not in merged.detected_categories


def test_monotonicity_gemini_adds_stronger_warning_and_upgrades():
    """
    Tests that Gemini CAN upgrade severity and add new categories/warnings to a SAFE heuristic baseline.
    """
    heuristic_res = RiskAssessmentResult(
        severity=RiskSeverity.SAFE,
        is_flagged=False,
        risk_score=5,
        detected_categories=[RiskCategory.CLEAN],
        recommended_action="PROCEED",
        guardrail_warnings=[]
    )

    gemini_res = RiskAssessmentResult(
        severity=RiskSeverity.HIGH_RISK,
        is_flagged=True,
        risk_score=95,
        detected_categories=[RiskCategory.PRIVACY_DATA_EXFILTRATION],
        recommended_action="BLOCKED",
        guardrail_warnings=["Proprietary internal system topology referenced in draft."],
        second_opinion_summary="Gemini detected confidential data leakage."
    )

    merged = merge_risk_assessments(heuristic_res, gemini_res)
    assert merged.severity == RiskSeverity.HIGH_RISK
    assert merged.recommended_action == "BLOCKED"
    assert merged.is_flagged is True
    assert merged.risk_score >= 95
    assert RiskCategory.PRIVACY_DATA_EXFILTRATION in merged.detected_categories
    assert RiskCategory.CLEAN not in merged.detected_categories
    assert "Proprietary internal system topology referenced in draft." in merged.guardrail_warnings


def test_monotonicity_merges_multiple_warnings_without_loss():
    """Tests that heuristic warnings and Gemini warnings are both preserved and deduplicated."""
    heuristic_res = RiskAssessmentResult(
        severity=RiskSeverity.CAUTION,
        is_flagged=True,
        risk_score=50,
        detected_categories=[RiskCategory.UNVERIFIED_CAREER_CLAIM],
        recommended_action="REVIEW_CAUTION",
        guardrail_warnings=["Warning A: Claim unverified."]
    )

    gemini_res = RiskAssessmentResult(
        severity=RiskSeverity.HIGH_RISK,
        is_flagged=True,
        risk_score=85,
        detected_categories=[RiskCategory.COMPENSATION_NEGOTIATION],
        recommended_action="BLOCKED",
        guardrail_warnings=["Warning A: Claim unverified.", "Warning B: Unapproved salary floor stated."]
    )

    merged = merge_risk_assessments(heuristic_res, gemini_res)
    assert merged.severity == RiskSeverity.HIGH_RISK
    assert merged.recommended_action == "BLOCKED"
    assert len(merged.guardrail_warnings) == 2
    assert "Warning A: Claim unverified." in merged.guardrail_warnings
    assert "Warning B: Unapproved salary floor stated." in merged.guardrail_warnings
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in merged.detected_categories
    assert RiskCategory.COMPENSATION_NEGOTIATION in merged.detected_categories


# ---------------------------------------------------------------------------
# 4. Fail-Closed Fallback & Robustness Tests
# ---------------------------------------------------------------------------

def test_gemini_unavailable_preserves_deterministic_findings():
    """Tests that when Gemini client is unavailable (e.g. no API key), heuristic findings are preserved."""
    msg = EmailMessage(
        id="test_no_client",
        subject="Phishing note",
        sender_name="Bad Guy",
        sender_email="bad@phish.com",
        body_text="Click http://bit.ly/malicious"
    )
    with patch("backend.radar.risk_evaluator.get_gemini_client", return_value=None):
        result = evaluate_second_opinion_risk(email=msg, proposed_action="DRAFT")
        assert result.severity == RiskSeverity.HIGH_RISK
        assert result.recommended_action == "BLOCKED"
        assert RiskCategory.SUSPICIOUS_LINK_OR_SPOOFING in result.detected_categories


def test_malformed_gemini_json_fails_closed():
    """Tests that malformed JSON from Gemini fails closed and retains heuristic findings."""
    msg = EmailMessage(
        id="test_bad_json",
        subject="Legit note",
        sender_name="Alex",
        sender_email="alex@firm.com",
        body_text="Hi Brian, please review our spec."
    )
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "{not valid json at all... [ERROR"
    mock_client.models.generate_content.return_value = mock_resp

    with patch("backend.radar.risk_evaluator.get_gemini_client", return_value=mock_client):
        result = evaluate_second_opinion_risk(email=msg, proposed_action="DRAFT")
        assert result.severity == RiskSeverity.SAFE
        assert result.recommended_action == "PROCEED"
        assert "deterministic baseline enforced" in result.second_opinion_summary


def test_gemini_timeout_fallback():
    """Tests that network/timeout exceptions from Gemini fail closed and preserve findings."""
    msg = EmailMessage(
        id="test_timeout",
        subject="Opportunity",
        sender_name="Recruiter",
        sender_email="rec@example.com",
        body_text="Offer for you."
    )
    # Draft contains binding commitment (heuristic HIGH_RISK)
    draft = "I accept this offer and guarantee I can start on Monday."

    mock_client = MagicMock()
    mock_client.models.generate_content.side_effect = TimeoutError("Deadline exceeded connecting to Gemini")

    with patch("backend.radar.risk_evaluator.get_gemini_client", return_value=mock_client):
        result = evaluate_second_opinion_risk(email=msg, draft_reply=draft, proposed_action="DRAFT")
        assert result.severity == RiskSeverity.HIGH_RISK
        assert result.recommended_action == "BLOCKED"
        assert RiskCategory.CONTRACT_LEGAL_COMMITMENT in result.detected_categories
        assert result.is_flagged is True


# ---------------------------------------------------------------------------
# 5. API Endpoint Integration Test
# ---------------------------------------------------------------------------

def test_risk_check_api_endpoint():
    """Tests the /api/radar/risk-check endpoint integration."""
    payload = {
        "subject": "Executive Architect Search",
        "body": "Hi Brian, are you open to discussing an executive role?",
        "sender_name": "Jordan Lee",
        "sender_email": "jordan@talentexec.com",
        "draft_reply": "Thank you for reaching out. I have influenced and delivered $100M+ across my career.",
        "proposed_action": "DRAFT",
        "execution_context": "OUTLOOK_INTERACTIVE_USER"
    }
    res = client.post("/api/radar/risk-check", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "severity" in data
    assert "second_opinion_summary" in data
    assert "detected_categories" in data
    assert "recommended_action" in data
    assert data["severity"] in ["SAFE", "CAUTION", "HIGH_RISK"]
    assert data["recommended_action"] in ["PROCEED", "REVIEW_CAUTION", "BLOCKED"]
