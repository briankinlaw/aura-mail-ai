"""
Unit and Security Tests for Phase 5.1 Deterministic Canonical Grounding Remediation.
Verifies multi-dimensional factual tuple validation, strict contextual isolation,
preservation of precision modifiers ('+'), rejection of unapproved employers/titles/dates,
fail-closed behavior on malformed input, Scribe fallback revalidation, monotonic Risk Sentinel
integration, and mail transmission isolation.
"""

import pytest
from unittest.mock import MagicMock, patch

from backend.canonical_grounding import (
    validate_canonical_grounding,
    extract_monetary_claims,
    extract_percentage_claims,
    extract_first_person_employment_claims,
    GroundingValidationResult,
    GroundingStatus,
    ClaimCategory,
    ClaimStatus,
    CANONICAL_FACT_REGISTRY,
    CANONICAL_EMPLOYMENT_RECORDS,
    AUTHORITATIVE_CAREER_TITLES,
    APPROVED_TITLES,
    APPROVED_PAST_EMPLOYERS
)
from backend.radar.risk_evaluator import (
    analyze_risk_heuristics,
    evaluate_second_opinion_risk,
    merge_risk_assessments,
    RiskCategory,
    RiskSeverity,
    RiskAssessmentResult
)
from backend.models import (
    EmailMessage,
    UserProfile,
    RecruiterDetails,
    ClassificationResult,
    ReplyDraftRequest
)
from backend.radar.scribe_service import generate_executive_reply, compose_grounded_response
from backend.safety_policy import MailAction, ExecutionContext


# ===========================================================================
# 8.1 Approved Canonical Claims & Paraphrases
# ===========================================================================

def test_approved_quantitative_claims():
    """Approved $8M Google Cloud revenue influenced and percentage metrics pass as grounded."""
    draft1 = "Over my career, I influenced $8M in new Google Cloud revenue across enterprise accounts."
    res1 = validate_canonical_grounding(draft1)
    assert res1.is_grounded is True
    assert res1.status == GroundingStatus.GROUNDED
    assert res1.requires_human_review is False
    assert len(res1.unsupported_claims) == 0
    assert "FACT_GOOGLE_REVENUE" in res1.verified_fact_ids

    draft2 = "We achieved a 23% POC-to-production conversion rate and 40% reduced scoping turnaround."
    res2 = validate_canonical_grounding(draft2)
    assert res2.is_grounded is True
    assert res2.status == GroundingStatus.GROUNDED
    assert "FACT_PROMEVO_POC_CONVERSION" in res2.verified_fact_ids
    assert "FACT_PROMEVO_SCOPING_TURNAROUND" in res2.verified_fact_ids


def test_approved_large_scale_impact_claim_with_required_plus():
    """Approved $100M+ enterprise revenue claim with raw '+' modifier is recognized as grounded."""
    draft = "Over my career, I have influenced and delivered $100M+ in enterprise revenue across data and AI platforms."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids
    assert len(res.supported_claims) >= 1
    assert len(res.unsupported_claims) == 0


def test_approved_employer_title_tenure_relationships():
    """Approved canonical employers and authorized titles pass validation."""
    draft_cdw = "During my time as Principal Solutions Architect at CDW, I closed $2.1M in services."
    res_cdw = validate_canonical_grounding(draft_cdw)
    assert res_cdw.is_grounded is True
    assert res_cdw.status == GroundingStatus.GROUNDED
    assert "FACT_CDW_SERVICES" in res_cdw.verified_fact_ids

    draft_dxc = "At DXC Technology, I oversaw a $22M portfolio with shared GTM P&L responsibility."
    res_dxc = validate_canonical_grounding(draft_dxc)
    assert res_dxc.is_grounded is True
    assert res_dxc.status == GroundingStatus.GROUNDED
    assert "FACT_DXC_PORTFOLIO" in res_dxc.verified_fact_ids

    draft_maven = "I currently work as Strategic Advisor, Data & AI at MavenCode."
    res_maven = validate_canonical_grounding(draft_maven)
    assert res_maven.is_grounded is True


def test_supported_paraphrase_preserving_all_dimensions():
    """Supported semantically equivalent paraphrasing is recognized as grounded when all dimensions match."""
    draft = (
        "Throughout my advisory work across enterprise clients, I helped influence over $8M in Google Cloud revenue "
        "and have contributed to delivering more than $100M+ in total enterprise value across my career."
    )
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.GROUNDED
    assert "FACT_GOOGLE_REVENUE" in res.verified_fact_ids
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids


def test_content_with_no_career_sensitive_claims():
    """Valid non-empty prose containing no career claims passes with NO_CAREER_CLAIMS status."""
    draft = (
        "Hi Sarah,\n\n"
        "Thank you for reaching out regarding the Principal Solutions Architect opening. "
        "I would be glad to connect for a 15-minute introductory conversation to discuss alignment.\n\n"
        "Best regards,\nBrian Kinlaw"
    )
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is True
    assert res.status == GroundingStatus.NO_CAREER_CLAIMS
    assert res.requires_human_review is False
    assert len(res.supported_claims) == 0
    assert len(res.unsupported_claims) == 0


# ===========================================================================
# 8.2 Numeric-Context Substitution Attacks (Independent Review Reproductions)
# ===========================================================================

def test_attack_amazon_generated_4m():
    """'At Amazon, I generated $4M in annual revenue' must be rejected (CDW fact, influenced only, CDW employer)."""
    draft = "At Amazon, I generated $4M in annual revenue."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.status in [ClaimStatus.MISATTRIBUTED, ClaimStatus.DISALLOWED_QUALIFIER] for u in res.unsupported_claims)


def test_attack_customer_satisfaction_23_percent():
    """'I improved customer satisfaction by 23%' must be rejected (23% is strictly POC-to-production conversion)."""
    draft = "I improved customer satisfaction by 23%."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.category == ClaimCategory.PERCENTAGE for u in res.unsupported_claims)


def test_attack_personally_booked_100m_at_promevo():
    """'I personally booked $100M+ at Promevo' must be rejected (career-wide influenced, not personal Promevo booking)."""
    draft = "I personally booked $100M+ at Promevo."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.status == ClaimStatus.DISALLOWED_QUALIFIER for u in res.unsupported_claims)


def test_attack_meta_salary_2_1m():
    """'I earned $2.1M in salary at Meta' must be rejected ($2.1M is CDW services closed, not salary or Meta)."""
    draft = "I earned $2.1M in salary at Meta."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.status in [ClaimStatus.DISALLOWED_QUALIFIER, ClaimStatus.MISATTRIBUTED] for u in res.unsupported_claims)


def test_attack_reduced_headcount_40_percent():
    """'I reduced headcount by 40%' must be rejected (40% is strictly reduced scoping turnaround)."""
    draft = "I reduced headcount by 40% across our engineering organization."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.category == ClaimCategory.PERCENTAGE for u in res.unsupported_claims)


def test_attack_increased_revenue_20_percent():
    """'I increased revenue by 20%' must be rejected (20% is strictly shorter sales cycles)."""
    draft = "I increased revenue by 20% in my first quarter."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.category == ClaimCategory.PERCENTAGE for u in res.unsupported_claims)


def test_attack_personal_sales_quota_22m():
    """'I managed a $22M personal sales quota' must be rejected ($22M is DXC portfolio with shared GTM P&L)."""
    draft = "I managed a $22M personal sales quota at DXC."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.status == ClaimStatus.DISALLOWED_QUALIFIER for u in res.unsupported_claims)


def test_attack_generated_or_closed_8m_google_revenue():
    """'I generated $8M in Google Cloud revenue' and 'I closed $8M' must be rejected (must be 'influenced')."""
    for bad_verb in ["generated", "closed", "sold", "booked", "earned"]:
        draft = f"I {bad_verb} $8M in Google Cloud revenue."
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False
        assert res.status == GroundingStatus.UNGROUNDED
        assert res.requires_human_review is True
        assert any(u.status == ClaimStatus.DISALLOWED_QUALIFIER for u in res.unsupported_claims)


# ===========================================================================
# 8.3 Precision and Qualifier Preservation Tests
# ===========================================================================

def test_missing_plus_on_100m_is_rejected():
    """'I delivered $100M in enterprise revenue' (omitting '+') must fail closed."""
    draft = "I delivered $100M in enterprise revenue."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.status == ClaimStatus.INSUFFICIENT_PRECISION for u in res.unsupported_claims)


def test_missing_plus_on_2m_pipeline_is_rejected():
    """'Pipeline contribution estimated $2M at Promevo' (omitting '+') must fail closed."""
    draft = "I delivered estimated $2M in pipeline contribution at Promevo."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.status == ClaimStatus.INSUFFICIENT_PRECISION for u in res.unsupported_claims)


def test_invented_monetary_values_fail():
    """Invented monetary amounts ($80M, $50M, $15M, $500K) must be rejected."""
    for bad_amount in ["$80M", "$50M", "$15M", "$500K", "$10B"]:
        draft = f"I personally managed a {bad_amount} cloud transformation portfolio."
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False
        assert res.status == GroundingStatus.UNGROUNDED
        assert res.requires_human_review is True
        assert any(u.category == ClaimCategory.MONETARY for u in res.unsupported_claims)


# ===========================================================================
# 8.4 Employer Verification (Positive and Negative)
# ===========================================================================

def test_unapproved_employers_rejected_without_denylist():
    """Asserting employment at arbitrary non-canonical companies must fail."""
    test_cases = [
        "When I was at Amazon, I built enterprise architectures.",
        "During my tenure at Microsoft, I led cloud initiatives.",
        "I worked at Stripe as a solutions engineer.",
        "I worked at Palantir from 2020 to 2022.",
        "I currently work at Snowflake.",
        "Former Oracle architect leading distributed data systems."
    ]
    for draft in test_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Failed to reject unapproved employer in: {draft}"
        assert res.status == GroundingStatus.UNGROUNDED
        assert res.requires_human_review is True
        assert any(u.category == ClaimCategory.EMPLOYER for u in res.unsupported_claims)


def test_opportunity_references_not_classified_as_employment():
    """Inbound recruiter opportunity references must not be falsely flagged as past employment claims."""
    opportunity_texts = [
        "I am interested in the role at Amazon.",
        "Thank you for reaching out regarding the Principal Solutions Architect opening at Microsoft.",
        "My background aligns well with Google Cloud requirements for this position.",
        "I would be glad to connect to discuss the opportunity at Apple."
    ]
    for text in opportunity_texts:
        res = validate_canonical_grounding(text)
        assert res.is_grounded is True, f"Falsely flagged opportunity reference as ungrounded: {text}"
        assert res.requires_human_review is False
        assert len(res.unsupported_claims) == 0


# ===========================================================================
# 8.5 Recipient-Company Collision Tests (Section 4.5)
# ===========================================================================

def test_recipient_company_does_not_bypass_employment_claim():
    """When recipient_company='Amazon', employment assertion at Amazon must still fail closed."""
    # Target opportunity reference -> Safe
    res_opp = validate_canonical_grounding("I am interested in the role at Amazon.", recipient_company="Amazon")
    assert res_opp.is_grounded is True
    assert res_opp.requires_human_review is False

    # First-person employment claim -> MUST BE REJECTED
    draft_claim = "During my time at Amazon, I was Chief Technology Officer."
    res_claim = validate_canonical_grounding(draft_claim, recipient_company="Amazon")
    assert res_claim.is_grounded is False
    assert res_claim.status == GroundingStatus.UNGROUNDED
    assert res_claim.requires_human_review is True
    assert any(u.category in [ClaimCategory.EMPLOYER, ClaimCategory.TITLE] for u in res_claim.unsupported_claims)


def test_recipient_company_google_collision():
    """When recipient_company='Google', employment assertion at Google must still fail closed."""
    # Target opportunity reference -> Safe
    res_opp = validate_canonical_grounding("Thank you for discussing the Google Cloud opportunity.", recipient_company="Google")
    assert res_opp.is_grounded is True

    # Salaried employment assertion at Google -> MUST BE REJECTED
    draft_claim = "I worked at Google from 2018 through 2024 as Chief Architect."
    res_claim = validate_canonical_grounding(draft_claim, recipient_company="Google")
    assert res_claim.is_grounded is False
    assert res_claim.status == GroundingStatus.UNGROUNDED
    assert res_claim.requires_human_review is True


# ===========================================================================
# 8.6 Title and Employer-Title Relationship Tests (Section 4.6)
# ===========================================================================

def test_unapproved_title_assertions_fail():
    """Asserting unapproved executive titles (CTO at Google, CEO, VP of Engineering) must fail."""
    test_cases = [
        "I served as Chief Technology Officer at Google.",
        "I was Chief Executive Officer at Promevo.",
        "My role was Vice President of Engineering.",
        "I was CEO at Acme Corporation."
    ]
    for draft in test_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Failed to reject unapproved title in: {draft}"
        assert res.status == GroundingStatus.UNGROUNDED
        assert res.requires_human_review is True
        assert any(u.category in [ClaimCategory.TITLE, ClaimCategory.EMPLOYER] for u in res.unsupported_claims)


def test_valid_title_at_unauthorized_employer_fails():
    """An approved title (Principal Solutions Architect) attached to a non-canonical employer (Meta) fails."""
    draft = "I served as Principal Solutions Architect at Meta."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert any(u.category == ClaimCategory.EMPLOYER for u in res.unsupported_claims)


def test_target_role_title_reference_not_flagged():
    """Target role references mentioning executive titles must not be treated as candidate employment claims."""
    target_texts = [
        "I am interested in the Chief Technology Officer role at your organization.",
        "The Principal Solutions Architect position aligns with my background."
    ]
    for text in target_texts:
        res = validate_canonical_grounding(text)
        assert res.is_grounded is True, f"Falsely flagged target-role title as ungrounded: {text}"
        assert res.requires_human_review is False


# ===========================================================================
# 8.7 Date and Tenure Chronology Tests (Section 4.7)
# ===========================================================================

def test_invalid_chronology_claims_fail():
    """Chronological contradictions (Google salaried dates, active Promevo in late 2026, MavenCode ended) fail."""
    test_cases = [
        ("I worked at Google from 2018 through 2024.", "Google salaried date range"),
        ("I currently work at Promevo as Senior Solutions Architect.", "Promevo current status (ended Aug 2026)"),
        ("I joined Promevo in 2021.", "Promevo start year mismatch"),
        ("My MavenCode tenure ended in 2025.", "MavenCode active status contradiction"),
        ("I have worked at Google since 2019.", "Google salaried tenure claim")
    ]
    for draft, label in test_cases:
        res = validate_canonical_grounding(draft)
        assert res.is_grounded is False, f"Failed to reject invalid chronology ({label}): {draft}"
        assert res.status == GroundingStatus.UNGROUNDED
        assert res.requires_human_review is True


# ===========================================================================
# 8.8 Malformed and Indeterminate Input Tests (Section 5)
# ===========================================================================

def test_malformed_and_non_string_inputs_fail_closed():
    """None, integers, empty strings, whitespace, and raw JSON must strictly fail closed."""
    bad_inputs = [
        None,
        12345,
        "",
        "   ",
        "\n\t  \n",
        "{'raw': 'json'}",
        '{"status": "grounded", "is_safe": true}',
        ["a", "list"]
    ]
    for bad_input in bad_inputs:
        res = validate_canonical_grounding(bad_input)
        assert res.is_grounded is False, f"Malformed input unexpectedly evaluated as grounded: {bad_input!r}"
        assert res.status == GroundingStatus.VALIDATION_FAILED
        assert res.requires_human_review is True
        assert "VALIDATION_FAILED" in res.status.value
        assert "safe" not in res.validation_summary.lower() or "failed" in res.validation_summary.lower()


# ===========================================================================
# 8.9 Mixed-Claim Tests
# ===========================================================================

def test_mixed_claims_in_separate_sentences():
    """A draft with one valid claim ($8M Google revenue influenced) and one invalid claim ($50M AWS) must fail."""
    draft = (
        "Over my career, I influenced $8M in new Google Cloud revenue. "
        "Additionally, I generated $50M in AWS cloud migrations."
    )
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert "FACT_GOOGLE_REVENUE" in res.verified_fact_ids
    assert len(res.unsupported_claims) >= 1
    assert any("$50M" in u.extracted_text for u in res.unsupported_claims)


def test_mixed_claims_in_same_sentence():
    """A single sentence containing valid ($100M+) and invalid (85% cost cut) claims fails validation."""
    draft = "I delivered $100M+ in enterprise revenue while driving an 85% reduction in cloud infrastructure costs."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True
    assert "FACT_CAREER_IMPACT" in res.verified_fact_ids
    assert any("85%" in u.extracted_text for u in res.unsupported_claims)


def test_valid_amount_with_invalid_employer_mix():
    """Valid $2.1M closed services attached to wrong employer (Amazon) fails."""
    draft = "At Amazon, I closed $2.1M in professional services."
    res = validate_canonical_grounding(draft)
    assert res.is_grounded is False
    assert res.status == GroundingStatus.UNGROUNDED
    assert res.requires_human_review is True


# ===========================================================================
# 8.10 Risk Sentinel Integration Tests (Section 7)
# ===========================================================================

def test_unsupported_claim_produces_non_downgradable_risk_finding():
    """Any unverified career claim must produce UNVERIFIED_CAREER_CLAIM and cannot be downgraded by Gemini."""
    bad_draft = "At Amazon, I generated $4M in annual revenue."
    heuristic_res = analyze_risk_heuristics(
        email_text="Looking for an enterprise architect.",
        draft_text=bad_draft,
        action="DRAFT"
    )
    assert heuristic_res.severity in [RiskSeverity.CAUTION, RiskSeverity.HIGH_RISK]
    assert heuristic_res.recommended_action in ["REVIEW_CAUTION", "BLOCKED"]
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in heuristic_res.detected_categories
    assert heuristic_res.recommended_action != "PROCEED"
    assert heuristic_res.severity != RiskSeverity.SAFE

    # Simulate Gemini returning a false 'SAFE' opinion
    mock_gemini_safe = RiskAssessmentResult(
        severity=RiskSeverity.SAFE,
        is_flagged=False,
        risk_score=0,
        detected_categories=[RiskCategory.CLEAN],
        second_opinion_summary="Everything looks fine to me.",
        recommended_action="PROCEED"
    )
    merged = merge_risk_assessments(heuristic_res, mock_gemini_safe)
    # Monotonic invariant: Merged result MUST retain the caution/unverified finding
    assert merged.severity in [RiskSeverity.CAUTION, RiskSeverity.HIGH_RISK]
    assert merged.recommended_action in ["REVIEW_CAUTION", "BLOCKED"]
    assert RiskCategory.UNVERIFIED_CAREER_CLAIM in merged.detected_categories
    assert merged.recommended_action != "PROCEED"


# ===========================================================================
# 8.11 Scribe Post-Generation & Fallback Revalidation Tests (Section 6)
# ===========================================================================

def test_scribe_valid_grounded_draft_returned():
    """When Gemini returns a perfectly grounded draft, Scribe returns it."""
    valid_draft = (
        "Hi Sarah,\n\n"
        "Thank you for reaching out regarding the Principal Solutions Architect opportunity at Snowflake. "
        "Over my career, I have influenced $8M in new Google Cloud revenue and delivered $100M+ in enterprise revenue.\n\n"
        "I have attached my updated resume for your review.\n\n"
        "Best regards,\nBrian Kinlaw"
    )
    email = EmailMessage(
        id="msg_001",
        sender_name="Sarah Recruiter",
        sender_email="sarah@snowflake.com",
        subject="Opportunity at Snowflake",
        body_text="We have an opening for a Principal Solutions Architect."
    )
    profile = UserProfile(full_name="Brian Kinlaw", current_title="Strategic Advisor")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = valid_draft
    mock_client.models.generate_content.return_value = mock_response

    with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
        result = generate_executive_reply(email, profile)
        assert result == valid_draft


def test_scribe_invalid_model_draft_falls_back_and_revalidates():
    """When Gemini returns an ungrounded draft (e.g. Amazon $4M generated), Scribe uses fallback."""
    hallucinated_draft = "At Amazon, I generated $4M in annual revenue and built their AI platform."
    email = EmailMessage(
        id="msg_002",
        sender_name="Alex Recruiter",
        sender_email="alex@amazon.com",
        subject="Opportunity at Amazon",
        body_text="Interested in your background."
    )
    profile = UserProfile(full_name="Brian Kinlaw", current_title="Strategic Advisor")

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = hallucinated_draft
    mock_client.models.generate_content.return_value = mock_response

    with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
        result = generate_executive_reply(email, profile)
        # Scribe must NOT return the hallucinated draft
        assert result != hallucinated_draft
        assert "At Amazon, I generated $4M" not in result
        # Fallback must be valid and grounded
        val = validate_canonical_grounding(result)
        assert val.is_grounded is True


def test_scribe_empty_none_malformed_model_responses_fallback():
    """Empty, None, or malformed LLM responses trigger fallback that is canonically grounded."""
    email = EmailMessage(
        id="msg_003",
        sender_name="Pat Recruiter",
        sender_email="pat@tech.com",
        subject="Role opening",
        body_text="Role details here."
    )
    profile = UserProfile(full_name="Brian Kinlaw", current_title="Strategic Advisor")

    for bad_response_text in [None, "", "   ", "{'invalid': 'json'}"]:
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = bad_response_text
        mock_client.models.generate_content.return_value = mock_response

        with patch("backend.radar.scribe_service.get_gemini_client", return_value=mock_client):
            result = generate_executive_reply(email, profile)
            assert result is not None
            assert len(result.strip()) > 0
            val = validate_canonical_grounding(result)
            assert val.is_grounded is True


# ===========================================================================
# 8.12 Transmission Isolation Tests (Section 9)
# ===========================================================================

def test_grounding_success_does_not_create_or_invoke_transmission():
    """Grounded validation success does not grant send authority or invoke mail transmission."""
    good_draft = "I influenced $8M in Google Cloud revenue and delivered $100M+ across my career."
    val = validate_canonical_grounding(good_draft)
    assert val.is_grounded is True

    # Even with a perfectly grounded draft, proposing SEND action remains HIGH_RISK + BLOCKED
    risk_res = analyze_risk_heuristics(
        email_text="Inbound inquiry.",
        draft_text=good_draft,
        action="SEND"
    )
    assert risk_res.severity == RiskSeverity.HIGH_RISK
    assert risk_res.recommended_action == "BLOCKED"
    assert RiskCategory.AUTONOMOUS_SEND_POLICY in risk_res.detected_categories
