"""
Unit and Security Tests for Phase 5 Deterministic Canonical Grounding Engine.
Verifies information-integrity controls, claim extraction, metric validation, and fail-closed invariants.
"""

import pytest
from backend.canonical_grounding import (
    validate_canonical_grounding,
    extract_monetary_claims,
    extract_percentage_claims,
    GroundingValidationResult,
    ClaimCategory,
    ClaimStatus,
    CANONICAL_FACT_REGISTRY,
    APPROVED_TITLES,
    APPROVED_PAST_EMPLOYERS
)
from backend.radar.risk_evaluator import (
    analyze_risk_heuristics,
    RiskCategory,
    RiskSeverity
)
from backend.models import EmailMessage, UserProfile
from backend.radar.scribe_service import generate_executive_reply, compose_grounded_response


def test_approved_quantitative_claim():
    """Approved $8M Google Cloud revenue influenced and 23% POC conversion are recognized as grounded."""
    draft1 = "Over my tenure, I influenced $8M in new Google Cloud revenue across enterprise accounts."
    res1 = validate_canonical_grounding(draft1)
    assert res1.is_grounded is True
    assert res1.requires_human_review is False
    assert len(res1.unsupported_claims) == 0
    assert "FACT_GOOGLE_REVENUE" in res1.verified_fact_ids

    draft2 = "We achieved a 23% POC-to-production conversion rate and 40% reduced scoping turnaround."
    res2 = validate_canonical_grounding(draft2)
    assert res2.is_grounded is True
    assert "FACT_PROMEVO_POC_CONVERSION" in res2.verified_fact_ids
    assert "FACT_PROMEVO_SCOPING_TURNAROUND" in res2.verified_fact_ids


def test_approved_large_scale_impact_claim():
    """Approved $100M+ enterprise revenue claim is recognized as grounded."""
    draft = "Over my career, I have influenced and delivered $100M+ in enterprise revenue across data and AI platforms."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is True
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids
    assert len(res.supported_claims) == 1


def test_invented_monetary_value():
    """Invented monetary amounts ($80M, $50M, $15M, $500K) must be rejected and flagged."""
    for bad_amount in ["$80M", "$50M", "$15M", "$500K", "$10B"]:
        draft = f"I personally managed a {bad_amount} cloud transformation portfolio."
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False
        assert res.requires_human_review is True
        assert any(u.category == ClaimCategory.MONETARY for u in res.unsupported_claims)
        assert bad_amount in res.validation_summary


def test_disallowed_qualifier_on_valid_amount():
    """Claiming 'generated $8M' or 'closed $8M' instead of 'influenced $8M' is rejected."""
    draft_gen = "I generated $8M in new Google Cloud revenue."
    res_gen = validate_canonical_grounding(draft_gen)
    assert res_gen.is_grounded is False
    assert any(u.status == ClaimStatus.DISALLOWED_QUALIFIER for u in res_gen.unsupported_claims)

    draft_close = "I closed $8M in Google Cloud revenue."
    res_close = validate_canonical_grounding(draft_close)
    assert res_close.is_grounded is False
    assert any(u.status == ClaimStatus.DISALLOWED_QUALIFIER for u in res_close.unsupported_claims)


def test_invented_percentage():
    """Invented percentages (85%, 99%, 50%, 15%) must be rejected and flagged."""
    for bad_pct in ["85%", "99%", "50%", "15%"]:
        draft = f"Our initiatives resulted in a {bad_pct} increase in cloud efficiency."
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False
        assert res.requires_human_review is True
        assert any(u.category == ClaimCategory.PERCENTAGE for u in res.unsupported_claims)


def test_wrong_employer():
    """Asserting past employment at unapproved companies (Amazon, Microsoft, Meta) must be rejected."""
    draft1 = "When I was at Amazon as Lead Cloud Architect, I built scalable solutions."
    res1 = validate_canonical_grounding(draft1)
    assert res1.is_grounded is False
    assert any(u.category == ClaimCategory.EMPLOYER for u in res1.unsupported_claims)

    draft2 = "During my time at Microsoft, I led enterprise AI engagements."
    res2 = validate_canonical_grounding(draft2)
    assert res2.is_grounded is False
    assert any(u.category == ClaimCategory.EMPLOYER for u in res2.unsupported_claims)


def test_wrong_title():
    """Asserting unapproved executive titles (CEO, CFO, VP of Sales) must be rejected."""
    draft = "As Chief Executive Officer of Promevo, I directed our AI strategy."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert any(u.category == ClaimCategory.TITLE for u in res.unsupported_claims)


def test_wrong_date_or_tenure():
    """Asserting ongoing employment at Promevo in late 2026 is rejected (Promevo ended Aug 2026)."""
    draft = "In my current role as Senior Solutions Architect at Promevo, I am leading new pilots."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert any(u.category == ClaimCategory.DATE_TENURE for u in res.unsupported_claims)


def test_supported_paraphrase():
    """Supported semantically equivalent paraphrasing is recognized as grounded."""
    draft = (
        "Throughout my advisory work across enterprise clients, I helped influence over $8M in Google Cloud revenue "
        "and have contributed to delivering more than $100M+ in total enterprise value across my career."
    )
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is True
    assert "FACT_GOOGLE_REVENUE" in res.verified_fact_ids
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids


def test_content_with_no_quantitative_claim():
    """Drafts containing only qualitative text pass validation without false-positive claim requirements."""
    draft = (
        "Hi Sarah,\n\n"
        "Thank you for reaching out regarding the Principal Solutions Architect opening. "
        "I would be glad to connect for a 15-minute introductory conversation to discuss alignment.\n\n"
        "Best regards,\nBrian Kinlaw"
    )
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is True
    assert res.requires_human_review is False
    assert len(res.supported_claims) == 0
    assert len(res.unsupported_claims) == 0


def test_malformed_model_output():
    """Malformed or non-string inputs fail gracefully and do not raise unhandled exceptions."""
    assert validate_canonical_grounding("").is_grounded is True
    assert validate_canonical_grounding(None).is_grounded is True
    assert validate_canonical_grounding(12345).is_grounded is True
    assert validate_canonical_grounding("{'raw': 'json'}").is_grounded is True


def test_unsupported_claim_mixed_with_supported_claims():
    """Draft containing a mix of valid ($8M) and invalid ($50M) claims is flagged as ungrounded."""
    draft = "I influenced $8M in Google Cloud revenue and also generated $50M in AWS revenue."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.requires_human_review is True
    assert "FACT_GOOGLE_REVENUE" in res.verified_fact_ids
    assert len(res.unsupported_claims) >= 1
    assert any("$50M" in u.extracted_text for u in res.unsupported_claims)


def test_supported_and_unsupported_claims_in_same_sentence():
    """Sentence containing both valid ($100M+) and invalid (85% cost cut) claims fails validation."""
    draft = "I delivered $100M+ in enterprise revenue while driving an 85% reduction in cloud infrastructure costs."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids
    assert any("85%" in u.extracted_text for u in res.unsupported_claims)


def test_unsupported_claim_cannot_be_labeled_verified_safe():
    """Risk Sentinel pre-screen must escalate ungrounded drafts to UNVERIFIED_CAREER_CLAIM and REVIEW_CAUTION."""
    bad_draft = "I delivered $80M in cloud migrations."
    risk_res = analyze_risk_heuristics(
        email_text="Looking for a cloud architect.",
        draft_text=bad_draft,
        action="DRAFT"
    )
    assert risk_res.severity in [RiskSeverity.CAUTION, RiskSeverity.HIGH_RISK]
    assert risk_res.recommended_action in ["REVIEW_CAUTION", "BLOCKED"]
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in risk_res.detected_categories
    assert risk_res.recommended_action != "PROCEED"


def test_grounding_success_does_not_create_or_invoke_transmission():
    """Valid canonical grounding does not grant transmission authorization or create send paths."""
    good_draft = "I influenced $8M in Google Cloud revenue and delivered $100M+ across my career."
    val = validate_canonical_grounding(good_draft)
    assert val.is_grounded is True

    # Even with perfectly grounded draft, SEND action remains HIGH_RISK + BLOCKED
    risk_res = analyze_risk_heuristics(
        email_text="Looking for a cloud architect.",
        draft_text=good_draft,
        action="SEND"
    )
    assert risk_res.severity == RiskSeverity.HIGH_RISK
    assert risk_res.recommended_action == "BLOCKED"
    assert RiskCategory.AUTONOMOUS_SEND_POLICY in risk_res.detected_categories
